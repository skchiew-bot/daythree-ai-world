"""The port through which the adapter learns what a task has already consumed, and through
which every provider attempt is written ahead (R0, ADR-013).

Like `CheckpointStore`, it is a protocol so the adapter has no DB dependency. The real,
DB-backed implementation lives in `services/mission-engine` (it reads and writes
`model_invocations`); tests inject a fake. The two attempt methods match the model
gateway's `AttemptLedger` protocol, and the adapter passes this object to the gateway as
its ledger.
"""
from __future__ import annotations

from typing import Any, Protocol

from contracts.ids import EntityId
from model_gateway.telemetry import ModelInvocationTelemetry
from policy_sdk.budgets import BudgetUsage


class UsageProvider(Protocol):
    async def usage_for_task(self, task_id: EntityId) -> BudgetUsage: ...

    async def begin_attempt(self, worst_case: ModelInvocationTelemetry) -> Any: ...

    async def finish_attempt(self, attempt_id: Any, outcome: ModelInvocationTelemetry) -> None: ...
