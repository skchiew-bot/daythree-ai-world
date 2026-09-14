"""Not in spec §16 either, but spec §17 Page 3 (Create Agent) has a "model policy"
dropdown field that has to be populated from somewhere.

Create-only, never edited in place (guardian-gatekeeper, 2026-09-15, "PATCH
/model-policies" gate review — BLOCK + Alternative A): a plain field-level PATCH would
have let an edit silently change the effective behaviour of every already-"immutable"
AgentVersion that references the row, with no way to detect it happened (this table has
no `updated_at`). Changing which provider/model an agent uses instead goes through the
same pattern agents.py already has for exactly this reason: create a new policy, create
a new AgentVersion pointing at it, activate that version. Rollback is just reactivating
the old version — no DB surgery.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import Settings, get_settings
from common.db.models import ModelPolicy, User
from contracts.enums import EventType, UserRole
from contracts.events import Actor, ActorType, build_event
from contracts.ids import EntityId, new_id
from model_gateway.provider_registry import available_provider_names

from api.dependencies.auth import get_current_user, require_role
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.redis_client import get_redis_client
from api.schemas.model_policies import ModelPolicyCreateRequest, ModelPolicyResponse

router = APIRouter(prefix="/api/v1/model-policies", tags=["model-policies"])

# Deliberately narrower than agents.py's MUTATORS (excludes operator): a policy governs
# which provider/model — and therefore how much real spend — every agent referencing it
# generates. guardian-gatekeeper gate review, condition A2. Kept as its own constant
# (not imported from routes.agents) for the same reason external_agents.py's MUTATORS is:
# a future change to that module's role set must not silently change who can do this.
MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin)

# Same fixed-window pattern as external_agents.py's rate limiter (including the NX
# self-healing fix from that route's security review) — duplicated rather than shared,
# matching this file's own precedent above of not cross-importing role/rate-limit
# constants between route modules. Low ceiling: policy creation is a rare admin action,
# not a hot path (guardian-gatekeeper gate review, condition A7).
_RATE_LIMIT_MAX_REQUESTS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60


async def _enforce_rate_limit(redis: Redis, tenant_id: EntityId) -> None:
    key = f"ratelimit:model-policies:create:{tenant_id}"
    count = await redis.incr(key)
    await redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS, nx=True)
    if count > _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many model-policy creations; slow down and retry shortly.",
        )


@router.get("", response_model=list[ModelPolicyResponse])
async def list_model_policies(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[ModelPolicy]:
    result = await session.execute(select(ModelPolicy).where(ModelPolicy.tenant_id == user.tenant_id))
    return list(result.scalars().all())


@router.post("", response_model=ModelPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_model_policy(
    payload: ModelPolicyCreateRequest,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
    settings: Settings = Depends(get_settings),
    publisher=Depends(get_event_publisher),
) -> ModelPolicy:
    await _enforce_rate_limit(redis, user.tenant_id)

    if payload.primary_provider not in available_provider_names(settings):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{payload.primary_provider}' is not a registered model provider in this deployment.",
        )

    # No UniqueConstraint on (tenant_id, name) today (flagged separately for its own
    # sign-off — an ALTER on a live table, per guardian-gatekeeper condition A5) — this
    # check-then-insert has a race window under concurrent requests from the same
    # tenant, acceptable here since policy creation is a rare, rate-limited admin action.
    existing = (
        await session.execute(
            select(ModelPolicy).where(ModelPolicy.tenant_id == user.tenant_id, ModelPolicy.name == payload.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A model policy named '{payload.name}' already exists for this tenant.",
        )

    policy = ModelPolicy(
        id=new_id(), tenant_id=user.tenant_id, name=payload.name,
        primary_provider=payload.primary_provider, primary_model=payload.primary_model,
    )
    session.add(policy)
    await session.flush()

    event = build_event(
        event_type=EventType.model_policy_created, tenant_id=user.tenant_id, correlation_id=policy.id,
        actor=Actor(type=ActorType.user, id=user.id), service="api",
        data={"name": policy.name, "primary_provider": policy.primary_provider, "primary_model": policy.primary_model},
    )
    await publisher.publish(event, session)

    await session.refresh(policy)  # populate server-default created_at, see agents.py's identical pattern
    return policy
