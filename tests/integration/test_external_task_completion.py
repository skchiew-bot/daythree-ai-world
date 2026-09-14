"""The "self-reported completion" path for an externally-executed agent (e.g. a
Claude Code session) — see services/api/routes/tasks.py::complete_task_external /
fail_task_external, and infrastructure/scripts/seed.py's Claude Code agent. Drives
the real FastAPI app end-to-end over HTTP, same as tests/security/test_authz.py.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from common.db.models import Agent, AgentVersion, ModelPolicy, Tenant, User
from contracts.enums import AgentLifecycleState, AutonomyLevel, UserRole, UserStatus
from contracts.ids import new_id
from contracts.policy import ToolPolicy
from event_service.publisher import EventPublisher

from api.app.main import app
from api.dependencies.auth import hash_password
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client

from mission_engine.engine.queue import TASK_QUEUE_KEY

pytestmark = pytest.mark.integration

PASSWORD = "Test-Password-123!"


class _InMemoryObjectStore:
    """Local stand-in for MinIO, mirroring tests/conftest.py's NullObjectStore —
    kept local rather than imported since `tests/` isn't a regular importable
    package (no __init__.py)."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}

    async def put_object(self, key: str, body: bytes, content_type: str) -> str:
        self._objects[key] = body
        return f"s3://test-bucket/{key}"

    async def get_object(self, key: str) -> bytes:
        return self._objects[key]

    async def generate_presigned_download_url(self, key: str) -> str:
        return f"http://fake-signed-url/{key}"


VALID_OUTPUT = json.dumps(
    {
        "title": "Externally-completed test mission",
        "executive_summary": "Done outside Daythree, reported back.",
        "sections": [{"heading": "Result", "content": "It worked."}],
    }
)


@pytest.fixture
def object_store():
    return _InMemoryObjectStore()


@pytest.fixture
async def client(db_session, fake_redis, object_store):
    async def override_db():
        yield db_session

    # A real EventPublisher (not a no-op stub): this test suite asserts on the
    # audit_events it writes, unlike tests/security's authz tests which don't care.
    publisher = EventPublisher(redis_client=fake_redis)

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    app.dependency_overrides[get_object_store] = lambda: object_store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _make_agent(db_session, tenant_id, *, agent_code: str, runtime_adapter: str) -> Agent:
    policy = ModelPolicy(
        id=new_id(), tenant_id=tenant_id, name=f"policy-for-{agent_code}",
        primary_provider="mock", primary_model="mock",
    )
    db_session.add(policy)
    await db_session.flush()

    agent = Agent(
        id=new_id(), tenant_id=tenant_id, agent_code=agent_code, display_name=agent_code,
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(agent)
    await db_session.flush()

    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="x", runtime_adapter=runtime_adapter,
        model_policy_id=policy.id, autonomy_level=AutonomyLevel.a1.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.flush()
    agent.active_version_id = version.id
    await db_session.flush()
    return agent


@pytest.fixture
async def ext_seeded(db_session):
    tenant = Tenant(id=new_id(), code="ext-task-tenant", name="Ext Task Tenant")
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        id=new_id(), tenant_id=tenant.id, email="ext-task-admin@test.local", display_name="Admin",
        role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash=hash_password(PASSWORD),
    )
    db_session.add(admin)
    await db_session.flush()

    external_agent = await _make_agent(
        db_session, tenant.id, agent_code="AGT-EXT-TEST", runtime_adapter="external_manual"
    )
    internal_agent = await _make_agent(
        db_session, tenant.id, agent_code="AGT-INT-TEST", runtime_adapter="custom_durable"
    )
    await db_session.commit()

    return {"tenant": tenant, "admin": admin, "external_agent": external_agent, "internal_agent": internal_agent}


async def _create_and_start_mission(client, token, agent_id) -> str:
    create = await client.post(
        "/api/v1/missions", headers={"Authorization": f"Bearer {token}"},
        json={"title": "Ext test mission", "objective": "x", "assigned_agent_id": str(agent_id)},
    )
    assert create.status_code == 201, create.text
    mission_id = create.json()["id"]

    start = await client.post(
        f"/api/v1/missions/{mission_id}/start", headers={"Authorization": f"Bearer {token}"}
    )
    assert start.status_code == 200, start.text
    return mission_id


@pytest.mark.asyncio
async def test_starting_a_mission_for_an_external_agent_does_not_enqueue_to_redis(client, ext_seeded, fake_redis):
    token = await _login(client, ext_seeded["admin"].email)
    await _create_and_start_mission(client, token, ext_seeded["external_agent"].id)
    assert await fake_redis.llen(TASK_QUEUE_KEY) == 0


@pytest.mark.asyncio
async def test_starting_a_mission_for_an_internal_agent_does_enqueue_to_redis(client, ext_seeded, fake_redis):
    token = await _login(client, ext_seeded["admin"].email)
    await _create_and_start_mission(client, token, ext_seeded["internal_agent"].id)
    assert await fake_redis.llen(TASK_QUEUE_KEY) == 1


@pytest.mark.asyncio
async def test_complete_external_produces_a_real_artifact_and_completes_the_mission(client, ext_seeded, db_session):
    token = await _login(client, ext_seeded["admin"].email)
    mission_id = await _create_and_start_mission(client, token, ext_seeded["external_agent"].id)

    tasks_resp = await client.get(
        f"/api/v1/missions/{mission_id}/tasks", headers={"Authorization": f"Bearer {token}"}
    )
    task_id = tasks_resp.json()[0]["id"]

    complete = await client.post(
        f"/api/v1/tasks/{task_id}/complete-external", headers={"Authorization": f"Bearer {token}"},
        json={"output_text": VALID_OUTPUT},
    )
    assert complete.status_code == 200, complete.text
    body = complete.json()
    assert body["status"] == "completed"
    assert body["output_artifact_id"] is not None

    mission = await client.get(f"/api/v1/missions/{mission_id}", headers={"Authorization": f"Bearer {token}"})
    assert mission.json()["status"] == "completed"

    timeline = await client.get(
        f"/api/v1/missions/{mission_id}/timeline", headers={"Authorization": f"Bearer {token}"}
    )
    event_types = [e["event_type"] for e in timeline.json()]
    assert event_types == [
        "mission.created", "mission.started", "task.created", "task.assigned",
        "task.started", "artifact.created", "task.completed", "mission.completed",
    ]


@pytest.mark.asyncio
async def test_complete_external_rejects_invalid_output(client, ext_seeded):
    token = await _login(client, ext_seeded["admin"].email)
    mission_id = await _create_and_start_mission(client, token, ext_seeded["external_agent"].id)
    tasks_resp = await client.get(
        f"/api/v1/missions/{mission_id}/tasks", headers={"Authorization": f"Bearer {token}"}
    )
    task_id = tasks_resp.json()[0]["id"]

    complete = await client.post(
        f"/api/v1/tasks/{task_id}/complete-external", headers={"Authorization": f"Bearer {token}"},
        json={"output_text": "not json"},
    )
    assert complete.status_code == 422


@pytest.mark.asyncio
async def test_complete_external_refuses_a_task_owned_by_the_internal_worker(client, ext_seeded):
    token = await _login(client, ext_seeded["admin"].email)
    mission_id = await _create_and_start_mission(client, token, ext_seeded["internal_agent"].id)
    tasks_resp = await client.get(
        f"/api/v1/missions/{mission_id}/tasks", headers={"Authorization": f"Bearer {token}"}
    )
    task_id = tasks_resp.json()[0]["id"]

    complete = await client.post(
        f"/api/v1/tasks/{task_id}/complete-external", headers={"Authorization": f"Bearer {token}"},
        json={"output_text": VALID_OUTPUT},
    )
    assert complete.status_code == 409


@pytest.mark.asyncio
async def test_fail_external_marks_task_and_mission_failed(client, ext_seeded):
    token = await _login(client, ext_seeded["admin"].email)
    mission_id = await _create_and_start_mission(client, token, ext_seeded["external_agent"].id)
    tasks_resp = await client.get(
        f"/api/v1/missions/{mission_id}/tasks", headers={"Authorization": f"Bearer {token}"}
    )
    task_id = tasks_resp.json()[0]["id"]

    failed = await client.post(
        f"/api/v1/tasks/{task_id}/fail-external", headers={"Authorization": f"Bearer {token}"},
        json={"reason": "could not complete the work"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"

    mission = await client.get(f"/api/v1/missions/{mission_id}", headers={"Authorization": f"Bearer {token}"})
    assert mission.json()["status"] == "failed"
