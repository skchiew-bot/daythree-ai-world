"""Not in spec §16 — see `ExternalAgentStatus` in `common.db.models` for why this
exists and what it deliberately does *not* do (no budget/audit). The write route is
role-gated and rate-limited (ADR-010 gate review, C1): the original design let any
authenticated caller of any role push unlimited status rows, which is a capacity-DoS
path against a table with no delete route (docs/adr/ADR-009-agent-room-assignment.md
originally flagged this; docs/adr/ADR-010-claude-code-subagent-digital-twins.md's gate
review required it be fixed before that ADR's own feature builds on similar ground).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import ExternalAgentStatus, User
from contracts.enums import UserRole
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, require_role
from api.dependencies.db import get_db_session
from api.dependencies.redis_client import get_redis_client
from api.schemas.external_agents import ExternalAgentStatusOut, ExternalAgentStatusUpdate

router = APIRouter(prefix="/api/v1/external-agents", tags=["external-agents"])

_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"

# Same allowed-role set as agents.py's MUTATORS — kept as a separate constant (not
# imported from routes.agents) so a future change to that module's mutator roles
# doesn't silently change who can push external-agent status.
MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.operator)

# Fixed-window counter, not a token bucket: one INCR+EXPIRE pair per request is enough
# to bound the capacity-DoS path (unlimited row creation) without adding new
# infrastructure beyond the Redis client every other route already depends on.
_RATE_LIMIT_MAX_REQUESTS = 60
_RATE_LIMIT_WINDOW_SECONDS = 60


async def _enforce_rate_limit(redis: Redis, tenant_id: EntityId) -> None:
    key = f"ratelimit:external-agents:status:{tenant_id}"
    count = await redis.incr(key)
    # NX + unconditional (not gated on count == 1): INCR and EXPIRE aren't atomic, so a
    # request that dies between them would otherwise leave the key with no TTL, wedging
    # the tenant's counter above the threshold forever. Calling this every request is
    # self-healing and NX makes it a no-op once the TTL is already set.
    await redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS, nx=True)
    if count > _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many external-agent status updates; slow down and retry shortly.",
        )


@router.get("", response_model=list[ExternalAgentStatusOut])
async def list_external_agent_statuses(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[ExternalAgentStatusOut]:
    result = await session.execute(
        select(ExternalAgentStatus).where(ExternalAgentStatus.tenant_id == user.tenant_id)
    )
    return [ExternalAgentStatusOut.model_validate(row, from_attributes=True) for row in result.scalars().all()]


@router.put("/{name}/status", response_model=ExternalAgentStatusOut)
async def set_external_agent_status(
    payload: ExternalAgentStatusUpdate,
    name: str = Path(pattern=_NAME_PATTERN),
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
) -> ExternalAgentStatusOut:
    await _enforce_rate_limit(redis, user.tenant_id)

    existing = (
        await session.execute(
            select(ExternalAgentStatus).where(
                ExternalAgentStatus.tenant_id == user.tenant_id, ExternalAgentStatus.name == name
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = ExternalAgentStatus(tenant_id=user.tenant_id, name=name)
        session.add(existing)

    existing.status = payload.status
    existing.job_description = payload.job_description
    existing.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(existing)
    return ExternalAgentStatusOut.model_validate(existing, from_attributes=True)
