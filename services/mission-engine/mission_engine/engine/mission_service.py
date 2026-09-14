"""Mission creation and mission start — the idempotent-start half of spec §13's flow
(steps 1-6, 8; steps 9-18 are `task_executor.execute_task`, run by the worker).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from common.db.models import Mission, Task
from contracts.enums import MissionPriority, MissionStatus, RiskLevel, TaskStatus
from contracts.ids import EntityId, new_id
from contracts.policy import BudgetPolicy

from mission_engine.engine.queue import enqueue_task
from mission_engine.states.transitions import validate_mission_transition


@dataclass
class StartMissionResult:
    mission: Mission
    task: Task
    newly_started: bool


async def create_mission(
    session: AsyncSession,
    *,
    tenant_id: EntityId,
    mission_code: str,
    title: str,
    objective: str,
    requested_by: Optional[EntityId],
    assigned_agent_id: EntityId,
    priority: MissionPriority = MissionPriority.normal,
    risk_level: RiskLevel = RiskLevel.low,
    budget_policy: BudgetPolicy | None = None,
) -> Mission:
    mission = Mission(
        id=new_id(),
        tenant_id=tenant_id,
        mission_code=mission_code,
        title=title,
        objective=objective,
        requested_by=requested_by,
        assigned_agent_id=assigned_agent_id,
        status=MissionStatus.draft.value,
        priority=priority.value,
        risk_level=risk_level.value,
        budget_policy=(budget_policy or BudgetPolicy()).model_dump(),
    )
    session.add(mission)
    await session.flush()
    return mission


async def start_mission(session: AsyncSession, redis_client: Redis, *, mission_id: EntityId) -> StartMissionResult:
    """Idempotent (spec §14, TC-P0-010): a second `start` call for an already-running
    (or already-terminal) mission returns the existing task instead of creating a new
    one or re-enqueueing it — the atomic `UPDATE ... WHERE status IN (...)` below is
    what actually prevents the race, not an application-level check-then-act.
    """
    result = await session.execute(
        update(Mission)
        .where(Mission.id == mission_id, Mission.status.in_([MissionStatus.draft.value, MissionStatus.ready.value]))
        .values(status=MissionStatus.running.value, started_at=func.now())
        .returning(Mission.id)
    )
    won_the_race = result.scalar_one_or_none() is not None

    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} does not exist.")
    if won_the_race:
        # `session.get()` above returns the identity-mapped object if this session
        # already loaded this Mission earlier in the request (e.g. the API route's own
        # tenant-scoping lookup before calling this function) — a plain Core-style
        # `update()` like the one above never touches that cached Python object's
        # attributes directly. SQLAlchemy's ORM-enabled bulk-update sync then expires
        # (not populates) attributes it can't statically evaluate — `started_at=
        # func.now()` is exactly that case — leaving `mission.started_at` needing a
        # lazy reload. FastAPI's response-model serialization runs outside the async
        # greenlet context, so that lazy reload raises `MissingGreenlet` instead of a
        # value (found by CI's E2E run against a real Postgres). An explicit, awaited
        # refresh here — right where the row was actually changed — fixes it for every
        # caller of `start_mission`, not just the API route.
        await session.refresh(mission)

    if not won_the_race:
        existing_task = (
            await session.execute(select(Task).where(Task.mission_id == mission_id))
        ).scalars().first()
        if existing_task is None:
            # Mission was created but never actually started (e.g. draft->cancelled
            # happened concurrently) — nothing to run.
            raise ValueError(f"Mission {mission_id} is '{mission.status}' and has no task to resume.")
        return StartMissionResult(mission=mission, task=existing_task, newly_started=False)

    idempotency_key = f"{mission_id}:task:1"
    task = Task(
        id=new_id(),
        mission_id=mission_id,
        assigned_agent_id=mission.assigned_agent_id,
        title=mission.title,
        instructions=mission.objective,
        status=TaskStatus.queued.value,
        idempotency_key=idempotency_key,
        budget_policy=mission.budget_policy,
        input_context={},
    )
    session.add(task)

    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # We won the mission-status CAS above, so under the normal one-way mission
        # state machine this branch should be unreachable — it only fires if a task
        # for this mission already existed before this call (e.g. something outside
        # the normal transition table put the mission back into draft/ready after it
        # had already run once). Re-verify rather than assume: if no row matches this
        # exact idempotency key, the IntegrityError was something else entirely (a bad
        # FK, a NOT NULL violation) and must not be swallowed — same discipline as
        # `artifact_service.commit_artifact`'s equivalent fallback.
        existing_task = (
            await session.execute(select(Task).where(Task.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if existing_task is None:
            raise
        # A task already existed — we did not just create one, so don't claim we did
        # and don't blindly re-enqueue it (it may already be running or completed;
        # only a fresh task created by this call should be pushed onto the queue).
        return StartMissionResult(mission=mission, task=existing_task, newly_started=False)

    await enqueue_task(redis_client, task.id)
    return StartMissionResult(mission=mission, task=task, newly_started=True)


async def mark_mission_status(session: AsyncSession, mission: Mission, target: MissionStatus) -> None:
    validate_mission_transition(MissionStatus(mission.status), target)
    mission.status = target.value
    sets_completed_at = target in (MissionStatus.completed, MissionStatus.failed, MissionStatus.cancelled)
    if sets_completed_at:
        mission.completed_at = func.now()
    await session.flush()
    if sets_completed_at:
        # Same MissingGreenlet-on-serialization risk as `start_mission`'s CAS update,
        # here via a plain ORM attribute assignment instead of a Core `update()` —
        # assigning `func.now()` directly still leaves the attribute needing a
        # reload that a later sync-context serialization can't perform. Refresh right
        # after the flush that changed it, for every caller (currently just
        # `routes/missions.py::cancel_mission`).
        await session.refresh(mission)
