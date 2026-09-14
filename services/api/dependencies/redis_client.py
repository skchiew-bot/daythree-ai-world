from __future__ import annotations

from fastapi import Request
from redis.asyncio import Redis


async def get_redis_client(request: Request) -> Redis:
    return request.app.state.redis_client
