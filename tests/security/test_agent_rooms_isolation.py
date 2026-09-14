"""ADR-009: two tenants each fill room (1,1) independently and never see each
other's rooms — the 404-not-403 tenant-isolation discipline used everywhere else
in the schema (agents.py, external_agents.py) applies here via the same
`Agent.tenant_id`/`Mission.tenant_id` scoping.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from common.db.models import Tenant, User
from contracts.enums import UserRole, UserStatus
from contracts.ids import new_id

from api.app.main import app
from api.dependencies.auth import hash_password
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client

pytestmark = [pytest.mark.integration, pytest.mark.security]

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
async def two_tenants(db_session):
    from common.db.models import ModelPolicy

    tenants = {}
    for label in ("a", "b"):
        tenant = Tenant(id=new_id(), code=f"rooms-iso-{label}", name=f"Tenant {label.upper()}")
        db_session.add(tenant)
        await db_session.flush()
        admin = User(
            id=new_id(), tenant_id=tenant.id, email=f"rooms-iso-{label}@test.local", display_name=f"Admin {label}",
            role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
        )
        policy = ModelPolicy(
            id=new_id(), tenant_id=tenant.id, name="mock-policy", primary_provider="mock", primary_model="mock",
        )
        db_session.add_all([admin, policy])
        await db_session.flush()
        tenants[label] = {"tenant": tenant, "admin": admin, "policy": policy}
    await db_session.commit()
    return tenants


def _agent_create_payload(agent_code: str, model_policy_id) -> dict:
    return {
        "agent_code": agent_code,
        "display_name": agent_code,
        "version": {
            "system_prompt": "x", "runtime_adapter": "custom_durable", "model_policy_id": str(model_policy_id),
            "autonomy_level": "A1", "tool_policy": {"allow": [], "deny": []},
        },
    }


@pytest.mark.asyncio
async def test_both_tenants_independently_occupy_floor_one_room_one(client, two_tenants):
    for label in ("a", "b"):
        token = await _login(client, two_tenants[label]["admin"].email)
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/v1/agents", headers=headers,
            json=_agent_create_payload(f"AGT-ISO-{label}", two_tenants[label]["policy"].id),
        )
        assert created.status_code == 201, created.text
        rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
        room = next(r for r in rooms if r["agent_id"] == created.json()["id"])
        assert (room["floor"], room["room_index"]) == (1, 1)


@pytest.mark.asyncio
async def test_tenant_never_sees_another_tenants_rooms(client, two_tenants):
    token_a = await _login(client, two_tenants["a"]["admin"].email)
    await client.post(
        "/api/v1/agents", headers={"Authorization": f"Bearer {token_a}"},
        json=_agent_create_payload("AGT-ISO-VISIBLE-A", two_tenants["a"]["policy"].id),
    )

    token_b = await _login(client, two_tenants["b"]["admin"].email)
    rooms_b = (await client.get("/api/v1/agent-rooms", headers={"Authorization": f"Bearer {token_b}"})).json()
    assert rooms_b["rooms"] == []


@pytest.mark.asyncio
async def test_agent_rooms_endpoint_requires_auth(client):
    response = await client.get("/api/v1/agent-rooms")
    assert response.status_code == 401
