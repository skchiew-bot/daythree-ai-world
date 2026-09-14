from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import AgentLifecycleState, AutonomyLevel
from contracts.ids import EntityId
from contracts.policy import ToolPolicy


class AgentVersionCreateRequest(BaseModel):
    system_prompt: str
    runtime_adapter: str = "custom_durable"
    model_policy_id: EntityId
    autonomy_level: AutonomyLevel = AutonomyLevel.a1
    tool_policy: ToolPolicy
    memory_policy: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class AgentCreateRequest(BaseModel):
    agent_code: str
    display_name: str
    description: Optional[str] = None
    department: Optional[str] = None
    role_name: Optional[str] = None
    version: AgentVersionCreateRequest


class AgentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    version: int
    runtime_adapter: str
    autonomy_level: str
    tool_policy: dict
    checksum: str
    created_at: datetime


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    agent_code: str
    display_name: str
    description: Optional[str]
    department: Optional[str]
    role_name: Optional[str]
    lifecycle_state: str
    active_version_id: Optional[EntityId]
    created_at: datetime
    updated_at: datetime
