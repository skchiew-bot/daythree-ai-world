"""T3 deliverable 2 / T3-F2 (operator-approved): registering a NEW subagent under a
session whose `ended_at` is set is a 409 with the stable detail `parent_session_ended`;
an idempotent replay of an already-registered `external_instance_ref` still returns the
stored row (so a hook retry after the session ended never turns a success into a
failure). Nothing is created on the refused path: no Task, no runtime-session row, no
persona row.

Drives the real FastAPI app over HTTP with the same fixture shape as
`tests/security/test_agent_runtime_close.py` (deliberately copied, not imported, so this
file stays readable on its own and never breaks if another file's fixtures change).
"""
from __future__ import annotations

import secrets
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from common.db.models import (
    Agent,
    AgentRuntimeApiKey,
    AgentRuntimeSession,
    AgentVersion,
    ModelPolicy,
    Task,
    Tenant,
    User,
)
from common.hashing import sha256_hex
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

pytestmark = [pytest.mark.integration, pytest.mark.security]

_SESSIONS = "/api/v1/agent-runtime/sessions"


@pytest.fixture
async def client(db_session, fake_redis):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_event_publisher] = lambda: EventPublisher(redis_client=fake_redis)
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    app.dependency_overrides[get_object_store] = lambda: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_tenant_with_runtime_key(db_session, code: str) -> dict:
    tenant = Tenant(id=new_id(), code=code, name=code)
    db_session.add(tenant)
    await db_session.flush()

    model_policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="claude-code-external", primary_provider="claude-code",
        primary_model="claude-code-session", max_input_tokens=0, max_output_tokens=0,
        max_cost_per_task=0, timeout_seconds=0,
    )
    db_session.add(model_policy)

    service_user = User(
        id=new_id(), tenant_id=tenant.id, email=f"agent-runtime+{code}@daythree.local",
        display_name="Agent Runtime", role=UserRole.agent_runtime.value, status=UserStatus.active.value,
        password_hash=hash_password(secrets.token_urlsafe(24)),
    )
    db_session.add(service_user)
    await db_session.flush()

    secret = secrets.token_urlsafe(32)
    key = AgentRuntimeApiKey(id=new_id(), user_id=service_user.id, key_hash=sha256_hex(secret), label="test")
    db_session.add(key)
    await db_session.flush()
    token = f"dtk_{key.id.hex}_{secret}"

    claude_code = Agent(
        id=new_id(), tenant_id=tenant.id, agent_code="AGT-CLAUDE-CODE", display_name="Claude Code",
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(claude_code)
    await db_session.flush()
    version = AgentVersion(
        id=new_id(), agent_id=claude_code.id, version=1, system_prompt="x", runtime_adapter="external_manual",
        model_policy_id=model_policy.id, autonomy_level=AutonomyLevel.a3.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.flush()
    claude_code.active_version_id = version.id
    await db_session.commit()

    return {"tenant": tenant, "token": token}


async def _register_session(client, token: str) -> tuple[str, str]:
    ref = str(uuid.uuid4())
    response = await client.post(
        _SESSIONS, headers=_auth_headers(token), json={"kind": "session", "external_session_ref": ref}
    )
    assert response.status_code == 201, response.text
    return ref, response.json()["id"]


async def _end_session(client, token: str, runtime_id: str) -> None:
    response = await client.patch(
        f"{_SESSIONS}/{runtime_id}", headers=_auth_headers(token), json={"outcome": "completed"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["ended_at"] is not None


def _subagent(ref: str, parent_ref: str, agent_type: str = "planner") -> dict:
    return {
        "kind": "subagent", "agent_type": agent_type,
        "external_instance_ref": ref, "parent_external_session_ref": parent_ref,
    }


async def _count(db_session, model, *criteria) -> int:
    stmt = select(func.count()).select_from(model)
    for criterion in criteria:
        stmt = stmt.where(criterion)
    return (await db_session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_a_new_subagent_under_an_ended_session_is_409_parent_session_ended_and_creates_nothing(
    client, db_session
):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-ended-new")
    parent_ref, runtime_id = await _register_session(client, ctx["token"])
    await _end_session(client, ctx["token"], runtime_id)
    tasks_before = await _count(db_session, Task)
    agents_before = await _count(db_session, Agent, Agent.tenant_id == ctx["tenant"].id)

    response = await client.post(
        _SESSIONS, headers=_auth_headers(ctx["token"]), json=_subagent("a1b2c3d4e5f60718", parent_ref)
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "parent_session_ended"
    assert await _count(db_session, Task) == tasks_before
    assert await _count(db_session, Agent, Agent.tenant_id == ctx["tenant"].id) == agents_before
    assert await _count(
        db_session, AgentRuntimeSession, AgentRuntimeSession.external_instance_ref == "a1b2c3d4e5f60718"
    ) == 0


@pytest.mark.asyncio
async def test_a_replay_of_an_already_registered_ref_after_the_session_ended_returns_the_stored_row(
    client, db_session
):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-ended-replay")
    parent_ref, runtime_id = await _register_session(client, ctx["token"])
    first = await client.post(
        _SESSIONS, headers=_auth_headers(ctx["token"]), json=_subagent("0f1e2d3c4b5a6978", parent_ref)
    )
    assert first.status_code == 201, first.text
    await _end_session(client, ctx["token"], runtime_id)
    tasks_before = await _count(db_session, Task)

    replay = await client.post(
        _SESSIONS, headers=_auth_headers(ctx["token"]), json=_subagent("0f1e2d3c4b5a6978", parent_ref)
    )

    # The route's decorator fixes the success status at 201 for a replay as well (T1's
    # own idempotency tests assert 201 twice); what matters is that it is a success
    # returning the stored row, not the new 409.
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert await _count(db_session, Task) == tasks_before


@pytest.mark.asyncio
async def test_a_live_session_still_registers_subagents_normally(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-ended-live")
    parent_ref, _runtime_id = await _register_session(client, ctx["token"])

    response = await client.post(
        _SESSIONS, headers=_auth_headers(ctx["token"]), json=_subagent("11223344aabbccdd", parent_ref)
    )

    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "subagent"


@pytest.mark.asyncio
async def test_a_new_run_after_the_old_one_ended_registers_subagents_again(client, db_session):
    """The hook's recovery path (build plan deliverable 4): on 409 it mints a NEW run
    uuid, re-registers the session and retries the subagent once -- that must succeed
    on the server side, and the ended run stays ended."""
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-ended-recover")
    old_ref, old_runtime_id = await _register_session(client, ctx["token"])
    await _end_session(client, ctx["token"], old_runtime_id)
    refused = await client.post(
        _SESSIONS, headers=_auth_headers(ctx["token"]), json=_subagent("99887766ffeeddcc", old_ref)
    )
    assert refused.status_code == 409

    new_ref, _new_runtime_id = await _register_session(client, ctx["token"])
    retried = await client.post(
        _SESSIONS, headers=_auth_headers(ctx["token"]), json=_subagent("99887766ffeeddcc", new_ref)
    )

    assert retried.status_code == 201, retried.text
    assert retried.json()["external_session_ref"] == new_ref
