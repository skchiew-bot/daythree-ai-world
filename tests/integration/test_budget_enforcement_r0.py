"""R0 (ADR-013) exit criteria, end to end against a real Postgres: the per-task BudgetPolicy
is enforced across retries, output repair and crash-resume, and every failed attempt
lands in `model_invocations`. A pre-R0 build fails every test in this module.

No real provider is ever called: the "openai" provider registered here is a scripted fake.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from common.db.models import ModelInvocation, RuntimeCheckpoint, Task
from contracts.enums import EventType, ModelInvocationStatus, TaskStatus
from contracts.ids import new_id
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.task_executor import execute_task
from mission_engine.engine.usage import SqlUsageProvider
from model_gateway.gateway import ModelGateway
from model_gateway.routing.circuit_breaker import CircuitBreaker
from model_gateway.telemetry import ModelInvocationTelemetry

pytestmark = pytest.mark.integration

VALID_OUTPUT = json.dumps(
    {
        "title": "T", "executive_summary": "S",
        "sections": [{"heading": "H", "content": "C"}],
        "assumptions": [], "risks": [], "open_questions": [],
    }
)


class ScriptedProvider:
    """Each generate() pops the next step: an Exception is raised, a str is returned as the
    model's text (with fixed token counts), a ModelResponse is returned as is."""

    def __init__(self, *script, input_tokens: int = 1000, output_tokens: int = 1000):
        self.script = list(script)
        self.calls = 0
        self._tokens = (input_tokens, output_tokens)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ModelResponse(
            text=step, input_tokens=self._tokens[0], output_tokens=self._tokens[1], latency_ms=1,
            provider="openai", model=request.model,
        )


async def _prepare(db_session, seeded, engine_deps, provider, budget: BudgetPolicy, *, model="gpt-4o", **gateway_kw):
    """A started, queued task on an 'openai' model policy, plus deps wired to `provider`."""
    seeded["model_policy"].primary_provider = "openai"
    seeded["model_policy"].primary_model = model
    await db_session.flush()
    deps = dataclasses.replace(
        engine_deps,
        model_gateway=ModelGateway(providers={"openai": provider}, backoff_base_seconds=0, **gateway_kw),
    )
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code=f"MSN-R0-{new_id().hex[:8]}",
        title="R0", objective="x", requested_by=None, assigned_agent_id=seeded["agent"].id,
        budget_policy=budget,
    )
    await db_session.commit()
    started = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()
    return deps, started.task


async def _run(db_session, seeded, engine_deps, provider, budget: BudgetPolicy, *, model="gpt-4o", **gateway_kw):
    deps, task = await _prepare(db_session, seeded, engine_deps, provider, budget, model=model, **gateway_kw)
    await execute_task(db_session, deps, task.id)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class _RaisesOn:
    """Wraps the event publisher and blows up when a given event is published."""

    def __init__(self, inner, event_type: EventType):
        self._inner = inner
        self._event_type = event_type

    async def publish(self, event, session) -> None:
        if event.event_type == self._event_type:
            raise RuntimeError("simulated crash / commit failure after the model call")
        await self._inner.publish(event, session)


async def _invocations(db_session, task_id) -> list[ModelInvocation]:
    result = await db_session.execute(select(ModelInvocation).where(ModelInvocation.task_id == task_id))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_max_model_calls_1_with_two_timeouts_makes_exactly_one_provider_call(
    db_session, seeded, engine_deps
):
    provider = ScriptedProvider(TimeoutError(), TimeoutError(), TimeoutError())
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1))

    assert provider.calls == 1
    assert task.status == TaskStatus.failed.value
    rows = await _invocations(db_session, task.id)
    assert [r.status for r in rows] == [ModelInvocationStatus.failed.value]
    assert rows[0].estimated_cost > 0  # the timed-out call is charged, not free


@pytest.mark.asyncio
async def test_cost_ceiling_trips_on_the_second_call_once_the_first_is_committed(
    db_session, seeded, engine_deps
):
    # Worst case of one call is about $0.0117 (gpt-4o, 1000 max output tokens plus the prompt),
    # under the $0.02 ceiling, so the first call runs. It answers with invalid output at an
    # actual $0.0125 (1000 in + 1000 out); spent + the repair call's worst case is then over
    # the ceiling, so the repair call must be refused.
    provider = ScriptedProvider("not json", VALID_OUTPUT)
    task = await _run(
        db_session, seeded, engine_deps, provider,
        BudgetPolicy(max_model_cost_usd=0.02, max_output_tokens=1000),
    )

    assert provider.calls == 1
    assert task.status == TaskStatus.failed.value
    rows = await _invocations(db_session, task.id)
    assert len(rows) == 1 and rows[0].estimated_cost == Decimal("0.012500")  # finished at actual cost


@pytest.mark.asyncio
async def test_a_call_whose_worst_case_would_cross_the_ceiling_never_reaches_the_provider(
    db_session, seeded, engine_deps
):
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_cost_usd=0.01))

    assert provider.calls == 0  # 8000 max output tokens on gpt-4o is $0.08 worst case
    assert task.status == TaskStatus.failed.value
    assert await _invocations(db_session, task.id) == []


@pytest.mark.asyncio
async def test_output_repair_counts_against_the_same_call_budget(db_session, seeded, engine_deps):
    provider = ScriptedProvider("not json", VALID_OUTPUT)
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1))

    assert provider.calls == 1  # repair refused, not silently allowed
    assert task.status == TaskStatus.failed.value


@pytest.mark.asyncio
async def test_repair_is_allowed_when_the_budget_has_room(db_session, seeded, engine_deps):
    provider = ScriptedProvider("not json", VALID_OUTPUT)
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=2))

    assert provider.calls == 2
    assert task.status == TaskStatus.completed.value
    assert len(await _invocations(db_session, task.id)) == 2


@pytest.mark.asyncio
async def test_failed_attempts_appear_in_model_invocations_before_a_later_success(
    db_session, seeded, engine_deps
):
    provider = ScriptedProvider(RuntimeError("boom"), TimeoutError(), VALID_OUTPUT)
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy())

    assert provider.calls == 3
    assert task.status == TaskStatus.completed.value
    statuses = sorted(r.status for r in await _invocations(db_session, task.id))
    assert statuses == ["completed", "failed", "failed"]


@pytest.mark.asyncio
async def test_unpriced_model_fails_the_task_and_makes_no_provider_call(db_session, seeded, engine_deps):
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _run(
        db_session, seeded, engine_deps, provider, BudgetPolicy(), model="gpt-not-in-the-price-table"
    )

    assert provider.calls == 0
    assert task.status == TaskStatus.failed.value
    assert await _invocations(db_session, task.id) == []


async def _interrupted_task(
    db_session, seeded, engine_deps, provider, budget, *, status, committed_rows=0, row_status="completed"
):
    """A task whose worker died mid-call: its checkpoint sits at `prompt_assembled`, with
    `committed_rows` invocation rows already committed (`row_status`: `completed`, or
    `requested` for a call written ahead and never finished) and the given task status
    (`running` = found by the orphan sweep; `queued` = an operator /retry)."""
    deps, task = await _prepare(db_session, seeded, engine_deps, provider, budget)
    mission_id = task.mission_id
    for _ in range(committed_rows):
        db_session.add(
            ModelInvocation(
                tenant_id=seeded["tenant"].id, mission_id=mission_id, task_id=task.id,
                agent_id=seeded["agent"].id, provider="openai", model="gpt-4o", input_tokens=10,
                output_tokens=10, estimated_cost=Decimal("0.001"), latency_ms=1, status=row_status,
                request_hash="h",
            )
        )
    db_session.add(
        RuntimeCheckpoint(
            id=new_id(), mission_id=mission_id, task_id=task.id, agent_id=seeded["agent"].id,
            checkpoint_sequence=1,
            state={
                "stage": "prompt_assembled", "system_prompt": "s" * 300, "user_prompt": "u",
                "provider": "openai", "model": "gpt-4o", "max_output_tokens": 100,
                "budget_policy": budget.model_dump(),
            },
        )
    )
    task.status = status
    await db_session.commit()

    await execute_task(db_session, deps, task.id)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest.mark.asyncio
async def test_resume_after_crash_sees_committed_calls_and_is_refused(db_session, seeded, engine_deps):
    """One call is already committed and the checkpoint sits at `prompt_assembled` (an
    operator /retry). The resumed call must be budgeted against the committed usage."""
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1),
        status=TaskStatus.queued.value, committed_rows=1,
    )

    assert provider.calls == 0
    assert task.status == TaskStatus.failed.value


@pytest.mark.asyncio
async def test_a_call_written_ahead_and_never_finished_counts_on_resume(db_session, seeded, engine_deps):
    """The dead worker wrote its attempt ahead (`requested`, conservative cost) and never
    finished it: the resume must count that call, so a worker that keeps dying mid-call
    cannot loop past `max_model_calls` for free."""
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1),
        status=TaskStatus.running.value, committed_rows=1, row_status="requested",
    )

    assert provider.calls == 0
    assert task.status == TaskStatus.failed.value
    assert [r.status for r in await _invocations(db_session, task.id)] == ["requested"]


@pytest.mark.asyncio
async def test_recovery_still_runs_when_the_budget_has_room_for_the_unfinished_call(
    db_session, seeded, engine_deps
):
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=2),
        status=TaskStatus.running.value, committed_rows=1, row_status="requested",
    )

    assert provider.calls == 1
    assert task.status == TaskStatus.completed.value
    assert sorted(r.status for r in await _invocations(db_session, task.id)) == ["completed", "requested"]


@pytest.mark.asyncio
async def test_no_charge_is_invented_for_a_call_that_was_never_written_ahead(db_session, seeded, engine_deps):
    """Resuming a `running` task whose worker died before any provider attempt began must
    not add a charge for a call that cannot have been sent."""
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1),
        status=TaskStatus.running.value,
    )

    assert provider.calls == 1
    assert task.status == TaskStatus.completed.value
    assert [r.status for r in await _invocations(db_session, task.id)] == ["completed"]


@pytest.mark.asyncio
async def test_a_crash_after_the_model_answered_keeps_its_charge(db_session, seeded, engine_deps):
    """The invocation row is committed with the attempt, not staged for a later commit: a
    failure right after the model answered (here: publishing model.completed) rolls the
    session back, and the billed call must still be on the books."""
    provider = ScriptedProvider(VALID_OUTPUT)
    deps, task = await _prepare(db_session, seeded, engine_deps, provider, BudgetPolicy())
    deps = dataclasses.replace(deps, event_publisher=_RaisesOn(deps.event_publisher, EventType.model_completed))

    with pytest.raises(RuntimeError, match="simulated crash"):
        await execute_task(db_session, deps, task.id)
    await db_session.rollback()  # what the worker does with an exception

    (row,) = await _invocations(db_session, task.id)
    assert row.status == ModelInvocationStatus.completed.value
    assert row.estimated_cost == Decimal("0.012500")  # finished at actual usage: 1000 in + 1000 out on gpt-4o
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_losing_the_lease_during_the_second_of_three_attempts_leaves_both_charged(
    db_session, seeded, engine_deps
):
    """Lease loss cancels the work mid-call. The first attempt (a timeout) and the second
    (in flight, never finished) are both committed charges; nothing is lost with the
    rollback."""
    second_attempt_started = asyncio.Event()

    class _HangsOnSecondAttempt:
        calls = 0

        async def generate(self, request):
            _HangsOnSecondAttempt.calls += 1
            if _HangsOnSecondAttempt.calls == 1:
                raise TimeoutError()
            second_attempt_started.set()
            await asyncio.sleep(60)

    deps, task = await _prepare(db_session, seeded, engine_deps, _HangsOnSecondAttempt(), BudgetPolicy())
    running = asyncio.ensure_future(execute_task(db_session, deps, task.id))
    await asyncio.wait_for(second_attempt_started.wait(), timeout=30)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    await db_session.rollback()

    rows = await _invocations(db_session, task.id)
    assert sorted(r.status for r in rows) == ["failed", "requested"]
    assert all(r.estimated_cost > 0 for r in rows)  # both at the conservative worst case


@pytest.mark.asyncio
async def test_an_open_circuit_fails_the_task_cleanly_with_no_phantom_charge(db_session, seeded, engine_deps):
    """A first attempt refused by the circuit breaker sends nothing. It must fail the task
    (not leave it `running` to be requeued and re-charged) and record no charge."""
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    breaker.record_failure("openai")
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy(), circuit_breaker=breaker)

    assert provider.calls == 0
    assert task.status == TaskStatus.failed.value
    assert await _invocations(db_session, task.id) == []


async def _started_ledger(db_session, seeded, engine_deps) -> tuple[SqlUsageProvider, Task]:
    deps, task = await _prepare(db_session, seeded, engine_deps, ScriptedProvider(), BudgetPolicy())
    ledger = SqlUsageProvider(
        db_session, tenant_id=seeded["tenant"].id, mission_id=task.mission_id, task_id=task.id,
        agent_id=seeded["agent"].id,
    )
    return ledger, task


def _worst_case() -> ModelInvocationTelemetry:
    return ModelInvocationTelemetry(
        provider="openai", model="gpt-4o", input_tokens=100, output_tokens=1000,
        estimated_cost=Decimal("0.01025"), latency_ms=0, status=ModelInvocationStatus.requested,
        request_hash="h",
    )


@pytest.mark.asyncio
async def test_a_commit_failure_while_finishing_an_attempt_leaves_the_conservative_charge(
    db_session, seeded, engine_deps, monkeypatch
):
    ledger, task = await _started_ledger(db_session, seeded, engine_deps)
    attempt_id = await ledger.begin_attempt(_worst_case())  # committed write-ahead

    real_commit = db_session.commit

    async def _failing_commit():
        raise ConnectionError("commit failed")

    monkeypatch.setattr(db_session, "commit", _failing_commit)
    outcome = _worst_case().model_copy(update={"status": ModelInvocationStatus.completed, "estimated_cost": Decimal("0.001")})
    with pytest.raises(ConnectionError):
        await ledger.finish_attempt(attempt_id, outcome)
    monkeypatch.setattr(db_session, "commit", real_commit)
    await db_session.rollback()

    usage = await ledger.usage_for_task(task.id)
    assert usage.calls_made == 1
    assert usage.cost_spent_usd == pytest.approx(0.01025)  # still the worst case, never lost or zeroed


@pytest.mark.asyncio
async def test_usage_counts_every_status_and_sums_their_cost(db_session, seeded, engine_deps):
    ledger, task = await _started_ledger(db_session, seeded, engine_deps)
    for status, cost in (("completed", "0.5"), ("failed", "0.25"), ("requested", "0.125")):
        attempt_id = await ledger.begin_attempt(_worst_case())
        await ledger.finish_attempt(
            attempt_id, _worst_case().model_copy(update={"status": ModelInvocationStatus(status), "estimated_cost": Decimal(cost)})
        )

    usage = await ledger.usage_for_task(task.id)
    assert usage.calls_made == 3
    assert usage.cost_spent_usd == pytest.approx(0.875)
    assert usage.retries_made == 2  # the failed and the never-finished attempts


@pytest.mark.asyncio
async def test_an_operator_retry_does_not_add_a_phantom_orphan_charge(db_session, seeded, engine_deps):
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1),
        status=TaskStatus.queued.value,
    )

    assert provider.calls == 1
    assert [r.status for r in await _invocations(db_session, task.id)] == ["completed"]
