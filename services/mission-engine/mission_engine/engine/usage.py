"""DB-backed `UsageProvider` (R0, ADR-013): what a task has already consumed, read from
`model_invocations`, so the budget check sees real numbers instead of a fresh zero.

- calls_made      : every invocation row for the task, INCLUDING failed and timed-out
                    attempts (a failed attempt can still have been billed).
- cost_spent_usd  : sum of `estimated_cost` over those rows (failed rows carry the
                    conservative estimate described in `model_gateway.telemetry`).
- retries_made    : failed rows, i.e. attempts that had to be retried or given up on. It is
                    task-wide, so `max_retries` is a per-task ceiling, not a per-call one.
- elapsed_minutes : wall-clock time since THIS execution attempt of the task began
                    (`execute_task` constructs the provider at its start). Calls and cost
                    are cumulative across attempts because they are money; runtime is per
                    attempt, otherwise an operator `/retry` (or a worker resume) hours later
                    would find `max_runtime_minutes` already blown and could never run.

The query sees rows added earlier in the same session (autoflush), so it is correct
between the first execute and the repair execute even before the worker's final commit.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import ModelInvocation
from contracts.enums import ModelInvocationStatus
from contracts.ids import EntityId
from policy_sdk.budgets import BudgetUsage

_SECONDS_PER_MINUTE = 60


class SqlUsageProvider:
    def __init__(self, session: AsyncSession, attempt_started_at: datetime | None = None):
        self._session = session
        self._attempt_started_at = attempt_started_at or datetime.now(timezone.utc)

    async def usage_for_task(self, task_id: EntityId) -> BudgetUsage:
        failed = ModelInvocationStatus.failed.value
        result = await self._session.execute(
            select(
                func.count(ModelInvocation.id),
                func.coalesce(func.sum(ModelInvocation.estimated_cost), 0),
                func.count(ModelInvocation.id).filter(ModelInvocation.status == failed),
            ).where(ModelInvocation.task_id == task_id)
        )
        calls, cost, failed_count = result.one()
        elapsed = datetime.now(timezone.utc) - self._attempt_started_at
        return BudgetUsage(
            calls_made=int(calls),
            cost_spent_usd=float(cost),
            elapsed_minutes=elapsed.total_seconds() / _SECONDS_PER_MINUTE,
            retries_made=int(failed_count),
        )
