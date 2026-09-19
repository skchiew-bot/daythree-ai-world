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
    # ADR-014 decision 2: optional link to a project, resolved with
    # get_tenant_scoped_or_404 (cross-tenant is a 404; archived is a 409).
    project_id: Optional[EntityId] = None


class MissionUpdateRequest(BaseModel):
    """The only mutable field today is the project link (ADR-014 decision 2) — every
    other mission field changes through a dedicated action route (start/cancel)."""

    project_id: Optional[EntityId] = None


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
    project_id: Optional[EntityId] = None
    # T1 build-plan condition C4: derived (never persisted -- no column is added to
    # `missions`), so Mission Control can hide Start/Cancel for a mission an
    # agent-runtime session owns. The real refusal is the 409 in start_mission_route/
    # cancel_mission below; this is cosmetic on top of it.
    is_agent_runtime: bool = False
