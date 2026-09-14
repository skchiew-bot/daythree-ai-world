"""The event envelope (spec §9) and a factory for building well-formed events.

Every material state change in the system emits one of these. The envelope shape is
frozen (`event_version`); adding a new `EventType` never changes the envelope itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import ActorType, EventType
from contracts.ids import EntityId, new_id

EVENT_VERSION = "1.0"


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: ActorType
    id: Optional[EntityId] = None


class EventMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    environment: str = "dev"


class EventEnvelope(BaseModel):
    """Matches spec §9 exactly. `data` is the event-type-specific payload."""

    model_config = ConfigDict(frozen=True)

    event_id: EntityId = Field(default_factory=new_id)
    event_type: EventType
    event_version: str = EVENT_VERSION
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tenant_id: EntityId
    correlation_id: EntityId
    causation_id: Optional[EntityId] = None
    actor: Actor
    mission_id: Optional[EntityId] = None
    task_id: Optional[EntityId] = None
    agent_id: Optional[EntityId] = None
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: EventMetadata


def build_event(
    *,
    event_type: EventType,
    tenant_id: EntityId,
    correlation_id: EntityId,
    actor: Actor,
    service: str,
    causation_id: EntityId | None = None,
    mission_id: EntityId | None = None,
    task_id: EntityId | None = None,
    agent_id: EntityId | None = None,
    data: dict[str, Any] | None = None,
    environment: str = "dev",
) -> EventEnvelope:
    """The one place every service builds an event, so the envelope shape can't drift."""
    return EventEnvelope(
        event_type=event_type,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        actor=actor,
        mission_id=mission_id,
        task_id=task_id,
        agent_id=agent_id,
        data=data or {},
        metadata=EventMetadata(service=service, environment=environment),
    )
