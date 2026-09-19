from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AuditEvent, Mission, User
from contracts.enums import UserRole
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.schemas.agent_runtime import HookLossRateResponse
from api.schemas.audit import AuditEventResponse
from api.services.agent_runtime_closure import compute_hook_loss_rate

router = APIRouter(prefix="/api/v1", tags=["audit"])

AUDIT_READERS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.auditor)

# T2 deliverable 10 default lookback: Gate E's own window is a config detail of the
# gate, not this endpoint -- an explicit `since`/`until` overrides it per call.
_DEFAULT_HOOK_LOSS_WINDOW = timedelta(days=7)


@router.get("/missions/{mission_id}/timeline", response_model=list[AuditEventResponse])
async def mission_timeline(
    mission_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[AuditEvent]:
    """Spec §13 step 18 / TC-P0-013: reconstructs the full lifecycle chronologically —
    every row is already tenant-scoped via `mission_id` plus the mission-existence
    check below, so no separate tenant filter on `audit_events` is needed here."""
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")

    result = await session.execute(
        select(AuditEvent).where(AuditEvent.mission_id == mission_id).order_by(AuditEvent.occurred_at.asc())
    )
    return list(result.scalars().all())


@router.get("/audit/events", response_model=list[AuditEventResponse])
async def list_audit_events(
    user: User = Depends(AUDIT_READERS), session: AsyncSession = Depends(get_db_session), limit: int = 200
) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == user.tenant_id)
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/audit/agent-runtime-hook-loss-rate", response_model=HookLossRateResponse)
async def agent_runtime_hook_loss_rate(
    user: User = Depends(AUDIT_READERS),
    session: AsyncSession = Depends(get_db_session),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> HookLossRateResponse:
    """T2 deliverable 10 for Gate E: computed on read from `agent_runtime_closures`,
    never a stored counter. Behind the existing audit reader roles, same as every
    other endpoint in this file -- not on the agent-runtime router, so the scoped
    `dtk_...` credential can never reach it (it isn't even the right kind of
    principal: `AUDIT_READERS` requires a JWT-authenticated `User`)."""
    since = since or (datetime.now(timezone.utc) - _DEFAULT_HOOK_LOSS_WINDOW)
    result = await compute_hook_loss_rate(session, user.tenant_id, since=since, until=until)
    return HookLossRateResponse(
        since=result.since, until=result.until, lost=result.lost, total=result.total, rate=result.rate
    )
