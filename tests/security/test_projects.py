"""ADR-014 decision 2: projects are create/archive-only, gated the same way
`model_policies.py` is (role constant + fixed-window rate limit), with a per-tenant
active cap (F10) and validated code/name (D12). `audit_events.payload` for both
lifecycle events must carry only ids/status/actor — never `name` or `code` (D17).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from common.db.models import AuditEvent, Project, Tenant, User
from contracts.enums import EventType, ProjectStatus, UserRole, UserStatus
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
    tenant = Tenant(id=new_id(), code="proj-tenant", name="Projects Tenant")
    db_session.add(tenant)
    await db_session.flush()

    users = {}
    for role in (UserRole.tenant_admin, UserRole.operator, UserRole.viewer):
        user = User(
            id=new_id(), tenant_id=tenant.id, email=f"proj-{role.value}@test.local", display_name=role.value,
            role=role.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
        )
        db_session.add(user)
        users[role.value] = user
    await db_session.commit()

    return {"tenant": tenant, **users}


@pytest.fixture
async def second_tenant_admin(db_session):
    tenant = Tenant(id=new_id(), code="proj-tenant-2", name="Second Projects Tenant")
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        id=new_id(), tenant_id=tenant.id, email="proj2-admin@test.local", display_name="Admin 2",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    db_session.add(admin)
    await db_session.commit()
    return {"tenant": tenant, "tenant_admin": admin}


def _payload(code: str, name: str = "Internal Codename") -> dict:
    return {"code": code, "name": name}


@pytest.mark.asyncio
async def test_viewer_cannot_create_project(client, tenant_with_users):
    token = await _login(client, tenant_with_users["viewer"].email)
    response = await client.post(
        "/api/v1/projects", headers={"Authorization": f"Bearer {token}"}, json=_payload("VIEW1")
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_archive_project(client, tenant_with_users, db_session):
    project = Project(
        id=new_id(), tenant_id=tenant_with_users["tenant"].id, code="ARCH1", name="n",
        status=ProjectStatus.active.value,
    )
    db_session.add(project)
    await db_session.commit()

    token = await _login(client, tenant_with_users["viewer"].email)
    response = await client.post(
        f"/api/v1/projects/{project.id}/archive", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_operator_can_create_and_archive_a_project(client, tenant_with_users):
    """Unlike model_policies.py (which excludes operator), ADR-014 decision 2 names
    operator among the mutating roles for projects."""
    token = await _login(client, tenant_with_users["operator"].email)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post("/api/v1/projects", headers=headers, json=_payload("OPS1"))
    assert created.status_code == 201, created.text

    archived = await client.post(f"/api/v1/projects/{created.json()['id']}/archive", headers=headers)
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_duplicate_code_within_a_tenant_is_409(client, tenant_with_users):
    token = await _login(client, tenant_with_users["tenant_admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/api/v1/projects", headers=headers, json=_payload("DUP1"))
    assert first.status_code == 201

    second = await client.post("/api/v1/projects", headers=headers, json=_payload("DUP1"))
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_same_code_across_two_tenants_is_fine(client, tenant_with_users, second_tenant_admin):
    token_a = await _login(client, tenant_with_users["tenant_admin"].email)
    token_b = await _login(client, second_tenant_admin["tenant_admin"].email)

    first = await client.post(
        "/api/v1/projects", headers={"Authorization": f"Bearer {token_a}"}, json=_payload("SAME1")
    )
    second = await client.post(
        "/api/v1/projects", headers={"Authorization": f"Bearer {token_b}"}, json=_payload("SAME1")
    )
    assert first.status_code == 201
    assert second.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,name",
    [
        ("lowercase", "Name"),          # must start uppercase/digit and be uppercase pattern
        ("", "Name"),                    # too short
        ("X" * 21, "Name"),               # too long
        ("BAD CODE", "Name"),             # space not allowed
        ("OK1", ""),                       # empty name
        ("OK2", "x" * 81),                 # name too long
        ("OK3", "bad\x00control"),          # control character
    ],
)
async def test_invalid_code_or_name_is_422(client, tenant_with_users, code, name):
    token = await _login(client, tenant_with_users["tenant_admin"].email)
    response = await client.post(
        "/api/v1/projects", headers={"Authorization": f"Bearer {token}"}, json=_payload(code, name)
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_forty_ninth_active_project_is_rejected(client, tenant_with_users):
    from api.routes.projects import _MAX_ACTIVE_PROJECTS

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    last_status = None
    for i in range(_MAX_ACTIVE_PROJECTS + 1):
        last_status = (
            await client.post("/api/v1/projects", headers=headers, json=_payload(f"CAP{i}"))
        ).status_code
    assert last_status == 409


@pytest.mark.asyncio
async def test_project_creation_is_rate_limited(client, tenant_with_users):
    from api.routes.projects import _RATE_LIMIT_MAX_REQUESTS

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    last_status = None
    for i in range(_RATE_LIMIT_MAX_REQUESTS + 1):
        last_status = (
            await client.post("/api/v1/projects", headers=headers, json=_payload(f"RL{i}"))
        ).status_code
    assert last_status == 429


@pytest.mark.asyncio
async def test_project_audit_events_never_contain_name_or_code(client, tenant_with_users, db_session, fake_redis):
    app.dependency_overrides[get_event_publisher] = lambda: EventPublisher(redis_client=fake_redis)

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/v1/projects", headers=headers, json=_payload("SECRET-CODE", "Client Legal Name Inc")
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    archived = await client.post(f"/api/v1/projects/{project_id}/archive", headers=headers)
    assert archived.status_code == 200

    events = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.event_type.in_(
                    [EventType.project_created.value, EventType.project_archived.value]
                )
            )
        )
    ).scalars().all()
    assert len(events) == 2
    for event in events:
        import json

        payload_text = json.dumps(event.payload)
        assert "SECRET-CODE" not in payload_text
        assert "Client Legal Name Inc" not in payload_text


@pytest.mark.asyncio
async def test_mission_cannot_link_to_another_tenants_project(client, tenant_with_users, second_tenant_admin, db_session):
    from common.db.models import Agent, AgentVersion, ModelPolicy
    from contracts.enums import AgentLifecycleState, AutonomyLevel
    from contracts.policy import ToolPolicy

    other_project = Project(
        id=new_id(), tenant_id=second_tenant_admin["tenant"].id, code="OTHER1", name="n",
        status=ProjectStatus.active.value,
    )
    db_session.add(other_project)

    policy = ModelPolicy(
        id=new_id(), tenant_id=tenant_with_users["tenant"].id, name="mock-policy",
        primary_provider="mock", primary_model="mock",
    )
    db_session.add(policy)
    await db_session.flush()

    agent = Agent(
        id=new_id(), tenant_id=tenant_with_users["tenant"].id, agent_code="AGT-MP", display_name="Agent",
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="x", runtime_adapter="custom_durable",
        model_policy_id=policy.id, autonomy_level=AutonomyLevel.a1.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.commit()

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    response = await client.post(
        "/api/v1/missions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "t", "objective": "o", "assigned_agent_id": str(agent.id),
            "project_id": str(other_project.id),
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mission_cannot_link_to_an_archived_project(client, tenant_with_users, db_session):
    from common.db.models import Agent, AgentVersion, ModelPolicy
    from contracts.enums import AgentLifecycleState, AutonomyLevel
    from contracts.policy import ToolPolicy

    project = Project(
        id=new_id(), tenant_id=tenant_with_users["tenant"].id, code="ARCHLNK", name="n",
        status=ProjectStatus.archived.value,
    )
    db_session.add(project)

    policy = ModelPolicy(
        id=new_id(), tenant_id=tenant_with_users["tenant"].id, name="mock-policy-2",
        primary_provider="mock", primary_model="mock",
    )
    db_session.add(policy)
    await db_session.flush()

    agent = Agent(
        id=new_id(), tenant_id=tenant_with_users["tenant"].id, agent_code="AGT-MP2", display_name="Agent",
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="x", runtime_adapter="custom_durable",
        model_policy_id=policy.id, autonomy_level=AutonomyLevel.a1.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.commit()

    token = await _login(client, tenant_with_users["tenant_admin"].email)
    response = await client.post(
        "/api/v1/missions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "t", "objective": "o", "assigned_agent_id": str(agent.id),
            "project_id": str(project.id),
        },
    )
    assert response.status_code == 409
