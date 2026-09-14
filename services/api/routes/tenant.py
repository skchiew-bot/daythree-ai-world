from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Tenant, User
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session

router = APIRouter(prefix="/api/v1/tenant", tags=["tenant"])


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    code: str
    name: str
    status: str


@router.get("", response_model=TenantResponse)
async def get_current_tenant(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> Tenant:
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return tenant
