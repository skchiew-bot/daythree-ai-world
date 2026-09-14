from unittest.mock import AsyncMock

import pytest

from common.db.models import AuditEvent
from contracts.enums import ActorType, EventType
from contracts.events import Actor, build_event
from contracts.ids import new_id
from event_service.publisher import EventPublisher

pytestmark = pytest.mark.unit


class _FakeSession:
    def __init__(self):
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


def _sample_event():
    return build_event(
        event_type=EventType.mission_started,
        tenant_id=new_id(),
        correlation_id=new_id(),
        actor=Actor(type=ActorType.user, id=new_id()),
        service="mission-engine",
        mission_id=new_id(),
    )


@pytest.mark.asyncio
async def test_publish_always_writes_the_audit_event_row():
    session = _FakeSession()
    publisher = EventPublisher(redis_client=None)
    event = _sample_event()

    await publisher.publish(event, session)

    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, AuditEvent)
    assert row.event_type == EventType.mission_started.value
    assert row.tenant_id == event.tenant_id
    assert row.mission_id == event.mission_id


@pytest.mark.asyncio
async def test_publish_broadcasts_to_redis_when_configured():
    session = _FakeSession()
    redis_mock = AsyncMock()
    publisher = EventPublisher(redis_client=redis_mock, stream_name="daythree.events")
    event = _sample_event()

    await publisher.publish(event, session)

    redis_mock.xadd.assert_awaited_once()
    args, _ = redis_mock.xadd.call_args
    assert args[0] == "daythree.events"


@pytest.mark.asyncio
async def test_redis_failure_does_not_prevent_the_durable_write_spec_15():
    """Redis unavailable: the DB write (audit_events) must still succeed — spec §15."""
    session = _FakeSession()
    redis_mock = AsyncMock()
    redis_mock.xadd.side_effect = ConnectionError("redis is down")
    publisher = EventPublisher(redis_client=redis_mock)
    event = _sample_event()

    await publisher.publish(event, session)  # must not raise

    assert len(session.added) == 1
