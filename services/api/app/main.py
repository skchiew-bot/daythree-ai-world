from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from artifact_service.storage.object_store import ObjectStore, ObjectStoreConfig
from common.config import get_settings
from event_service.publisher import EventPublisher
from observability.logging.setup import configure_logging
from observability.tracing.setup import configure_tracing

from api.middleware.request_context import RequestContextMiddleware
from api.routes import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.require_safe_for_production()
    configure_logging(settings.log_level)

    redis_client = redis_asyncio.from_url(settings.redis_url)
    app.state.redis_client = redis_client
    app.state.event_publisher = EventPublisher(redis_client, stream_name=settings.redis_stream_name)
    app.state.object_store = ObjectStore(
        ObjectStoreConfig(
            endpoint_url=settings.object_store_endpoint_url,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            bucket=settings.object_store_bucket,
            region=settings.object_store_region,
            signed_url_ttl_seconds=settings.object_store_signed_url_ttl_seconds,
        )
    )
    try:
        yield
    finally:
        await redis_client.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Daythree AI World API",
        version="0.1.0",
        description="Phase 0: agent registry, missions, tasks, artifacts, audit.",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    configure_tracing(app, service_name=settings.otel_service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
    return app


app = create_app()
