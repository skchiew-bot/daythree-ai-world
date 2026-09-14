"""A minimal reference consumer: tails the Redis event stream and logs each event.

Phase 0 has no real downstream consumer (the 3D world doesn't exist yet — spec §36
says the event backbone exists so Phase 3 can consume it later). This exists to prove
the stream actually carries events during the demo/resilience tests, not as a
production consumer.
"""
from __future__ import annotations

import asyncio

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


async def tail_stream(redis_client: Redis, stream_name: str, *, stop_after: int | None = None) -> None:
    last_id = "$"
    seen = 0
    while stop_after is None or seen < stop_after:
        entries = await redis_client.xread({stream_name: last_id}, block=5000, count=10)
        for _stream, messages in entries:
            for message_id, fields in messages:
                last_id = message_id
                seen += 1
                logger.info("event_stream_message", event_type=fields.get(b"event_type") or fields.get("event_type"))
        await asyncio.sleep(0)
