"""DB-backed usage reader and write-ahead ledger for one task (R0, ADR-013).

Reading: what a task has already consumed, from `model_invocations`, so the budget check
sees real numbers instead of a fresh zero.

- calls_made      : every invocation row for the task, whatever its status (a failed,
                    timed-out or never-finished attempt can still have been billed).
- cost_spent_usd  : sum of `estimated_cost` over those rows.
- retries_made    : rows that are not `completed`, i.e. attempts that failed or never
                    finished. Task-wide, so `max_retries` is a per-task ceiling.
- elapsed_minutes : wall-clock time since THIS execution attempt of the task began
                    (`execute_task` constructs the provider at its start). Calls and cost
                    are cumulative across attempts because they are money; runtime is per
                    attempt, otherwise an operator `/retry` (or a worker resume) hours later
                    would find `max_runtime_minutes` already blown and could never run.

Writing (the gateway's `AttemptLedger`): `begin_attempt` inserts a `requested` row at the
worst-case cost and COMMITS it before the provider request is sent; `finish_attempt`
rewrites that row with the outcome and commits. The invariant: after any crash, lease loss
or commit failure the committed charges are >= the provider requests that may have been
sent, because an attempt that was never finished keeps its worst-case `requested` charge.
A `requested` row left behind therefore means "sent, outcome unknown".

These commits also commit whatever else the session has staged, the same behaviour as
`SqlCheckpointStore.save`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import ModelInvocation
from contracts.enums import ModelInvocationStatus
from contracts.ids import EntityId, new_id
from model_gateway.telemetry import ModelInvocationTelemetry
from policy_sdk.budgets import BudgetUsage

_SECONDS_PER_MINUTE = 60


class SqlUsageProvider:
    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_id: EntityId,
        mission_id: EntityId,
        task_id: EntityId,
        agent_id: EntityId,
        attempt_started_at: datetime | None = None,
    ):
        self._session = session
        self._tenant_id = tenant_id
        self._mission_id = mission_id
        self._task_id = task_id
        self._agent_id = agent_id
        self._attempt_started_at = attempt_started_at or datetime.now(timezone.utc)

    async def usage_for_task(self, task_id: EntityId) -> BudgetUsage:
        completed = ModelInvocationStatus.completed.value
        result = await self._session.execute(
            select(
                func.count(ModelInvocation.id),
                func.coalesce(func.sum(ModelInvocation.estimated_cost), 0),
                func.count(ModelInvocation.id).filter(ModelInvocation.status != completed),
            ).where(ModelInvocation.task_id == task_id)
        )
        calls, cost, unfinished_or_failed = result.one()
        elapsed = datetime.now(timezone.utc) - self._attempt_started_at
        return BudgetUsage(
            calls_made=int(calls),
            cost_spent_usd=float(cost),
            elapsed_minutes=elapsed.total_seconds() / _SECONDS_PER_MINUTE,
            retries_made=int(unfinished_or_failed),
        )

    async def begin_attempt(self, worst_case: ModelInvocationTelemetry) -> EntityId:
        attempt_id = new_id()
        self._session.add(
            ModelInvocation(
                id=attempt_id, tenant_id=self._tenant_id, mission_id=self._mission_id,
                task_id=self._task_id, agent_id=self._agent_id, **_row_values(worst_case),
            )
        )
        await self._session.commit()
        return attempt_id

    async def finish_attempt(self, attempt_id: EntityId, outcome: ModelInvocationTelemetry) -> None:
        await self._session.execute(
            update(ModelInvocation).where(ModelInvocation.id == attempt_id).values(**_row_values(outcome))
        )
        await self._session.commit()


def _row_values(telemetry: ModelInvocationTelemetry) -> dict:
    return {
        "provider": telemetry.provider, "model": telemetry.model,
        "input_tokens": telemetry.input_tokens, "output_tokens": telemetry.output_tokens,
        "estimated_cost": telemetry.estimated_cost, "latency_ms": telemetry.latency_ms,
        "status": telemetry.status.value, "request_hash": telemetry.request_hash,
        "response_hash": telemetry.response_hash,
    }
