"""Not in spec §16 either, but spec §17 Page 5 (Mission Detail) has a "Model Usage"
tab that needs per-mission token/cost/latency data — `model_invocations` already has
everything needed (spec §8.11); this just exposes it scoped to one mission.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Mission, ModelInvocation, User
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404
from api.dependencies.db import get_db_session

router = APIRouter(prefix="/api/v1", tags=["model-invocations"])


class ModelInvocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    task_id: EntityId
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal
    latency_ms: int
    status: str
    created_at: datetime


@router.get("/missions/{mission_id}/model-invocations", response_model=list[ModelInvocationResponse])
async def list_mission_model_invocations(
    mission_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[ModelInvocation]:
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")
    result = await session.execute(
        select(ModelInvocation).where(ModelInvocation.mission_id == mission_id).order_by(ModelInvocation.created_at)
    )
    return list(result.scalars().all())
