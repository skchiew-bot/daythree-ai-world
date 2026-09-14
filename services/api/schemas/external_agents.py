from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ExternalAgentStatusValue = Literal["idle", "working", "done", "failed"]


class ExternalAgentStatusUpdate(BaseModel):
    status: ExternalAgentStatusValue
    job_description: Optional[str] = Field(default=None, max_length=500)


class ExternalAgentStatusOut(BaseModel):
    name: str
    status: str
    job_description: Optional[str]
    updated_at: datetime
