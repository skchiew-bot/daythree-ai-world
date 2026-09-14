"""EventPublisher — spec §9/§15.

Durability contract: the `audit_events` INSERT happens on the caller's own DB session
(so it commits atomically with whatever state change produced the event — spec §4
rule 3 "every meaningful action is auditable" would be broken by a separate
transaction that could commit the state change but lose the event). The Redis publish
is strictly best-effort *after* that: if Redis is down, the event is still durably
recorded and a structured warning is logged — this is the literal implementation of
spec §15 "Redis unavailable → event publication retries [at the transport level] /
durable DB state remains correct".
"""
from __future__ import annotations

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AuditEvent
from contracts.events import EventEnvelope

logger = structlog.get_logger(__name__)


class EventPublisher:
    def __init__(self, redis_client: Redis | None, stream_name: str = "daythree.events"):
        self._redis = redis_client
        self._stream_name = stream_name

    async def publish(self, event: EventEnvelope, session: AsyncSession) -> None:
        session.add(
            AuditEvent(
                id=event.event_id,
                tenant_id=event.tenant_id,
                event_type=event.event_type.value,
                actor_type=event.actor.type.value,
                actor_id=event.actor.id,
                mission_id=event.mission_id,
                task_id=event.task_id,
                agent_id=event.agent_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                payload=event.model_dump(mode="json"),
                occurred_at=event.occurred_at,
            )
        )

        await self._publish_to_redis_best_effort(event)

    async def _publish_to_redis_best_effort(self, event: EventEnvelope) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.xadd(
                self._stream_name,
                {"event_id": str(event.event_id), "event_type": event.event_type.value,
                 "payload": event.model_dump_json()},
            )
        except Exception as exc:  # noqa: BLE001 — deliberately non-fatal, spec §15
            logger.warning(
                "redis_publish_failed",
                event_id=str(event.event_id),
                event_type=event.event_type.value,
                error=str(exc),
            )
