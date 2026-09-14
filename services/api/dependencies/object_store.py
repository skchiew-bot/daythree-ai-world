from __future__ import annotations

from fastapi import Request

from artifact_service.storage.object_store import ObjectStore


async def get_object_store(request: Request) -> ObjectStore:
    return request.app.state.object_store
