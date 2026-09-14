from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from contracts.ids import EntityId


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    mission_id: EntityId
    task_id: EntityId
    agent_id: EntityId
    agent_version_id: EntityId
    artifact_type: str
    title: str
    content_hash: str
    mime_type: str
    version: int
    created_at: datetime


class ArtifactDownloadResponse(BaseModel):
    download_url: str
    expires_in_seconds: int
