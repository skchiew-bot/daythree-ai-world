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

    # timeout estimate for gpt-4o: 100 in-tokens + 1000 out-tokens = ~$0.01025
    with pytest.raises(BudgetExceededError) as excinfo:
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(max_model_cost_usd=0.005), usage=BudgetUsage()
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
async def test_unbillable_provider_rejection_counts_as_a_call_but_costs_nothing():
    provider = _ScriptedProvider(_HttpError(401), ok_response())
    gateway = gateway_for(provider)
    outcome = await gateway.generate(make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage())
    (failed,) = outcome.failed_attempts
    assert failed.estimated_cost == Decimal("0")

    # ...and it still counted as a call against max_model_calls.
    provider = _ScriptedProvider(_HttpError(400), ok_response())
    with pytest.raises(BudgetExceededError):
        await gateway_for(provider).generate(
            make_request(), budget_policy=BudgetPolicy(max_model_calls=1), usage=BudgetUsage()
        )
    assert provider.calls == 1


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
