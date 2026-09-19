"""ADR-014 decision 3 / gate finding F3: two tenants whose agents' latest tasks
share an identical `created_at` (inserted in one transaction, since
`Task.created_at` is otherwise `server_default=func.now()` and therefore constant
within a transaction anyway) must never see each other's project through
`GET /agent-rooms` — proving the outer world-read query carries an explicit
`Mission.tenant_id` predicate, not just a tenant-scoped subquery feeding an
unfiltered outer `select(Task)`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from common.db.models import Agent, AgentVersion, Mission, MissionProject, ModelPolicy, Project, Task, Tenant, User
from contracts.enums import AgentLifecycleState, AutonomyLevel, MissionStatus, ProjectStatus, TaskStatus, UserRole, UserStatus
from contracts.ids import new_id
from contracts.policy import ToolPolicy

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


async def _build_tenant_with_running_task(db_session, label: str, shared_created_at: datetime):
    tenant = Tenant(id=new_id(), code=f"rp-iso-{label}", name=f"Tenant {label.upper()}")
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        id=new_id(), tenant_id=tenant.id, email=f"rp-iso-{label}@test.local", display_name=f"Admin {label}",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="mock-policy", primary_provider="mock", primary_model="mock",
    )
    db_session.add_all([admin, policy])
    await db_session.flush()

    project = Project(id=new_id(), tenant_id=tenant.id, code=f"PRJ{label.upper()}", name=f"Project {label}", status=ProjectStatus.active.value)
    agent = Agent(
        id=new_id(), tenant_id=tenant.id, agent_code=f"AGT-{label.upper()}", display_name=f"Agent {label}",
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add_all([project, agent])
    await db_session.flush()

    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="x", runtime_adapter="custom_durable",
        model_policy_id=policy.id, autonomy_level=AutonomyLevel.a1.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.flush()
    agent.active_version_id = version.id

    mission = Mission(
        id=new_id(), tenant_id=tenant.id, mission_code=f"MSN-{label.upper()}", title="t", objective="o",
        status=MissionStatus.running.value, budget_policy={}, assigned_agent_id=agent.id,
    )
    db_session.add(mission)
    await db_session.flush()
    db_session.add(MissionProject(mission_id=mission.id, tenant_id=tenant.id, project_id=project.id))

    task = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="t", instructions="i",
        status=TaskStatus.running.value, idempotency_key=str(new_id()), budget_policy={},
        created_at=shared_created_at, started_at=shared_created_at,
    )
    db_session.add(task)

    return {"tenant": tenant, "admin": admin, "project": project, "agent": agent}


@pytest.mark.asyncio
async def test_identical_task_timestamps_never_leak_a_project_across_tenants(client, db_session):
    shared_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    tenant_a = await _build_tenant_with_running_task(db_session, "a", shared_created_at)
    tenant_b = await _build_tenant_with_running_task(db_session, "b", shared_created_at)
    await db_session.commit()

    token_a = await _login(client, tenant_a["admin"].email)
    rooms_a = (await client.get("/api/v1/agent-rooms", headers={"Authorization": f"Bearer {token_a}"})).json()

    agent_ids_in_response = {r["agent_id"] for r in rooms_a["rooms"]}
    assert str(tenant_a["agent"].id) in agent_ids_in_response
    assert str(tenant_b["agent"].id) not in agent_ids_in_response

    project_ids_in_response = {p["id"] for p in rooms_a["projects"]}
    assert str(tenant_a["project"].id) in project_ids_in_response
    assert str(tenant_b["project"].id) not in project_ids_in_response

    room_a = next(r for r in rooms_a["rooms"] if r["agent_id"] == str(tenant_a["agent"].id))
    assert room_a["project_id"] == str(tenant_a["project"].id)
