from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from contracts.ids import EntityId


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    tenant_id: EntityId
    email: str
    display_name: str
    role: str
