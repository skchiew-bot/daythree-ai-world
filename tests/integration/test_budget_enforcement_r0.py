"""R0 (ADR-013) exit criteria, end to end against a real Postgres: the per-task BudgetPolicy
is enforced across retries, output repair and crash-resume, and every failed attempt
lands in `model_invocations`. A pre-R0 build fails every test in this module.

No real provider is ever called: the "openai" provider registered here is a scripted fake.
"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from common.db.models import ModelInvocation, RuntimeCheckpoint, Task
from contracts.enums import ModelInvocationStatus, TaskStatus
from contracts.ids import new_id
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.task_executor import execute_task
from model_gateway.gateway import ModelGateway

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


async def _run(db_session, seeded, engine_deps, provider, budget: BudgetPolicy, *, model="gpt-4o"):
    seeded["model_policy"].primary_provider = "openai"
    seeded["model_policy"].primary_model = model
    await db_session.flush()
    deps = dataclasses.replace(
        engine_deps,
        model_gateway=ModelGateway(providers={"openai": provider}, backoff_base_seconds=0),
    )
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code=f"MSN-R0-{new_id().hex[:8]}",
        title="R0", objective="x", requested_by=None, assigned_agent_id=seeded["agent"].id,
        budget_policy=budget,
    )
    await db_session.commit()
    started = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()
    await execute_task(db_session, deps, started.task.id)
    await db_session.commit()
    task = await db_session.get(Task, started.task.id)
    await db_session.refresh(task)
    return task


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
    # First call answers with invalid output at $0.0125 (gpt-4o, 1000 in + 1000 out) which
    # is over the $0.01 ceiling; the repair call must therefore be refused.
    provider = ScriptedProvider("not json", VALID_OUTPUT)
    task = await _run(db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_cost_usd=0.01))

    assert provider.calls == 1
    assert task.status == TaskStatus.failed.value
    rows = await _invocations(db_session, task.id)
    assert len(rows) == 1 and rows[0].estimated_cost == Decimal("0.012500")


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


async def _interrupted_task(db_session, seeded, engine_deps, provider, budget, *, status, committed_rows=0):
    """A task whose worker died mid-call: its checkpoint sits at `prompt_assembled`, with
    `committed_rows` completed invocations already committed and the given task status
    (`running` = found by the orphan sweep; `queued` = an operator /retry)."""
    seeded["model_policy"].primary_provider = "openai"
    seeded["model_policy"].primary_model = "gpt-4o"
    await db_session.flush()
    deps = dataclasses.replace(
        engine_deps, model_gateway=ModelGateway(providers={"openai": provider}, backoff_base_seconds=0)
    )
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code=f"MSN-R0-{new_id().hex[:8]}", title="R0",
        objective="x", requested_by=None, assigned_agent_id=seeded["agent"].id, budget_policy=budget,
    )
    await db_session.commit()
    started = await start_mission(db_session, mission_id=mission.id)
    task = started.task
    for _ in range(committed_rows):
        db_session.add(
            ModelInvocation(
                tenant_id=seeded["tenant"].id, mission_id=mission.id, task_id=task.id,
                agent_id=seeded["agent"].id, provider="openai", model="gpt-4o", input_tokens=10,
                output_tokens=10, estimated_cost=Decimal("0.001"), latency_ms=1, status="completed",
                request_hash="h",
            )
        )
    db_session.add(
        RuntimeCheckpoint(
            id=new_id(), mission_id=mission.id, task_id=task.id, agent_id=seeded["agent"].id,
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
async def test_a_call_orphaned_by_a_dead_worker_is_charged_before_the_resume(db_session, seeded, engine_deps):
    """The dead worker's provider call may have been billed, and nothing recorded it. On
    recovery (task found `running`) it is charged conservatively as one failed call, so a
    worker that keeps dying mid-call cannot loop past `max_model_calls` for free."""
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1),
        status=TaskStatus.running.value,
    )

    assert provider.calls == 0  # the presumed in-flight call already used the only call
    assert task.status == TaskStatus.failed.value
    (row,) = await _invocations(db_session, task.id)
    assert row.status == ModelInvocationStatus.failed.value
    assert row.estimated_cost > 0
    assert row.output_tokens == 100  # the checkpointed max_output_tokens


@pytest.mark.asyncio
async def test_recovery_of_an_orphaned_call_still_runs_when_the_budget_has_room(db_session, seeded, engine_deps):
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=2),
        status=TaskStatus.running.value,
    )

    assert provider.calls == 1
    assert task.status == TaskStatus.completed.value
    assert sorted(r.status for r in await _invocations(db_session, task.id)) == ["completed", "failed"]


@pytest.mark.asyncio
async def test_an_operator_retry_does_not_add_a_phantom_orphan_charge(db_session, seeded, engine_deps):
    provider = ScriptedProvider(VALID_OUTPUT)
    task = await _interrupted_task(
        db_session, seeded, engine_deps, provider, BudgetPolicy(max_model_calls=1),
        status=TaskStatus.queued.value,
    )

    assert provider.calls == 1
    assert [r.status for r in await _invocations(db_session, task.id)] == ["completed"]
