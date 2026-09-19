"""ADR-014 decision 2: projects are a first-class entity a mission can link to.

Create and archive are gated the same way `model_policies.py` gates policy creation
(a narrower role set than `agents.py`'s MUTATORS, plus a fixed-window rate limit) —
duplicated rather than shared, matching that file's own precedent of not cross-
importing role/rate-limit constants between route modules. `GET` is open to any
authenticated user in the tenant, same as `list_missions`.

`audit_events.payload` for both events carries only `project_id`, `status` and the
actor id (data-warden D17) — `code` and `name` are never placed in event `data`.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Project, User
from contracts.enums import EventType, ProjectStatus, UserRole
from contracts.events import Actor, ActorType, build_event
from contracts.ids import EntityId, new_id

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.redis_client import get_redis_client
from api.schemas.projects import ProjectCreateRequest, ProjectResponse

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

# ADR-014 decision 2: narrower than missions.py's MUTATORS would suggest (it isn't,
# actually — same three roles), kept as its own constant per model_policies.py's
# precedent so a future edit to another router's role set can't silently change this.
MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.operator)

# Same fixed-window pattern as model_policies.py's rate limiter.
_RATE_LIMIT_MAX_REQUESTS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60

# The town grid has 48 lots (ADR-014 operator decision O15) — a per-tenant cap on
# *active* projects so the grid never has to grow to fit an unbounded roster.
_MAX_ACTIVE_PROJECTS = 48


async def _lock_tenant_active_project_count(session: AsyncSession, tenant_id: EntityId) -> None:
    """Security review follow-up (PR #26, MEDIUM): the count-then-insert cap check
    below has a race window under concurrent creates from the same tenant — two
    requests can both read `active_count = 47` before either commits its insert,
    both pass the `< 48` check, and leave the tenant at 49, which breaks the
    invariant the W2 town grid (48 lots) depends on. A Postgres transaction-scoped
    advisory lock, keyed per tenant, serializes the count-check-insert sequence
    across concurrent requests without a schema change; it releases automatically
    at commit or rollback via `get_db_session`, so no explicit unlock is needed."""
    lock_key = int.from_bytes(hashlib.sha256(tenant_id.bytes).digest()[:8], "big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


async def _enforce_rate_limit(redis: Redis, tenant_id: EntityId) -> None:
    key = f"ratelimit:projects:create:{tenant_id}"
    count = await redis.incr(key)
    await redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS, nx=True)
    if count > _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many project creations; slow down and retry shortly.",
        )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[Project]:
    result = await session.execute(select(Project).where(Project.tenant_id == user.tenant_id))
    return list(result.scalars().all())


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
    publisher=Depends(get_event_publisher),
) -> Project:
    await _enforce_rate_limit(redis, user.tenant_id)
    await _lock_tenant_active_project_count(session, user.tenant_id)

    existing = (
        await session.execute(
            select(Project).where(Project.tenant_id == user.tenant_id, Project.code == payload.code)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A project with code '{payload.code}' already exists for this tenant.",
        )

    active_count = (
        await session.execute(
            select(func.count()).select_from(Project).where(
                Project.tenant_id == user.tenant_id, Project.status == ProjectStatus.active.value
            )
        )
    ).scalar_one()
    if active_count >= _MAX_ACTIVE_PROJECTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This tenant already has {_MAX_ACTIVE_PROJECTS} active projects, the maximum allowed.",
        )

    project = Project(
        id=new_id(), tenant_id=user.tenant_id, code=payload.code, name=payload.name,
        status=ProjectStatus.active.value, created_by=user.id,
    )
    session.add(project)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Race-window fallback for the check-then-insert above (same acceptance as
        # model_policies.py's duplicate-name check — a rare, rate-limited admin action).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A project with code '{payload.code}' already exists for this tenant.",
        ) from exc

    event = build_event(
        event_type=EventType.project_created, tenant_id=user.tenant_id, correlation_id=project.id,
        actor=Actor(type=ActorType.user, id=user.id), service="api",
        data={"project_id": str(project.id), "status": project.status},
    )
    await publisher.publish(event, session)

    await session.refresh(project)
    return project


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: EntityId,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
    publisher=Depends(get_event_publisher),
) -> Project:
    await _enforce_rate_limit(redis, user.tenant_id)

    project = await get_tenant_scoped_or_404(session, Project, project_id, user.tenant_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if project.status != ProjectStatus.archived.value:
        project.status = ProjectStatus.archived.value
        await session.flush()

        event = build_event(
            event_type=EventType.project_archived, tenant_id=user.tenant_id, correlation_id=project.id,
            actor=Actor(type=ActorType.user, id=user.id), service="api",
            data={"project_id": str(project.id), "status": project.status},
        )
        await publisher.publish(event, session)

    return project
