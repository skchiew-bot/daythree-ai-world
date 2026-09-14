"""Not in spec §16 either, but spec §17 Page 3 (Create Agent) has a "model policy"
dropdown field that has to be populated from somewhere.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import ModelPolicy, User
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session

router = APIRouter(prefix="/api/v1/model-policies", tags=["model-policies"])


class ModelPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    name: str
    primary_provider: str
    primary_model: str


@router.get("", response_model=list[ModelPolicyResponse])
async def list_model_policies(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[ModelPolicy]:
    result = await session.execute(select(ModelPolicy).where(ModelPolicy.tenant_id == user.tenant_id))
    return list(result.scalars().all())
