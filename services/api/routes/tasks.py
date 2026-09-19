from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from artifact_service.service import commit_artifact
from artifact_service.storage.object_store import ObjectStore
from common.db.models import Agent, AgentVersion, Mission, Task, User
from contracts.enums import ActorType, ArtifactType, EventType, MissionStatus, TaskStatus, UserRole
from contracts.events import Actor, build_event
from contracts.ids import EntityId
from contracts.output_contract import validate_mission_output

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client
from api.schemas.tasks import TaskCompleteExternalRequest, TaskFailExternalRequest, TaskResponse

from mission_engine.engine.queue import enqueue_task
from mission_engine.states.transitions import (
    InvalidTransition,
    validate_mission_transition,
    validate_task_transition,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])

MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.operator)


async def _publish(publisher, session, event_type, tenant_id, actor, mission_id, task_id=None, agent_id=None, data=None):
    event = build_event(
        event_type=event_type, tenant_id=tenant_id, correlation_id=mission_id, actor=actor, service="api",
        mission_id=mission_id, task_id=task_id, agent_id=agent_id, data=data or {},
    )
    await publisher.publish(event, session)


@router.get("/missions/{mission_id}/tasks", response_model=list[TaskResponse])
async def list_tasks_for_mission(
    mission_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[Task]:
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")
    result = await session.execute(select(Task).where(Task.mission_id == mission_id))
    return list(result.scalars().all())


async def _get_task_tenant_scoped(session: AsyncSession, task_id: EntityId, tenant_id) -> Task | None:
    result = await session.execute(
        select(Task).join(Mission, Task.mission_id == Mission.id).where(Task.id == task_id, Mission.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> Task:
    task = await _get_task_tenant_scoped(session, task_id, user.tenant_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


@router.post("/tasks/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: EntityId,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    redis_client: Redis = Depends(get_redis_client),
) -> Task:
    task = await _get_task_tenant_scoped(session, task_id, user.tenant_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    # T1-F7 (digital-twin program): a task assigned to a non-`custom_durable` agent
    # (e.g. a Claude Code twin, `external_manual`) has no internal worker to ever pick
    # it up off the queue -- re-queueing it here would just leave it stuck `queued`
    # forever. Mirrors `_load_external_task`'s same check for complete-external/
    # fail-external.
    agent = await session.get(Agent, task.assigned_agent_id)
    agent_version = (
        await session.get(AgentVersion, agent.active_version_id)
        if agent is not None and agent.active_version_id is not None
        else None
    )
    if agent_version is None or agent_version.runtime_adapter != "custom_durable":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This task is executed externally and cannot be retried by the platform worker.",
        )

    try:
        validate_task_transition(TaskStatus(task.status), TaskStatus.queued)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    task.status = TaskStatus.queued.value
    await session.flush()
    await enqueue_task(redis_client, task.id)
    return task


async def _load_external_task(session: AsyncSession, task_id: EntityId, tenant_id: EntityId):
    """Loads the task + its mission + its assigned agent's active version, 404ing if
    not found (or not tenant-scoped), and 409ing if the assigned agent is executed
    internally (runtime_adapter == "custom_durable") -- complete-external/
    fail-external must never be usable to short-circuit a task the worker owns.
    """
    task = await _get_task_tenant_scoped(session, task_id, tenant_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    mission = await session.get(Mission, task.mission_id)
    agent = await session.get(Agent, task.assigned_agent_id)
    agent_version = (
        await session.get(AgentVersion, agent.active_version_id)
        if agent is not None and agent.active_version_id is not None
        else None
    )
    if agent_version is None or agent_version.runtime_adapter == "custom_durable":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This task is executed internally by the worker, not via complete-external/fail-external.",
        )
    return task, mission, agent, agent_version


@router.post("/tasks/{task_id}/complete-external", response_model=TaskResponse)
async def complete_task_external(
    task_id: EntityId,
    payload: TaskCompleteExternalRequest,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
    object_store: ObjectStore = Depends(get_object_store),
) -> Task:
    task, mission, agent, agent_version = await _load_external_task(session, task_id, user.tenant_id)
    actor = Actor(type=ActorType.agent, id=agent.id)
    correlation_id = mission.id

    try:
        validate_task_transition(TaskStatus(task.status), TaskStatus.running)
        validate_mission_transition(MissionStatus(mission.status), MissionStatus.completed)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    parsed, error = validate_mission_output(payload.output_text)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Output failed validation: {error}"
        )

    # queued -> running -> completed in one call: the real work already happened
    # outside Daythree before this endpoint was ever called, so there's no separate
    # moment to mark `running` at -- started_at and completed_at end up very close
    # together, unlike the internally-executed path's actual elapsed time.
    task.status = TaskStatus.running.value
    task.started_at = func.now()
    await _publish(publisher, session, EventType.task_started, user.tenant_id, actor, correlation_id,
                    task_id=task.id, agent_id=agent.id)
    await session.flush()

    commit_result = await commit_artifact(
        session, object_store, tenant_id=mission.tenant_id, mission_id=mission.id, task_id=task.id,
        agent_id=agent.id, agent_version_id=agent_version.id, artifact_type=ArtifactType.mission_output,
        title=parsed.title, content=payload.output_text.encode("utf-8"), mime_type="application/json",
    )
    if commit_result.newly_created:
        await _publish(publisher, session, EventType.artifact_created, user.tenant_id, actor, correlation_id,
                        task_id=task.id, agent_id=agent.id, data={"artifact_id": str(commit_result.artifact.id)})

    task.output_artifact_id = commit_result.artifact.id
    task.status = TaskStatus.completed.value
    task.completed_at = func.now()
    await _publish(publisher, session, EventType.task_completed, user.tenant_id, actor, correlation_id,
                    task_id=task.id, agent_id=agent.id)

    mission.status = MissionStatus.completed.value
    mission.completed_at = func.now()
    await _publish(publisher, session, EventType.mission_completed, user.tenant_id, actor, correlation_id,
                    agent_id=agent.id)

    await session.flush()
    await session.refresh(task)
    return task


@router.post("/tasks/{task_id}/fail-external", response_model=TaskResponse)
async def fail_task_external(
    task_id: EntityId,
    payload: TaskFailExternalRequest,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> Task:
    task, mission, agent, _agent_version = await _load_external_task(session, task_id, user.tenant_id)
    actor = Actor(type=ActorType.agent, id=agent.id)
    correlation_id = mission.id

    try:
        if task.status == TaskStatus.queued.value:
            validate_task_transition(TaskStatus.queued, TaskStatus.running)
            task.status = TaskStatus.running.value
            task.started_at = func.now()
            await _publish(publisher, session, EventType.task_started, user.tenant_id, actor, correlation_id,
                            task_id=task.id, agent_id=agent.id)
            await session.flush()
        validate_task_transition(TaskStatus(task.status), TaskStatus.failed)
        validate_mission_transition(MissionStatus(mission.status), MissionStatus.failed)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    task.status = TaskStatus.failed.value
    task.completed_at = func.now()
    await _publish(publisher, session, EventType.task_failed, user.tenant_id, actor, correlation_id,
                    task_id=task.id, agent_id=agent.id, data={"reason": payload.reason})

    mission.status = MissionStatus.failed.value
    mission.completed_at = func.now()
    await _publish(publisher, session, EventType.mission_failed, user.tenant_id, actor, correlation_id,
                    agent_id=agent.id, data={"reason": payload.reason})

    await session.flush()
    await session.refresh(task)
    return task
