"""Composition root: builds the concrete `EngineDeps` from settings. Kept in the
worker package (not `packages/common`) because it's the first place that legitimately
depends on every service — `common`/`contracts`/`policy-sdk` must stay dependency-free
of any concrete service, or the "swap the provider/runtime/transport" promise (spec §4
rules 7/8) stops being true.
"""
from __future__ import annotations

import redis.asyncio as redis_asyncio

from artifact_service.storage.object_store import ObjectStore, ObjectStoreConfig
from common.config import Settings
from event_service.publisher import EventPublisher
from model_gateway.gateway import ModelGateway
from model_gateway.providers.mock import MockModelProvider
from mission_engine.engine.task_executor import EngineDeps


def build_model_gateway(settings: Settings) -> ModelGateway:
    providers = {"mock": MockModelProvider()}
    if settings.anthropic_api_key:
        from model_gateway.providers.anthropic_provider import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(api_key=settings.anthropic_api_key)
    return ModelGateway(providers=providers)


def build_object_store(settings: Settings) -> ObjectStore:
    return ObjectStore(
        ObjectStoreConfig(
            endpoint_url=settings.object_store_endpoint_url,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            bucket=settings.object_store_bucket,
            region=settings.object_store_region,
            signed_url_ttl_seconds=settings.object_store_signed_url_ttl_seconds,
        )
    )


def build_redis_client(settings: Settings) -> redis_asyncio.Redis:
    return redis_asyncio.from_url(settings.redis_url)


def build_engine_deps(settings: Settings) -> EngineDeps:
    redis_client = build_redis_client(settings)
    return EngineDeps(
        model_gateway=build_model_gateway(settings),
        object_store=build_object_store(settings),
        event_publisher=EventPublisher(redis_client=redis_client, stream_name=settings.redis_stream_name),
    )
