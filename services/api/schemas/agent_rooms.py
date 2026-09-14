from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from contracts.ids import EntityId

RoomActivity = Literal["idle", "assigned", "working", "completed", "failed"]


class AgentRoomOut(BaseModel):
    agent_id: EntityId
    agent_code: str
    display_name: str
    lifecycle_state: str
    floor: int
    room_index: int
    assigned_at: datetime
    activity: RoomActivity
    active_task_id: Optional[EntityId]
    activity_changed_at: Optional[datetime]


class AgentRoomsResponse(BaseModel):
    """`rooms_per_floor`/`default_floor_count` carry the layout contract so the
    frontend never hardcodes it (see ADR-009's implementation plan)."""

    rooms_per_floor: int
    default_floor_count: int
    rooms: list[AgentRoomOut]
