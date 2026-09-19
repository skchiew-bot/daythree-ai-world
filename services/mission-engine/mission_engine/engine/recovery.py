"""Orphan recovery bookkeeping (R0, ADR-013): what the sweep does with a `running` task that
no worker holds a lease on.

Every recovery is counted in `tasks.retry_count` inside the sweep's OWN transaction, which
the sweep commits before it re-enqueues. Counting it in the worker instead would be lost
whenever `process_task` rolls back (an object-store outage on resume, say), and a task
would then be requeued every sweep forever. At the cap the task is failed through the state
machine with a fixed reason and no free text, so it cannot sit `running` unnoticed.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from common.db.models import Mission, Task
from contracts.enums import ActorType, EventType, MissionStatus, TaskStatus
from contracts.events import Actor, build_event
from contracts.ids import EntityId
from event_service.publisher import EventPublisher

from mission_engine.states.transitions import (
    InvalidTransition,
    validate_mission_transition,
    validate_task_transition,
)

logger = structlog.get_logger(__name__)

MAX_REQUEUES_REASON = "max_requeues"


async def register_recovery(
    session: AsyncSession, publisher: EventPublisher | None, task_id: EntityId, *, max_requeues: int
) -> bool:
    """Counts one recovery of `task_id` (flushed, for the caller to commit) and returns True
    if it should be requeued. Returns False when the task is no longer `running`, or when it
    has hit `max_requeues` and was failed instead."""
    task = await session.get(Task, task_id)
    if task is None or task.status != TaskStatus.running.value:
        return False
    if task.retry_count >= max_requeues:
        await _fail_after_max_requeues(session, publisher, task)
        return False
    task.retry_count += 1
    await session.flush()
    return True


async def _fail_after_max_requeues(session: AsyncSession, publisher: EventPublisher | None, task: Task) -> None:
    if publisher is None:
        raise RuntimeError("An event publisher is required to fail a task that hit the requeue cap.")
    mission = await session.get(Mission, task.mission_id)
    logger.warning("task_failed_after_max_requeues", task_id=str(task.id), requeues=task.retry_count)
    try:
        validate_task_transition(TaskStatus.running, TaskStatus.failed)
        validate_mission_transition(MissionStatus(mission.status), MissionStatus.failed)
    except InvalidTransition:
        logger.exception("max_requeues_transition_refused", task_id=str(task.id))
        return

    actor = Actor(type=ActorType.system)
    task.status = TaskStatus.failed.value
    task.completed_at = func.now()
    mission.status = MissionStatus.failed.value
    mission.completed_at = func.now()
    for event_type in (EventType.task_failed, EventType.mission_failed):
        await publisher.publish(
            build_event(
                event_type=event_type, tenant_id=mission.tenant_id, correlation_id=mission.id, actor=actor,
                service="worker", mission_id=mission.id, task_id=task.id, agent_id=task.assigned_agent_id,
                data={"reason": MAX_REQUEUES_REASON},
            ),
            session,
        )
    await session.flush()
