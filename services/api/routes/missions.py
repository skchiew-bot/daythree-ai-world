from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, AgentVersion, Mission, User
from contracts.enums import EventType, MissionStatus, UserRole
from contracts.events import Actor, ActorType, build_event
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.redis_client import get_redis_client
from api.schemas.missions import MissionCreateRequest, MissionResponse

from mission_engine.engine.mission_service import create_mission as _create_mission
from mission_engine.engine.mission_service import mark_mission_status, start_mission
from mission_engine.engine.queue import enqueue_task
from mission_engine.states.transitions import InvalidTransition

router = APIRouter(prefix="/api/v1/missions", tags=["missions"])

MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.operator)


async def _publish(publisher, session, event_type, tenant_id, actor, mission_id, task_id=None, agent_id=None, data=None):
    event = build_event(
        event_type=event_type, tenant_id=tenant_id, correlation_id=mission_id, actor=actor, service="api",
        mission_id=mission_id, task_id=task_id, agent_id=agent_id, data=data or {},
    )
    await publisher.publish(event, session)


@router.post("", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
async def create_mission_route(
    payload: MissionCreateRequest,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> Mission:
    import uuid as _uuid

    mission = await _create_mission(
        session, tenant_id=user.tenant_id, mission_code=f"MSN-{_uuid.uuid4().hex[:10].upper()}",
        title=payload.title, objective=payload.objective, requested_by=user.id,
        assigned_agent_id=payload.assigned_agent_id, priority=payload.priority,
        risk_level=payload.risk_level, budget_policy=payload.budget_policy,
    )
    await _publish(
        publisher, session, EventType.mission_created, user.tenant_id, Actor(type=ActorType.user, id=user.id),
        mission.id, agent_id=mission.assigned_agent_id,
    )
    return mission


@router.get("", response_model=list[MissionResponse])
async def list_missions(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[Mission]:
    result = await session.execute(select(Mission).where(Mission.tenant_id == user.tenant_id))
    return list(result.scalars().all())


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> Mission:
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")
    return mission


@router.post("/{mission_id}/start", response_model=MissionResponse)
async def start_mission_route(
    mission_id: EntityId,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
    redis_client: Redis = Depends(get_redis_client),
) -> Mission:
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")

    try:
        result = await start_mission(session, mission_id=mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    actor = Actor(type=ActorType.user, id=user.id)
    if result.newly_started:
        # TC-P0-010: a second /start call for the same mission takes the branch above
        # (`newly_started=False`) and emits nothing further — exactly one run.
        await _publish(publisher, session, EventType.mission_started, user.tenant_id, actor, mission_id,
                        agent_id=result.mission.assigned_agent_id)
        await _publish(publisher, session, EventType.task_created, user.tenant_id, actor, mission_id,
                        task_id=result.task.id, agent_id=result.task.assigned_agent_id)
        await _publish(publisher, session, EventType.task_assigned, user.tenant_id, actor, mission_id,
                        task_id=result.task.id, agent_id=result.task.assigned_agent_id)

        # Commit BEFORE enqueueing, not after: `get_db_session`'s automatic commit only
        # runs once this route returns, which would be after `enqueue_task` below — a
        # worker could then BRPOP this task_id and query for it while the INSERT is
        # still only visible inside this uncommitted transaction, raising
        # `TaskExecutionError: Task ... does not exist` (found by CI's E2E job; see
        # `mission_service.start_mission`'s docstring for the full explanation).
        await session.commit()

        # An externally-executed agent (runtime_adapter != "custom_durable" — see
        # routes/tasks.py's complete-external/fail-external) has no internal worker
        # to hand this off to; enqueueing it would just sit in Redis forever since
        # nothing ever BRPOPs it for that adapter type. Leave the task `queued` for
        # the external agent to report back on directly.
        agent = await session.get(Agent, result.task.assigned_agent_id)
        agent_version = (
            await session.get(AgentVersion, agent.active_version_id)
            if agent is not None and agent.active_version_id is not None
            else None
        )
        if agent_version is not None and agent_version.runtime_adapter == "custom_durable":
            await enqueue_task(redis_client, result.task.id)
    return result.mission


@router.post("/{mission_id}/cancel", response_model=MissionResponse)
async def cancel_mission(
    mission_id: EntityId,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> Mission:
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")

    try:
        await mark_mission_status(session, mission, MissionStatus.cancelled)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await _publish(
        publisher, session, EventType.mission_cancelled, user.tenant_id, Actor(type=ActorType.user, id=user.id),
        mission_id,
    )
    return mission
