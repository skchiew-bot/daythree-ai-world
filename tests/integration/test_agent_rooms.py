"""ADR-009: agent room assignment. Drives the real FastAPI app end-to-end (same
pattern as tests/integration/test_external_task_completion.py) plus a couple of
direct-service tests for behavior that isn't reachable over HTTP (allocator
exhaustion, exception-survival).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from common.db.models import Agent, AgentRoomAssignment, AgentVersion, Mission, ModelPolicy, Task, Tenant, User
from contracts.enums import AgentLifecycleState, AutonomyLevel, MissionStatus, TaskStatus, UserRole, UserStatus
from contracts.ids import new_id
from contracts.policy import ToolPolicy

from api.app.main import app
from api.dependencies.auth import hash_password
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client
from api.services.room_assignment import ensure_assignment, get_assignment, release_assignment

pytestmark = pytest.mark.integration

PASSWORD = "Test-Password-123!"


class _NoopEventPublisher:
    async def publish(self, event, session) -> None:
        pass


@pytest.fixture
async def client(db_session, fake_redis):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_event_publisher] = lambda: _NoopEventPublisher()
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    app.dependency_overrides[get_object_store] = lambda: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
async def tenant_admin(db_session):
    tenant = Tenant(id=new_id(), code="rooms-tenant", name="Rooms Tenant")
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        id=new_id(), tenant_id=tenant.id, email="rooms-admin@test.local", display_name="Admin",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    db_session.add(admin)

    policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="mock-policy", primary_provider="mock", primary_model="mock",
    )
    db_session.add(policy)
    await db_session.commit()

    return {"tenant": tenant, "admin": admin, "policy": policy}


def _agent_create_payload(agent_code: str, model_policy_id) -> dict:
    return {
        "agent_code": agent_code,
        "display_name": agent_code,
        "version": {
            "system_prompt": "x",
            "runtime_adapter": "custom_durable",
            "model_policy_id": str(model_policy_id),
            "autonomy_level": "A1",
            "tool_policy": {"allow": [], "deny": []},
        },
    }


@pytest.mark.asyncio
async def test_registering_an_agent_assigns_a_room(client, tenant_admin):
    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/agents", headers=headers,
        json=_agent_create_payload("AGT-ROOM-1", tenant_admin["policy"].id),
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]

    rooms = await client.get("/api/v1/agent-rooms", headers=headers)
    assert rooms.status_code == 200, rooms.text
    body = rooms.json()
    assert body["rooms_per_floor"] == 4
    matching = [r for r in body["rooms"] if r["agent_id"] == agent_id]
    assert len(matching) == 1
    assert matching[0]["floor"] == 1
    assert matching[0]["room_index"] == 1
    assert matching[0]["activity"] == "idle"


@pytest.mark.asyncio
async def test_room_assignment_is_idempotent_across_reads(client, tenant_admin):
    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/v1/agents", headers=headers,
        json=_agent_create_payload("AGT-ROOM-2", tenant_admin["policy"].id),
    )
    agent_id = created.json()["id"]

    first = await client.get("/api/v1/agent-rooms", headers=headers)
    second = await client.get("/api/v1/agent-rooms", headers=headers)
    room_first = next(r for r in first.json()["rooms"] if r["agent_id"] == agent_id)
    room_second = next(r for r in second.json()["rooms"] if r["agent_id"] == agent_id)
    assert (room_first["floor"], room_first["room_index"]) == (room_second["floor"], room_second["room_index"])


@pytest.mark.asyncio
async def test_twenty_first_agent_overflows_to_floor_six(client, tenant_admin):
    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    last_agent_id = None
    for i in range(21):
        created = await client.post(
            "/api/v1/agents", headers=headers,
            json=_agent_create_payload(f"AGT-OVERFLOW-{i:02d}", tenant_admin["policy"].id),
        )
        assert created.status_code == 201, created.text
        last_agent_id = created.json()["id"]

    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    last_room = next(r for r in rooms if r["agent_id"] == last_agent_id)
    assert (last_room["floor"], last_room["room_index"]) == (6, 1)


@pytest.mark.asyncio
async def test_suspend_releases_room_and_it_is_reused(client, tenant_admin):
    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/api/v1/agents", headers=headers,
        json=_agent_create_payload("AGT-SUSPEND-1", tenant_admin["policy"].id),
    )
    first_id = first.json()["id"]
    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    first_room = next(r for r in rooms if r["agent_id"] == first_id)
    assert (first_room["floor"], first_room["room_index"]) == (1, 1)

    suspended = await client.post(f"/api/v1/agents/{first_id}/suspend", headers=headers)
    assert suspended.status_code == 200, suspended.text

    rooms_after_suspend = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    assert all(r["agent_id"] != first_id for r in rooms_after_suspend)  # suspended agents aren't listed

    second = await client.post(
        "/api/v1/agents", headers=headers,
        json=_agent_create_payload("AGT-SUSPEND-2", tenant_admin["policy"].id),
    )
    second_id = second.json()["id"]
    rooms_after_new = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    second_room = next(r for r in rooms_after_new if r["agent_id"] == second_id)
    assert (second_room["floor"], second_room["room_index"]) == (1, 1)  # the freed room is reused


@pytest.mark.asyncio
async def test_seeded_agent_with_no_prior_row_is_roomed_on_first_read(client, db_session, tenant_admin):
    """The plan's lazy-backfill requirement: an agent created a way other than the
    /agents route (e.g. seed.py) still gets a room on the first GET, without
    touching seed.py."""
    agent = Agent(
        id=new_id(), tenant_id=tenant_admin["tenant"].id, agent_code="AGT-SEEDED",
        display_name="Seeded", lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(agent)
    await db_session.commit()

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}
    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    assert any(r["agent_id"] == str(agent.id) for r in rooms)


@pytest.mark.asyncio
async def test_activity_reflects_task_lifecycle(client, db_session, tenant_admin):
    agent = Agent(
        id=new_id(), tenant_id=tenant_admin["tenant"].id, agent_code="AGT-ACTIVITY",
        display_name="Activity", lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="x", runtime_adapter="custom_durable",
        model_policy_id=tenant_admin["policy"].id, autonomy_level=AutonomyLevel.a1.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.flush()
    agent.active_version_id = version.id

    mission = Mission(
        id=new_id(), tenant_id=tenant_admin["tenant"].id, mission_code="MSN-ROOMS-1", title="t", objective="o",
        status=MissionStatus.running.value, budget_policy={}, assigned_agent_id=agent.id,
    )
    db_session.add(mission)
    await db_session.flush()
    task = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="t", instructions="i",
        status=TaskStatus.queued.value, idempotency_key=str(new_id()), budget_policy={},
    )
    db_session.add(task)
    await db_session.commit()

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    room = next(r for r in rooms if r["agent_id"] == str(agent.id))
    assert room["activity"] == "assigned"

    task.status = TaskStatus.running.value
    await db_session.commit()
    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    room = next(r for r in rooms if r["agent_id"] == str(agent.id))
    assert room["activity"] == "working"


@pytest.mark.asyncio
async def test_registration_survives_an_allocator_exception(client, tenant_admin, monkeypatch):
    """R2 regression test: if room allocation raises, agent creation must still
    succeed — ensure_assignment must not leak an exception into create_agent."""
    import api.routes.agents as agents_route

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated allocator failure")

    monkeypatch.setattr(agents_route, "ensure_assignment", _boom)

    token = await _login(client, tenant_admin["admin"].email)
    response = await client.post(
        "/api/v1/agents", headers={"Authorization": f"Bearer {token}"},
        json=_agent_create_payload("AGT-SURVIVES", tenant_admin["policy"].id),
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_ensure_assignment_is_exception_contained_at_the_service_layer(db_session, tenant_admin, monkeypatch):
    """Direct-service version of the same guarantee: even a raw exception inside the
    allocator's own retry loop returns None instead of propagating."""
    import api.services.room_assignment as room_assignment_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(room_assignment_module, "list_assignments", _boom)

    result = await ensure_assignment(db_session, tenant_admin["tenant"].id, new_id())
    assert result is None
