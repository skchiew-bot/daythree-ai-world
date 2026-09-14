from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Mission, Task, User
from contracts.enums import TaskStatus, UserRole
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.dependencies.redis_client import get_redis_client
from api.schemas.tasks import TaskResponse

from mission_engine.engine.queue import enqueue_task
from mission_engine.states.transitions import InvalidTransition, validate_task_transition

router = APIRouter(prefix="/api/v1", tags=["tasks"])

MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.operator)


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

    try:
        validate_task_transition(TaskStatus(task.status), TaskStatus.queued)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    task.status = TaskStatus.queued.value
    await session.flush()
    await enqueue_task(redis_client, task.id)
    return task
