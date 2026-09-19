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
    # ADR-014 decision 3: non-null only while `activity` is `assigned`/`working` or
    # inside the result-hold window; null once the task is idle again (gate F6).
    project_id: Optional[EntityId] = None


class ProjectSummary(BaseModel):
    """ADR-014 decision 3/5: the world read's own minimal projection — never the
    full `ProjectResponse` — so a future field added to the Projects page schema
    doesn't silently start flowing into the polled world read."""

    id: EntityId
    code: str
    name: str
    status: str


class AgentRoomsResponse(BaseModel):
    """`rooms_per_floor`/`default_floor_count` carry the layout contract so the
    frontend never hardcodes it (see ADR-009's implementation plan)."""

    rooms_per_floor: int
    default_floor_count: int
    rooms: list[AgentRoomOut]
    # Every active project plus every project referenced by an emitted
    # `project_id` above, even if archived (ADR-014 decision 3, gate F6/F10).
    projects: list[ProjectSummary] = []
