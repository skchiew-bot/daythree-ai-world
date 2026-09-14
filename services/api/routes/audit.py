from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AuditEvent, Mission, User
from contracts.enums import UserRole
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.schemas.audit import AuditEventResponse

router = APIRouter(prefix="/api/v1", tags=["audit"])

AUDIT_READERS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.auditor)


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
