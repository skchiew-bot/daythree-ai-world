from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from contracts.ids import EntityId


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    mission_id: EntityId
    assigned_agent_id: EntityId
    title: str
    status: str
    retry_count: int
    output_artifact_id: Optional[EntityId]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
