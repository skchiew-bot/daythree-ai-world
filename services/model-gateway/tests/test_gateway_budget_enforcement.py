"""R0 (ADR-013): the gateway must enforce the *whole* BudgetPolicy across its own retry
loop, persist every failed attempt, and refuse unpriced models before any provider call.
"""
import asyncio
from decimal import Decimal

import pytest

from contracts.enums import ModelInvocationStatus
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from model_gateway.errors import UnpricedModelError
from model_gateway.gateway import BudgetExceededError, ModelGateway, ModelGatewayError
from model_gateway.routing.circuit_breaker import CircuitOpenError
from policy_sdk.budgets import BudgetUsage

pytestmark = pytest.mark.unit


def make_request(**overrides) -> ModelRequest:
    defaults = dict(
        provider="openai", model="gpt-4o", system_prompt="s" * 300, user_prompt="",
        max_output_tokens=1000, timeout_seconds=5,
    )
    defaults.update(overrides)
    return ModelRequest(**defaults)


class _ScriptedProvider:
    """Plays back a script: an Exception instance is raised, anything else is returned."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        step = self.script.pop(0) if self.script else RuntimeError("script exhausted")
        if isinstance(step, Exception):
            raise step
        return step


def ok_response(request_model: str = "gpt-4o", inp: int = 100, out: int = 50) -> ModelResponse:
    return ModelResponse(
        text="{}", input_tokens=inp, output_tokens=out, latency_ms=1, provider="openai", model=request_model
    )


class _HttpError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"http {status_code}")


def gateway_for(provider, **kw) -> ModelGateway:
    return ModelGateway(providers={"openai": provider}, backoff_base_seconds=0, **kw)


@pytest.mark.asyncio
async def test_timeouts_with_max_model_calls_1_make_exactly_one_provider_call():
    provider = _ScriptedProvider(TimeoutError(), TimeoutError(), TimeoutError())
    gateway = gateway_for(provider)

    with pytest.raises(BudgetExceededError) as excinfo:
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(max_model_calls=1), usage=BudgetUsage()
        )

    assert provider.calls == 1
    assert "max_model_calls" in excinfo.value.reason
    assert len(excinfo.value.attempts) == 1
    assert excinfo.value.attempts[0].status == ModelInvocationStatus.failed


@pytest.mark.asyncio
async def test_wait_for_timeout_is_a_billed_call():
    class _Hangs:
        calls = 0

        async def generate(self, request):
            _Hangs.calls += 1
            await asyncio.sleep(30)

    gateway = gateway_for(_Hangs())
    with pytest.raises(BudgetExceededError) as excinfo:
        await gateway.generate(
            make_request(timeout_seconds=1), budget_policy=BudgetPolicy(max_model_calls=1), usage=BudgetUsage()
        )
    assert _Hangs.calls == 1
    (attempt,) = excinfo.value.attempts
    assert attempt.estimated_cost > 0  # never undercount a timeout


@pytest.mark.asyncio
async def test_incoming_usage_counts_toward_the_in_loop_budget():
    provider = _ScriptedProvider(RuntimeError("boom"), ok_response())
    gateway = gateway_for(provider)

    # 1 call already made elsewhere (e.g. the first execute); this call's attempt 1 is
    # allowed (calls_made=1 < 2), attempt 2 is not (1 + 1 attempt >= 2).
    with pytest.raises(BudgetExceededError):
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(max_model_calls=2), usage=BudgetUsage(calls_made=1)
        )
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cost_of_a_failed_attempt_trips_the_cost_ceiling_on_the_retry():
    provider = _ScriptedProvider(TimeoutError(), ok_response())
    gateway = gateway_for(provider)

    # A call's worst case (and so a timeout's charge) for gpt-4o here is $0.01025: the first
    # attempt fits under the $0.02 ceiling, but after it is charged the retry no longer does.
    with pytest.raises(BudgetExceededError) as excinfo:
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(max_model_cost_usd=0.02), usage=BudgetUsage()
        )
    assert provider.calls == 1
    assert "max_model_cost_usd" in excinfo.value.reason


@pytest.mark.asyncio
async def test_max_retries_zero_allows_only_one_attempt():
    provider = _ScriptedProvider(RuntimeError("boom"), ok_response())
    gateway = gateway_for(provider)
    with pytest.raises(BudgetExceededError) as excinfo:
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(max_retries=0), usage=BudgetUsage()
        )
    assert provider.calls == 1
    assert "max_retries" in excinfo.value.reason


@pytest.mark.asyncio
async def test_prior_retries_count_toward_max_retries():
    provider = _ScriptedProvider(RuntimeError("boom"), ok_response())
    gateway = gateway_for(provider)
    with pytest.raises(BudgetExceededError):
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(max_retries=2), usage=BudgetUsage(retries_made=2)
        )
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_failed_attempts_are_returned_alongside_a_later_success():
    provider = _ScriptedProvider(RuntimeError("boom"), ok_response())
    gateway = gateway_for(provider)
    outcome = await gateway.generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())

    assert outcome.attempts == 2
    assert [t.status for t in outcome.failed_attempts] == [ModelInvocationStatus.failed]
    assert outcome.telemetry.status == ModelInvocationStatus.completed


@pytest.mark.asyncio
async def test_exhausted_retries_error_carries_every_attempt():
    provider = _ScriptedProvider(RuntimeError("a"), RuntimeError("b"))
    gateway = gateway_for(provider, max_attempts=2)
    with pytest.raises(ModelGatewayError) as excinfo:
        await gateway.generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())
    assert len(excinfo.value.attempts) == 2
    assert all(a.status == ModelInvocationStatus.failed for a in excinfo.value.attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 404])
async def test_permanent_provider_rejection_fails_at_once_and_costs_nothing(status):
    """A 4xx that is not 408/429 will fail identically on every retry: one call (counted,
    at cost 0), no further attempts."""
    provider = _ScriptedProvider(_HttpError(status), ok_response())
    with pytest.raises(ModelGatewayError) as excinfo:
        await gateway_for(provider).generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())

    assert provider.calls == 1
    (attempt,) = excinfo.value.attempts
    assert attempt.status == ModelInvocationStatus.failed
    assert attempt.estimated_cost == Decimal("0")


@pytest.mark.asyncio
async def test_permanent_rejections_do_not_feed_the_circuit_breaker():
    from model_gateway.routing.circuit_breaker import CircuitBreaker

    provider = _ScriptedProvider(_HttpError(400), _HttpError(400), ok_response())
    gateway = ModelGateway(
        providers={"openai": provider}, backoff_base_seconds=0,
        circuit_breaker=CircuitBreaker(failure_threshold=1, cooldown_seconds=60),
    )
    for _ in range(2):
        with pytest.raises(ModelGatewayError) as excinfo:
            await gateway.generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())
        assert not isinstance(excinfo.value, CircuitOpenError)  # the breaker never opened

    assert (await gateway.generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())).attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [_HttpError(429), _HttpError(500), _HttpError(408)])
async def test_transient_errors_are_still_retried(error):
    provider = _ScriptedProvider(error, ok_response())
    outcome = await gateway_for(provider).generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())
    assert outcome.attempts == 2


@pytest.mark.asyncio
async def test_a_call_whose_worst_case_cost_would_pass_the_ceiling_is_refused_up_front():
    """gpt-4o at 8000 max output tokens can cost $0.08; a $0.01 ceiling must refuse it
    before the call, not discover the overshoot afterwards."""
    provider = _ScriptedProvider(ok_response())
    with pytest.raises(BudgetExceededError) as excinfo:
        await gateway_for(provider).generate(
            make_request(max_output_tokens=8000), budget_policy=BudgetPolicy(max_model_cost_usd=0.01),
            usage=BudgetUsage(),
        )
    assert provider.calls == 0
    assert "max_model_cost_usd" in excinfo.value.reason


@pytest.mark.asyncio
async def test_worst_case_is_added_to_what_is_already_spent():
    # worst case for this request: 100 in-tokens + 1000 out-tokens = $0.01025
    request = make_request()
    ok = _ScriptedProvider(ok_response())
    await gateway_for(ok).generate(
        request, budget_policy=BudgetPolicy(max_model_cost_usd=0.5), usage=BudgetUsage(cost_spent_usd=0.4)
    )
    assert ok.calls == 1

    refused = _ScriptedProvider(ok_response())
    with pytest.raises(BudgetExceededError):
        await gateway_for(refused).generate(
            request, budget_policy=BudgetPolicy(max_model_cost_usd=0.5), usage=BudgetUsage(cost_spent_usd=0.495)
        )
    assert refused.calls == 0


@pytest.mark.asyncio
async def test_first_attempt_circuit_open_is_a_clean_gateway_error_with_no_attempts():
    """It must not escape as a bare exception: the mission engine only fails a task
    cleanly on ModelGatewayError, and a stuck `running` task gets requeued and re-charged."""
    from model_gateway.routing.circuit_breaker import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    breaker.record_failure("openai")
    provider = _ScriptedProvider(ok_response())
    with pytest.raises(ModelGatewayError) as excinfo:
        await ModelGateway(providers={"openai": provider}, circuit_breaker=breaker).generate(
            make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
        )
    assert isinstance(excinfo.value, CircuitOpenError)
    assert excinfo.value.attempts == ()
    assert provider.calls == 0


class _RecordingLedger:
    """Stands in for the DB-backed write-ahead ledger."""

    def __init__(self, fail_begin_on: int | None = None):
        self.events: list[tuple] = []
        self._fail_begin_on = fail_begin_on

    async def begin_attempt(self, worst_case):
        if self._fail_begin_on == len(self.begun) + 1:
            raise RuntimeError("ledger write failed")
        self.events.append(("begin", worst_case))
        return len(self.begun)

    async def finish_attempt(self, attempt_id, outcome):
        self.events.append(("finish", attempt_id, outcome))

    @property
    def begun(self):
        return [e for e in self.events if e[0] == "begin"]

    @property
    def finished(self):
        return [e for e in self.events if e[0] == "finish"]


@pytest.mark.asyncio
async def test_every_attempt_is_written_ahead_at_worst_case_then_finished():
    provider = _ScriptedProvider(TimeoutError(), ok_response(inp=100, out=50))
    ledger = _RecordingLedger()
    await gateway_for(provider).generate(
        make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage(), ledger=ledger
    )

    assert [e[0] for e in ledger.events] == ["begin", "finish", "begin", "finish"]
    for _, worst in ledger.begun:
        assert worst.status == ModelInvocationStatus.requested
        assert worst.output_tokens == 1000  # the full max_output_tokens
        assert worst.estimated_cost == Decimal("0.01025")
    (_, _, failed), (_, _, completed) = ledger.finished
    assert failed.status == ModelInvocationStatus.failed and failed.estimated_cost == Decimal("0.01025")
    assert completed.status == ModelInvocationStatus.completed
    assert completed.estimated_cost == Decimal("0.00075")  # actual usage, not the worst case


@pytest.mark.asyncio
async def test_a_permanent_rejection_is_finished_at_zero_cost():
    ledger = _RecordingLedger()
    with pytest.raises(ModelGatewayError):
        await gateway_for(_ScriptedProvider(_HttpError(401))).generate(
            make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage(), ledger=ledger
        )
    ((_, _, outcome),) = ledger.finished
    assert outcome.status == ModelInvocationStatus.failed and outcome.estimated_cost == Decimal("0")


@pytest.mark.asyncio
async def test_no_provider_call_when_the_write_ahead_cannot_be_recorded():
    provider = _ScriptedProvider(ok_response())
    with pytest.raises(RuntimeError, match="ledger write failed"):
        await gateway_for(provider).generate(
            make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage(),
            ledger=_RecordingLedger(fail_begin_on=1),
        )
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_a_cancelled_call_leaves_its_write_ahead_row_unfinished():
    """Lease loss cancels the work mid-call: the row written ahead stays as the
    conservative charge, and the second of three attempts is charged too."""
    started = asyncio.Event()

    class _HangsOnSecond:
        calls = 0

        async def generate(self, request):
            _HangsOnSecond.calls += 1
            if _HangsOnSecond.calls == 1:
                raise TimeoutError()
            started.set()
            await asyncio.sleep(60)

    ledger = _RecordingLedger()
    task = asyncio.ensure_future(
        gateway_for(_HangsOnSecond()).generate(
            make_request(timeout_seconds=30), budget_policy=BudgetPolicy(), usage=BudgetUsage(), ledger=ledger
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(ledger.begun) == 2  # both attempts are on the books
    assert len(ledger.finished) == 1  # only the first was finished; the second stays conservative


@pytest.mark.asyncio
async def test_a_success_without_reported_usage_is_flagged_and_still_costs_something():
    response = ok_response(inp=333, out=444).model_copy(update={"usage_estimated": True})
    outcome = await gateway_for(_ScriptedProvider(response)).generate(
        make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
    )
    assert outcome.telemetry.usage_estimated is True
    assert outcome.telemetry.estimated_cost > 0


@pytest.mark.asyncio
async def test_unpriced_model_raises_before_any_provider_call():
    provider = _ScriptedProvider(ok_response())
    gateway = gateway_for(provider)
    with pytest.raises(UnpricedModelError):
        await gateway.generate(
            make_request(model="gpt-unheard-of"), budget_policy=BudgetPolicy(), usage=BudgetUsage()
        )
    assert provider.calls == 0


def test_unpriced_model_error_is_a_gateway_error():
    # so the mission engine's existing `except ModelGatewayError` fails the task cleanly
    assert issubclass(UnpricedModelError, ModelGatewayError)


@pytest.mark.asyncio
async def test_circuit_opening_mid_loop_still_reports_the_attempts_made():
    from model_gateway.routing.circuit_breaker import CircuitBreaker

    provider = _ScriptedProvider(RuntimeError("a"), RuntimeError("b"))
    gateway = ModelGateway(
        providers={"openai": provider}, backoff_base_seconds=0,
        circuit_breaker=CircuitBreaker(failure_threshold=1, cooldown_seconds=60),
    )
    with pytest.raises(ModelGatewayError) as excinfo:
        await gateway.generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())
    assert provider.calls == 1
    assert len(excinfo.value.attempts) == 1
