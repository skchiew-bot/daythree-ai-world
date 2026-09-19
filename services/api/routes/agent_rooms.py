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
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, Mission, MissionProject, Project, Task, User
from common.rooms import DEFAULT_FLOOR_COUNT, ROOMS_PER_FLOOR
from contracts.enums import AgentLifecycleState, ProjectStatus, TaskStatus
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session
from api.schemas.agent_rooms import AgentRoomOut, AgentRoomsResponse, ProjectSummary, RoomActivity
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
    """One deterministic row per agent (ADR-014 decision 3, gate finding F5): two
    tasks with an identical `created_at` (constant within a transaction, since
    `Task.created_at` is `server_default=func.now()`) no longer make this pick
    non-deterministic — `DISTINCT ON` breaks every tie with `id DESC`. The explicit
    `Mission.tenant_id == tenant_id` filter on this, the OUTER statement (not just a
    subquery) is gate finding F3: the prior version tenant-filtered only a subquery
    feeding into an otherwise-unfiltered `select(Task)`.
    """
    stmt = (
        select(Task)
        .join(Mission, Mission.id == Task.mission_id)
        .where(Mission.tenant_id == tenant_id)
        .distinct(Task.assigned_agent_id)
        .order_by(Task.assigned_agent_id, Task.created_at.desc(), Task.id.desc())
    )
    result = await session.execute(stmt)
    return {task.assigned_agent_id: task for task in result.scalars().all()}


async def _project_id_by_mission(session: AsyncSession, tenant_id, mission_ids: list) -> dict:
    """The mission -> project links for a set of missions, filtered through an
    explicit `Project.tenant_id == tenant_id` join predicate (gate finding F3
    applied to the new join, not just the pre-existing Task/Mission one)."""
    if not mission_ids:
        return {}
    result = await session.execute(
        select(MissionProject.mission_id, MissionProject.project_id)
        .join(Project, Project.id == MissionProject.project_id)
        .where(
            MissionProject.tenant_id == tenant_id,
            MissionProject.mission_id.in_(mission_ids),
            Project.tenant_id == tenant_id,
        )
    )
    return {mission_id: project_id for mission_id, project_id in result.all()}


async def _projects_summary(session: AsyncSession, tenant_id, referenced_ids: set) -> list[ProjectSummary]:
    """Every active project plus every project referenced by an emitted
    `project_id`, even archived (gate finding F6) — loaded in exactly one query
    over the id set (gate finding F10).

    Ordered by `(created_at, id)` because the town places buildings by probing in this
    order (gate finding F7): without an explicit ORDER BY the order is Postgres's
    physical row order, which changes when any project row is updated, and every later
    building could shift lots.
    """
    result = await session.execute(
        select(Project)
        .where(
            Project.tenant_id == tenant_id,
            or_(Project.status == ProjectStatus.active.value, Project.id.in_(referenced_ids)),
        )
        .order_by(Project.created_at, Project.id)
    )
    return [
        ProjectSummary(id=p.id, code=p.code, name=p.name, status=p.status)
        for p in result.scalars().all()
    ]


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
    project_id_by_mission = await _project_id_by_mission(
        session, user.tenant_id, [t.mission_id for t in latest_task_by_agent.values()]
    )
    now = datetime.now(timezone.utc)

    rooms: list[AgentRoomOut] = []
    referenced_project_ids: set[EntityId] = set()
    for agent in agents:
        assignment = assignments.get(agent.id)
        if assignment is None:
            continue
        task = latest_task_by_agent.get(agent.id)
        activity, activity_changed_at = _activity_for_task(task, now)
        # Non-null only while the twin is placed at a project (assigned/working, or
        # completed/failed inside the hold window) — idle means it's home (F6).
        project_id = project_id_by_mission.get(task.mission_id) if task is not None and activity != "idle" else None
        if project_id is not None:
            referenced_project_ids.add(project_id)
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
                project_id=project_id,
            )
        )

    projects = await _projects_summary(session, user.tenant_id, referenced_project_ids)

    return AgentRoomsResponse(
        rooms_per_floor=ROOMS_PER_FLOOR, default_floor_count=DEFAULT_FLOOR_COUNT, rooms=rooms, projects=projects
    )
