from __future__ import annotations

import structlog
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from common.config import get_settings
from common.db.session import get_engine

router = APIRouter(tags=["health"])
logger = structlog.get_logger(__name__)


@router.get("/health/live")
async def live() -> dict:
    return {"status": "live"}


@router.get("/health/ready")
async def ready() -> dict:
    """Unauthenticated by design (a load balancer/orchestrator needs to call this
    before the caller is necessarily "logged in") — so the response never carries raw
    exception text (hostnames, driver internals), only "ok"/"error". Full detail goes
    to the structured logs instead, where an operator (not an anonymous caller) reads it.
    """
    checks = {"database": "unknown", "redis": "unknown"}

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_check_database_failed", error=str(exc))
        checks["database"] = "error"

    try:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(get_settings().redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_check_redis_failed", error=str(exc))
        checks["redis"] = "error"

    overall_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if overall_ok else "degraded", "checks": checks}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
