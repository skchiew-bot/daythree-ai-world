"""External agent status feed (see ExternalAgentStatus in common.db.models):
auth is required, and one tenant never sees another tenant's rows.
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
    tenant_a = Tenant(id=new_id(), code="ext-tenant-a", name="Tenant A")
    tenant_b = Tenant(id=new_id(), code="ext-tenant-b", name="Tenant B")
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    admin_a = User(
        id=new_id(), tenant_id=tenant_a.id, email="ext-admin-a@test.local", display_name="Admin A",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    admin_b = User(
        id=new_id(), tenant_id=tenant_b.id, email="ext-admin-b@test.local", display_name="Admin B",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    db_session.add_all([admin_a, admin_b])
    await db_session.commit()

    return {"admin_a": admin_a, "admin_b": admin_b}


@pytest.mark.asyncio
async def test_status_update_requires_auth(client):
    response = await client.put("/api/v1/external-agents/claude-code/status", json={"status": "working"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_status_upsert_creates_then_updates(client, two_tenants):
    token = await _login(client, two_tenants["admin_a"].email)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.put(
        "/api/v1/external-agents/claude-code/status",
        headers=headers,
        json={"status": "working", "job_description": "Building the status feed"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "working"

    updated = await client.put(
        "/api/v1/external-agents/claude-code/status",
        headers=headers,
        json={"status": "done", "job_description": None},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"
    assert updated.json()["job_description"] is None

    listing = await client.get("/api/v1/external-agents", headers=headers)
    assert listing.status_code == 200
    names = [row["name"] for row in listing.json()]
    assert names == ["claude-code"]  # upsert, not a second row


@pytest.mark.asyncio
async def test_tenants_do_not_see_each_others_external_agents(client, two_tenants):
    token_a = await _login(client, two_tenants["admin_a"].email)
    token_b = await _login(client, two_tenants["admin_b"].email)

    await client.put(
        "/api/v1/external-agents/claude-code/status",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"status": "working"},
    )

    listing_b = await client.get("/api/v1/external-agents", headers={"Authorization": f"Bearer {token_b}"})
    assert listing_b.status_code == 200
    assert listing_b.json() == []
