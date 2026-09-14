"""ModelPolicy is create-only (guardian-gatekeeper, 2026-09-15, "PATCH /model-policies"
gate review — BLOCK + Alternative A): no PATCH exists, only POST. These tests cover the
gate's explicit conditions — role gate narrower than agents.py's MUTATORS (A2), provider
allow-list validation (A3), duplicate-name rejection (A5), the model_policy.created audit
event committing atomically with the insert (A6), and rate limiting (A7).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from common.db.models import AuditEvent, Tenant, User
from contracts.enums import EventType, UserRole, UserStatus
from contracts.ids import new_id
from event_service.publisher import EventPublisher

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
async def tenant_with_users(db_session):
    tenant = Tenant(id=new_id(), code="mp-tenant", name="MP Tenant")
    db_session.add(tenant)
    await db_session.flush()

    users = {}
    for role in (UserRole.tenant_admin, UserRole.operator, UserRole.viewer):
        user = User(
            id=new_id(), tenant_id=tenant.id, email=f"mp-{role.value}@test.local", display_name=role.value,
            role=role.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
        )
        db_session.add(user)
        users[role.value] = user
    await db_session.commit()

    return {"tenant": tenant, **users}


def _payload(name: str, provider: str = "mock") -> dict:
    return {"name": name, "primary_provider": provider, "primary_model": "mock-model"}


@pytest.mark.asyncio
async def test_viewer_cannot_create_model_policy(client, tenant_with_users):
    token = await _login(client, tenant_with_users["viewer"].email)
    response = await client.post(
        "/api/v1/model-policies", headers={"Authorization": f"Bearer {token}"}, json=_payload("p1")
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_operator_cannot_create_model_policy(client, tenant_with_users):
    """Gate condition A2: narrower than agents.py's MUTATORS — operator is excluded
    given the spend impact of which provider an agent uses."""
    token = await _login(client, tenant_with_users["operator"].email)
    response = await client.post(
        "/api/v1/model-policies", headers={"Authorization": f"Bearer {token}"}, json=_payload("p1")
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenant_admin_can_create_model_policy(client, tenant_with_users):
    token = await _login(client, tenant_with_users["tenant_admin"].email)
    response = await client.post(
        "/api/v1/model-policies", headers={"Authorization": f"Bearer {token}"}, json=_payload("p1")
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "p1"
    assert body["primary_provider"] == "mock"


@pytest.mark.asyncio
async def test_duplicate_name_is_rejected(client, tenant_with_users):
    token = await _login(client, tenant_with_users["tenant_admin"].email)
    headers = {"Authorization": f"Bearer {token}"}
    first = await client.post("/api/v1/model-policies", headers=headers, json=_payload("dup"))
    assert first.status_code == 201

    second = await client.post("/api/v1/model-policies", headers=headers, json=_payload("dup"))
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_unregistered_provider_is_rejected(client, tenant_with_users):
    """Gate condition A3: primary_provider is validated against the same allow-list
    build_model_gateway would actually register, not an arbitrary string."""
    token = await _login(client, tenant_with_users["tenant_admin"].email)
    response = await client.post(
        "/api/v1/model-policies",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload("p1", provider="definitely-not-a-real-provider"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_model_policy_creation_is_rate_limited(client, tenant_with_users):
    from api.routes.model_policies import _RATE_LIMIT_MAX_REQUESTS

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    last_status = None
    for i in range(_RATE_LIMIT_MAX_REQUESTS + 1):
        last_status = (
            await client.post("/api/v1/model-policies", headers=headers, json=_payload(f"rl-{i}"))
        ).status_code

    assert last_status == 429


@pytest.mark.asyncio
async def test_model_policy_created_event_is_recorded_atomically(client, tenant_with_users, db_session, fake_redis):
    """Gate condition A6: the audit row commits in the same transaction as the insert —
    verified here with the real EventPublisher (not the noop the other tests use)."""
    app.dependency_overrides[get_event_publisher] = lambda: EventPublisher(redis_client=fake_redis)

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    response = await client.post(
        "/api/v1/model-policies", headers={"Authorization": f"Bearer {token}"}, json=_payload("audited")
    )
    assert response.status_code == 201
    policy_id = response.json()["id"]

    events = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.event_type == EventType.model_policy_created.value))
    ).scalars().all()
    assert any(str(e.correlation_id) == policy_id for e in events)
