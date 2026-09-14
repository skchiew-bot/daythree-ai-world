"""The real `CheckpointStore` (agent_runtime.checkpoint_store.CheckpointStore protocol),
backed by the `runtime_checkpoints` table — this is the concrete mechanism behind
"runtime can restart without losing the mission" (success criterion 10).

`save()` COMMITS, not just flushes. `task_executor.execute_task` runs entirely on one
request-scoped session that the worker only commits once, at the very end — if
`save()` only flushed, a checkpoint written "before the model call" would still be
sitting in an open, uncommitted transaction, and a real process crash during the model
call would roll it back along with everything else, silently defeating the whole point
of checkpointing before a potentially slow, crashable operation. Committing here turns
each checkpoint into a real durability boundary: everything the session has staged so
far (the checkpoint row, plus whatever task-status/event writes preceded it in the same
call) becomes durable immediately, and SQLAlchemy's session auto-begins a fresh
transaction for whatever runs next.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import RuntimeCheckpoint
from contracts.ids import EntityId, new_id
from contracts.runtime import Checkpoint


class SqlCheckpointStore:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, checkpoint: Checkpoint) -> Checkpoint:
        row = RuntimeCheckpoint(
            id=new_id(),
            mission_id=checkpoint.mission_id,
            task_id=checkpoint.task_id,
            agent_id=checkpoint.agent_id,
            checkpoint_sequence=checkpoint.sequence,
            state=checkpoint.state,
            status=checkpoint.status.value,
        )
        self._session.add(row)
        await self._session.commit()
        return checkpoint.model_copy(update={"checkpoint_id": row.id})

    async def latest_for_task(self, task_id: EntityId) -> Checkpoint | None:
        result = await self._session.execute(
            select(RuntimeCheckpoint)
            .where(RuntimeCheckpoint.task_id == task_id)
            .order_by(RuntimeCheckpoint.checkpoint_sequence.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return Checkpoint(
            checkpoint_id=row.id,
            run_id=row.id,  # run_id isn't persisted separately; the checkpoint id stands in for it on reload
            task_id=row.task_id,
            mission_id=row.mission_id,
            agent_id=row.agent_id,
            sequence=row.checkpoint_sequence,
            status=row.status,
            state=row.state,
        )
