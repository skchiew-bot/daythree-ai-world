import pytest

from contracts.enums import ActorType, EventType
from contracts.events import Actor, build_event
from contracts.ids import new_id

pytestmark = pytest.mark.unit


def test_build_event_produces_a_well_formed_envelope():
    tenant_id = new_id()
    correlation_id = new_id()
    agent_id = new_id()

    event = build_event(
        event_type=EventType.task_started,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        actor=Actor(type=ActorType.agent, id=agent_id),
        service="mission-engine",
        agent_id=agent_id,
        data={"foo": "bar"},
    )

    assert event.event_type == EventType.task_started
    assert event.event_version == "1.0"
    assert event.tenant_id == tenant_id
    assert event.correlation_id == correlation_id
    assert event.agent_id == agent_id
    assert event.data == {"foo": "bar"}
    assert event.metadata.service == "mission-engine"
    assert event.event_id is not None


def test_build_event_defaults_causation_and_data_to_none_and_empty():
    event = build_event(
        event_type=EventType.mission_created,
        tenant_id=new_id(),
        correlation_id=new_id(),
        actor=Actor(type=ActorType.user, id=new_id()),
        service="api",
    )
    assert event.causation_id is None
    assert event.data == {}


def test_event_envelope_is_immutable():
    event = build_event(
        event_type=EventType.mission_created,
        tenant_id=new_id(),
        correlation_id=new_id(),
        actor=Actor(type=ActorType.user, id=new_id()),
        service="api",
    )
    with pytest.raises(Exception):
        event.event_type = EventType.mission_failed
