"""Not in spec §16's route list, but spec §17 Page 1 (Dashboard) needs one place to
read its numbers from — added as a straightforward aggregation over tables the API
already exposes individually, rather than making the admin UI compute it client-side
from several paginated list calls.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, Mission, ModelInvocation, User
from contracts.enums import MissionStatus

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class DashboardSummary(BaseModel):
    total_agents: int
    active_missions: int
    failed_missions: int
    completed_missions: int
    model_calls: int
    current_cost_usd: float
    system_status: str


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> DashboardSummary:
    async def count_missions(status_value: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(Mission).where(
                Mission.tenant_id == user.tenant_id, Mission.status == status_value
            )
        )
        return result.scalar_one()

    total_agents = (
        await session.execute(select(func.count()).select_from(Agent).where(Agent.tenant_id == user.tenant_id))
    ).scalar_one()
    model_calls = (
        await session.execute(
            select(func.count()).select_from(ModelInvocation).where(ModelInvocation.tenant_id == user.tenant_id)
        )
    ).scalar_one()
    total_cost = (
        await session.execute(
            select(func.coalesce(func.sum(ModelInvocation.estimated_cost), 0)).where(
                ModelInvocation.tenant_id == user.tenant_id
            )
        )
    ).scalar_one()

    return DashboardSummary(
        total_agents=total_agents,
        active_missions=await count_missions(MissionStatus.running.value),
        failed_missions=await count_missions(MissionStatus.failed.value),
        completed_missions=await count_missions(MissionStatus.completed.value),
        model_calls=model_calls,
        current_cost_usd=float(Decimal(str(total_cost))),
        system_status="ok",
    )
