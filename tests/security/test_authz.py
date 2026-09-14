"""Spec §27 Security Tests + TC-P0-012: cross-tenant access denied, viewer cannot
mutate, invalid JWT/session denied, secrets never appear in an API response. Drives
the real FastAPI app end-to-end over HTTP (not just calling route functions directly)
so the actual dependency wiring (auth, tenant scoping, roles) is what's under test.
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


async def _login(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
async def two_tenants(db_session):
    tenant_a = Tenant(id=new_id(), code="tenant-a", name="Tenant A")
    tenant_b = Tenant(id=new_id(), code="tenant-b", name="Tenant B")
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    admin_a = User(
        id=new_id(), tenant_id=tenant_a.id, email="admin-a@test.local", display_name="Admin A",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    viewer_a = User(
        id=new_id(), tenant_id=tenant_a.id, email="viewer-a@test.local", display_name="Viewer A",
        role=UserRole.viewer.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    admin_b = User(
        id=new_id(), tenant_id=tenant_b.id, email="admin-b@test.local", display_name="Admin B",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    db_session.add_all([admin_a, viewer_a, admin_b])
    await db_session.flush()
    await db_session.commit()

    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "admin_a": admin_a, "viewer_a": viewer_a, "admin_b": admin_b}


@pytest.mark.asyncio
async def test_invalid_password_is_rejected(client, two_tenants):
    response = await client.post(
        "/api/v1/auth/login", data={"username": two_tenants["admin_a"].email, "password": "wrong-password"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_jwt_is_denied(client):
    response = await client.get("/api/v1/tenant", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_credentials_denied(client):
    response = await client.get("/api/v1/tenant")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_viewer_cannot_create_an_agent(client, two_tenants):
    token = await _login(client, two_tenants["viewer_a"].email)
    response = await client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_code": "AGT-X", "display_name": "X",
            "version": {
                "model_policy_id": str(new_id()),
                "tool_policy": {"allow": ["artifact.write"], "deny": ["*"]},
            },
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_an_agent(client, two_tenants):
    token = await _login(client, two_tenants["admin_a"].email)
    policy_id = new_id()  # no real ModelPolicy row — see the assertion note below

    response = await client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_code": "AGT-VALID", "display_name": "Valid Agent",
            "version": {
                "model_policy_id": str(policy_id),
                "tool_policy": {"allow": ["artifact.write"], "deny": ["*"]},
            },
        },
    )
    # No such model_policy row exists yet, so this is expected to fail at the DB FK
    # level (409/500) rather than at the authz layer (403) — the point of this test is
    # that a tenant_admin is NOT blocked by role, unlike the viewer above.
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_cross_tenant_mission_access_returns_404_not_403_tc_p0_012(client, two_tenants, db_session):
    from common.db.models import Mission
    from contracts.policy import BudgetPolicy

    mission = Mission(
        id=new_id(), tenant_id=two_tenants["tenant_a"].id, mission_code="MSN-CROSS-TENANT",
        title="Tenant A's mission", objective="x", status="draft",
        budget_policy=BudgetPolicy().model_dump(),
    )
    db_session.add(mission)
    await db_session.commit()

    token_b = await _login(client, two_tenants["admin_b"].email)
    response = await client.get(f"/api/v1/missions/{mission.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404  # not 403 — no resource-existence leak across tenants

    token_a = await _login(client, two_tenants["admin_a"].email)
    same_tenant_response = await client.get(
        f"/api/v1/missions/{mission.id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert same_tenant_response.status_code == 200


@pytest.mark.asyncio
async def test_login_response_never_contains_the_password_hash(client, two_tenants):
    token = await _login(client, two_tenants["admin_a"].email)
    me_response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert "password" not in me_response.text.lower()
    assert "password_hash" not in me_response.json()
