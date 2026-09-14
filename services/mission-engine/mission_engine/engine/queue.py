"""The task queue: a plain Redis list. A native asyncio worker `BRPOP`s from it — no
Celery/Dramatiq broker needed for Phase 0's single-queue, single-tenant-scale needs
(see docs/adr/ADR-003-event-transport.md).
"""
from __future__ import annotations

import uuid

from redis.asyncio import Redis

TASK_QUEUE_KEY = "daythree:task_queue"


async def enqueue_task(redis_client: Redis, task_id: uuid.UUID) -> None:
    await redis_client.lpush(TASK_QUEUE_KEY, str(task_id))


async def dequeue_task(redis_client: Redis, timeout_seconds: int = 5) -> uuid.UUID | None:
    result = await redis_client.brpop([TASK_QUEUE_KEY], timeout=timeout_seconds)
    if result is None:
        return None
    _, value = result
    return uuid.UUID(value.decode() if isinstance(value, bytes) else value)
