from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from contracts.ids import EntityId


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    event_type: str
    actor_type: str
    actor_id: Optional[EntityId]
    mission_id: Optional[EntityId]
    task_id: Optional[EntityId]
    agent_id: Optional[EntityId]
    correlation_id: EntityId
    causation_id: Optional[EntityId]
    payload: dict[str, Any]
    occurred_at: datetime
