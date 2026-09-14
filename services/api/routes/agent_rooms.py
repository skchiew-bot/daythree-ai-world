"""GET /api/v1/agent-rooms (ADR-009): the 3D World's read model for the apartment.
Readable by any authenticated role — no mutation of agents/missions/tasks happens
here. It *does* write via the lazy-backfill path (`ensure_assignment` for an agent
that has no room yet, e.g. one seeded by `infrastructure/scripts/seed.py` before this
feature existed), but that write is idempotent and DB-guarded by the partial unique
index, so a GET performing it is safe.

Room "activity" is derived from each agent's most recently created Task, scoped to
the tenant by joining through Mission (`Task` itself carries no `tenant_id`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, Mission, Task, User
from common.rooms import DEFAULT_FLOOR_COUNT, ROOMS_PER_FLOOR
from contracts.enums import AgentLifecycleState, TaskStatus

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session
from api.schemas.agent_rooms import AgentRoomOut, AgentRoomsResponse, RoomActivity
from api.services.room_assignment import ensure_assignment, list_assignments

router = APIRouter(prefix="/api/v1/agent-rooms", tags=["agent-rooms"])

# Matches World.tsx's RESULT_HOLD_MS (6000ms) — how long a room keeps showing
# completed/failed before reverting to idle.
_RESULT_HOLD_SECONDS = 6

_TERMINAL_STATUSES = {TaskStatus.completed.value, TaskStatus.failed.value, TaskStatus.cancelled.value}


def _activity_for_task(task: Task | None, now: datetime) -> tuple[RoomActivity, datetime | None]:
    if task is None:
        return "idle", None
    if task.status == TaskStatus.queued.value:
        return "assigned", task.created_at
    if task.status in (TaskStatus.running.value, TaskStatus.waiting.value):
        return "working", task.started_at or task.created_at
    if task.status in _TERMINAL_STATUSES:
        changed_at = task.completed_at or task.created_at
        age_seconds = (now - changed_at).total_seconds()
        if age_seconds >= _RESULT_HOLD_SECONDS:
            return "idle", changed_at
        return ("completed" if task.status == TaskStatus.completed.value else "failed"), changed_at
    return "idle", None


async def _latest_task_by_agent(session: AsyncSession, tenant_id) -> dict:
    latest = (
        select(Task.assigned_agent_id.label("agent_id"), func.max(Task.created_at).label("max_created_at"))
        .join(Mission, Mission.id == Task.mission_id)
        .where(Mission.tenant_id == tenant_id)
        .group_by(Task.assigned_agent_id)
        .subquery()
    )
    result = await session.execute(
        select(Task).join(
            latest,
            (Task.assigned_agent_id == latest.c.agent_id) & (Task.created_at == latest.c.max_created_at),
        )
    )
    return {task.assigned_agent_id: task for task in result.scalars().all()}


@router.get("", response_model=AgentRoomsResponse)
async def list_agent_rooms(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> AgentRoomsResponse:
    agents = list(
        (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == user.tenant_id,
                    Agent.lifecycle_state != AgentLifecycleState.suspended.value,
                )
            )
        )
        .scalars()
        .all()
    )

    assignments = {a.agent_id: a for a in await list_assignments(session, user.tenant_id)}
    for agent in agents:
        if agent.id in assignments:
            continue
        backfilled = await ensure_assignment(session, user.tenant_id, agent.id)
        if backfilled is not None:
            assignments[agent.id] = backfilled
    await session.flush()

    latest_task_by_agent = await _latest_task_by_agent(session, user.tenant_id)
    now = datetime.now(timezone.utc)

    rooms: list[AgentRoomOut] = []
    for agent in agents:
        assignment = assignments.get(agent.id)
        if assignment is None:
            continue
        task = latest_task_by_agent.get(agent.id)
        activity, activity_changed_at = _activity_for_task(task, now)
        rooms.append(
            AgentRoomOut(
                agent_id=agent.id,
                agent_code=agent.agent_code,
                display_name=agent.display_name,
                lifecycle_state=agent.lifecycle_state,
                floor=assignment.floor,
                room_index=assignment.room_index,
                assigned_at=assignment.assigned_at,
                activity=activity,
                active_task_id=task.id if task else None,
                activity_changed_at=activity_changed_at,
            )
        )

    return AgentRoomsResponse(
        rooms_per_floor=ROOMS_PER_FLOOR, default_floor_count=DEFAULT_FLOOR_COUNT, rooms=rooms
    )
