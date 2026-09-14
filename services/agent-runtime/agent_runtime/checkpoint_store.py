"""The persistence port the durable adapter uses to save/load checkpoints.

Kept out of the adapter itself so the adapter has no DB dependency and is trivial to
unit test. The real, DB-backed implementation (writing to `runtime_checkpoints`) lives
in `services/mission-engine` where the request-scoped session already exists; tests use
`InMemoryCheckpointStore`.
"""
from __future__ import annotations

from typing import Protocol

from contracts.ids import EntityId
from contracts.runtime import Checkpoint


class CheckpointStore(Protocol):
    async def save(self, checkpoint: Checkpoint) -> Checkpoint: ...
    async def latest_for_task(self, task_id: EntityId) -> Checkpoint | None: ...


class InMemoryCheckpointStore:
    """Used by unit tests and by `make demo` when nothing else needs the checkpoint
    history to survive process restart (a real run always uses the SQL-backed store)."""

    def __init__(self) -> None:
        self._by_task: dict[EntityId, list[Checkpoint]] = {}

    async def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self._by_task.setdefault(checkpoint.task_id, []).append(checkpoint)
        return checkpoint

    async def latest_for_task(self, task_id: EntityId) -> Checkpoint | None:
        history = self._by_task.get(task_id)
        return history[-1] if history else None
