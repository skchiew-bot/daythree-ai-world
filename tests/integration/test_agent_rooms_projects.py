"""ADR-014 decision 3: the world read gains `project_id` per agent and a top-level
`projects` array. Covers gate finding F5 (deterministic active-task pick across
repeated reads), the `project_id` lifetime contract (non-null only while
assigned/working or inside the result-hold window), and F6 (an archived-but-
referenced project still appears in `projects`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    tenant = Tenant(id=new_id(), code="rp-tenant", name="RP Tenant")
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        id=new_id(), tenant_id=tenant.id, email="rp-admin@test.local", display_name="Admin",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="mock-policy", primary_provider="mock", primary_model="mock",
    )
    db_session.add_all([admin, policy])
    await db_session.commit()
    return {"tenant": tenant, "admin": admin, "policy": policy}


async def _make_agent_with_mission(db_session, tenant_admin, project=None):
    tenant = tenant_admin["tenant"]
    agent = Agent(
        id=new_id(), tenant_id=tenant.id, agent_code=f"AGT-{new_id().hex[:8]}", display_name="Agent",
        lifecycle_state=AgentLifecycleState.active.value,
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
        id=new_id(), tenant_id=tenant.id, mission_code=f"MSN-{new_id().hex[:8]}", title="t", objective="o",
        status=MissionStatus.running.value, budget_policy={}, assigned_agent_id=agent.id,
    )
    db_session.add(mission)
    await db_session.flush()
    if project is not None:
        db_session.add(MissionProject(mission_id=mission.id, tenant_id=tenant.id, project_id=project.id))
        await db_session.flush()
    return agent, mission


@pytest.mark.asyncio
async def test_active_task_pick_is_stable_across_twenty_consecutive_reads(client, db_session, tenant_admin):
    """Gate finding F5: two tasks tied on `created_at` for the same agent must not
    make the world read flicker between them on successive polls."""
    agent, mission = await _make_agent_with_mission(db_session, tenant_admin)
    shared_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    older = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="older", instructions="i",
        status=TaskStatus.queued.value, idempotency_key=str(new_id()), budget_policy={}, created_at=shared_created_at,
    )
    newer = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="newer", instructions="i",
        status=TaskStatus.queued.value, idempotency_key=str(new_id()), budget_policy={}, created_at=shared_created_at,
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    expected_task_id = str(max(older.id, newer.id))  # DISTINCT ON ... ORDER BY ..., id DESC

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}
    picks = set()
    for _ in range(20):
        rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
        room = next(r for r in rooms if r["agent_id"] == str(agent.id))
        picks.add(room["active_task_id"])

    assert picks == {expected_task_id}


@pytest.mark.asyncio
async def test_project_id_is_present_while_working_and_null_once_the_hold_window_passes(client, db_session, tenant_admin):
    from api.routes.agent_rooms import _RESULT_HOLD_SECONDS

    project = Project(id=new_id(), tenant_id=tenant_admin["tenant"].id, code="LIFECYC", name="n", status=ProjectStatus.active.value)
    db_session.add(project)
    await db_session.flush()
    agent, mission = await _make_agent_with_mission(db_session, tenant_admin, project=project)

    now = datetime.now(timezone.utc)
    task = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="t", instructions="i",
        status=TaskStatus.running.value, idempotency_key=str(new_id()), budget_policy={},
        started_at=now, created_at=now,
    )
    db_session.add(task)
    await db_session.commit()

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}

    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    room = next(r for r in rooms if r["agent_id"] == str(agent.id))
    assert room["activity"] == "working"
    assert room["project_id"] == str(project.id)

    task.status = TaskStatus.completed.value
    task.completed_at = now - timedelta(seconds=_RESULT_HOLD_SECONDS + 1)
    await db_session.commit()

    rooms = (await client.get("/api/v1/agent-rooms", headers=headers)).json()["rooms"]
    room = next(r for r in rooms if r["agent_id"] == str(agent.id))
    assert room["activity"] == "idle"
    assert room["project_id"] is None


@pytest.mark.asyncio
async def test_archived_but_referenced_project_still_appears_in_projects_array(client, db_session, tenant_admin):
    project = Project(id=new_id(), tenant_id=tenant_admin["tenant"].id, code="ARCHREF", name="n", status=ProjectStatus.active.value)
    db_session.add(project)
    await db_session.flush()
    agent, mission = await _make_agent_with_mission(db_session, tenant_admin, project=project)

    now = datetime.now(timezone.utc)
    task = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="t", instructions="i",
        status=TaskStatus.running.value, idempotency_key=str(new_id()), budget_policy={},
        started_at=now, created_at=now,
    )
    db_session.add(task)
    project.status = ProjectStatus.archived.value
    await db_session.commit()

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}
    body = (await client.get("/api/v1/agent-rooms", headers=headers)).json()

    project_ids = {p["id"] for p in body["projects"]}
    assert str(project.id) in project_ids
    matching = next(p for p in body["projects"] if p["id"] == str(project.id))
    assert matching["status"] == "archived"


@pytest.mark.asyncio
async def test_projects_array_is_ordered_by_created_at_then_id_even_after_a_row_is_updated(
    client, db_session, tenant_admin
):
    """ADR-014 gate F7: the town places buildings by probing in the order the API returns
    `projects[]`, so that order must be `(created_at, id)`, not Postgres's physical row
    order. An UPDATE writes a new tuple version, which changes the physical order of a
    heap scan; without an explicit ORDER BY the updated (oldest) project would jump to
    the end and every later building could shift lots.
    """
    tenant_id = tenant_admin["tenant"].id
    base = datetime.now(timezone.utc) - timedelta(days=3)
    projects = [
        Project(
            id=new_id(), tenant_id=tenant_id, code=f"ORD{i}", name=f"n{i}",
            status=ProjectStatus.active.value, created_at=base + timedelta(hours=i),
        )
        for i in range(4)
    ]
    db_session.add_all(projects)
    await db_session.commit()

    oldest = projects[0]
    oldest.name = "renamed"
    await db_session.commit()
    oldest.status = ProjectStatus.archived.value
    await db_session.commit()
    oldest.status = ProjectStatus.active.value
    await db_session.commit()

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(5):
        body = (await client.get("/api/v1/agent-rooms", headers=headers)).json()
        assert [p["code"] for p in body["projects"]] == ["ORD0", "ORD1", "ORD2", "ORD3"]


@pytest.mark.asyncio
async def test_projects_created_in_the_same_instant_tie_break_on_id(client, db_session, tenant_admin):
    tenant_id = tenant_admin["tenant"].id
    same_instant = datetime.now(timezone.utc) - timedelta(hours=1)
    ids_descending = sorted((new_id() for _ in range(5)), reverse=True)
    projects = [
        Project(
            id=project_id, tenant_id=tenant_id, code=f"TIE{i}", name="n",
            status=ProjectStatus.active.value, created_at=same_instant,
        )
        for i, project_id in enumerate(ids_descending)
    ]
    for project in projects:
        db_session.add(project)
        await db_session.flush()
    await db_session.commit()

    token = await _login(client, tenant_admin["admin"].email)
    headers = {"Authorization": f"Bearer {token}"}
    body = (await client.get("/api/v1/agent-rooms", headers=headers)).json()
    returned = [p["id"] for p in body["projects"]]
    assert returned == sorted(returned)
