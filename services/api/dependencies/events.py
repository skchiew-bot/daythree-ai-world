"""A single `EventPublisher` per app process (built once at startup with the real
Redis client — see `app/main.py`'s lifespan) rather than a throwaway one per request,
so API-originated events (agent.*, mission.created, mission.started, task.created,
task.assigned) get the same live Redis broadcast as worker-originated ones.
"""
from __future__ import annotations

from fastapi import Request

from event_service.publisher import EventPublisher


async def get_event_publisher(request: Request) -> EventPublisher:
    return request.app.state.event_publisher
