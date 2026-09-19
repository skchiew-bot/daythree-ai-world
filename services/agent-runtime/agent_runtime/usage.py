"""The port through which the adapter learns what a task has already consumed (R0, ADR-013).

Like `CheckpointStore`, it is a protocol so the adapter has no DB dependency. The real,
DB-backed implementation lives in `services/mission-engine` (it reads committed
`model_invocations`); tests inject a fake.
"""
from __future__ import annotations

from typing import Protocol

from contracts.ids import EntityId
from policy_sdk.budgets import BudgetUsage


class UsageProvider(Protocol):
    async def usage_for_task(self, task_id: EntityId) -> BudgetUsage: ...
