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


class TaskCompleteExternalRequest(BaseModel):
    """See routes/tasks.py::complete_task_external — for a task assigned to an
    externally-executed agent (runtime_adapter != "custom_durable"), the caller has
    already done the real work outside Daythree and is reporting the result."""

    output_text: str


class TaskFailExternalRequest(BaseModel):
    reason: str
