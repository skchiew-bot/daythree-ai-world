"""Not in spec §16 — see `ExternalAgentStatus` in `common.db.models` for why this
exists and what it deliberately does *not* do (no budget/permission/audit).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import ExternalAgentStatus, User

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session
from api.schemas.external_agents import ExternalAgentStatusOut, ExternalAgentStatusUpdate

router = APIRouter(prefix="/api/v1/external-agents", tags=["external-agents"])

_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"


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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ExternalAgentStatusOut:
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
