from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from contracts.enums import MissionPriority, MissionStatus, RiskLevel
from contracts.ids import EntityId
from contracts.policy import BudgetPolicy


class MissionCreateRequest(BaseModel):
    title: str
    objective: str
    assigned_agent_id: EntityId
    priority: MissionPriority = MissionPriority.normal
    risk_level: RiskLevel = RiskLevel.low
    budget_policy: Optional[BudgetPolicy] = None


class MissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    mission_code: str
    title: str
    objective: str
    status: str
    priority: str
    risk_level: str
    assigned_agent_id: Optional[EntityId]
    budget_policy: dict
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
