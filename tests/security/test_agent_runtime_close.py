"""T2 acceptance tests 2, 3, 5 (HTTP half), 8, 9, 10, 11, 12 (test 1 -- the migration --
lives in `tests/integration/test_migration_0004b.py`; the concurrent halves of tests 4,
6 and 7 live in `tests/integration/test_agent_runtime_closure_concurrency.py`, since
they need real overlapping Postgres transactions or `FOR UPDATE SKIP LOCKED`, not a
shared `db_session`).

Drives the real FastAPI app end-to-end over HTTP, matching
`tests/security/test_agent_runtime.py`'s own precedent -- fixtures below are
deliberately copied rather than imported from that file (same discipline
`test_agent_runtime_concurrency.py` already uses), so this file stays independently
readable and never breaks if T1's fixtures change shape.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from common.db.models import (
    Agent,
    AgentRuntimeApiKey,
    AgentRuntimeClosure,
    AgentVersion,
    Artifact,
    AuditEvent,
    Mission,
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
from api.dependencies.auth import create_access_token, hash_password
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client
from api.routes.agent_rooms import _RESULT_HOLD_SECONDS

pytestmark = [pytest.mark.integration, pytest.mark.security]


class _NoopEventPublisher:
    async def publish(self, event, session) -> None:
        pass


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

    return {"tenant": tenant, "service_user": service_user, "key": key, "token": token, "claude_code": claude_code}


async def _make_admin(db_session, client, tenant_id, code: str) -> str:
    admin = User(
        id=new_id(), tenant_id=tenant_id, email=f"{code}-admin@test.local", display_name="Admin",
        role=UserRole.platform_admin.value, status=UserStatus.active.value,
        password_hash=hash_password("Test-Password-123!"),
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", data={"username": admin.email, "password": "Test-Password-123!"})
    return login.json()["access_token"]


async def _register_session(client, token: str, session_ref: str | None = None) -> dict:
    session_ref = session_ref or str(uuid.uuid4())
    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(token),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _register_subagent(client, token: str, session_ref: str, instance_ref: str) -> dict:
    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(token),
        json={
            "kind": "subagent", "agent_type": "planner",
            "external_instance_ref": instance_ref, "parent_external_session_ref": session_ref,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _close_payload(outcome="completed", reason_code="hook_reported", tool_call_count=None) -> dict:
    body = {"outcome": outcome, "reason_code": reason_code}
    if tool_call_count is not None:
        body["tool_call_count"] = tool_call_count
    return body


# ---------------------------------------------------------------------------
# Test 2 -- a close emits task.started then task.completed, one closure row,
# no artifact, Mission stays running.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_emits_task_started_then_task_completed_and_writes_one_closure_row(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "close-basic")
    session_ref = str(uuid.uuid4())
    session_row = await _register_session(client, ctx["token"], session_ref)
    subagent = await _register_subagent(client, ctx["token"], session_ref, "inst-close-1")

    response = await client.post(
        f"/api/v1/agent-runtime/subagents/inst-close-1/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["closed_by"] == "hook"
    assert body["outcome"] == "completed"
    assert body["artifact_id"] is None

    task = await db_session.get(Task, uuid.UUID(subagent["task_id"]))
    assert task.status == "completed"

    mission = await db_session.get(Mission, uuid.UUID(session_row["mission_id"]))
    assert mission.status == "running"  # T2-F5: the close path never touches the Mission

    closures = (
        await db_session.execute(
            select(AgentRuntimeClosure).where(AgentRuntimeClosure.task_id == uuid.UUID(subagent["task_id"]))
        )
    ).scalars().all()
    assert len(closures) == 1

    artifacts = (
        await db_session.execute(select(Artifact).where(Artifact.task_id == uuid.UUID(subagent["task_id"])))
    ).scalars().all()
    assert artifacts == []

    events = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.task_id == uuid.UUID(subagent["task_id"]))
            .order_by(AuditEvent.occurred_at.asc())
        )
    ).scalars().all()
    event_types = [e.event_type for e in events]
    assert event_types.index("task.started") < event_types.index("task.completed")


@pytest.mark.asyncio
async def test_close_by_session_id_path_also_works_and_a_failed_outcome_fails_the_task(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "close-by-id")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx["token"], session_ref)
    subagent = await _register_subagent(client, ctx["token"], session_ref, "inst-close-2")

    response = await client.post(
        f"/api/v1/agent-runtime/sessions/{subagent['id']}/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(outcome="failed", tool_call_count=5),
    )

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "failed"
    task = await db_session.get(Task, uuid.UUID(subagent["task_id"]))
    assert task.status == "failed"


# ---------------------------------------------------------------------------
# Test 3 -- output_text/reason/extra field is 422; tool_call_count out of range is 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_body",
    [
        {"output_text": "some output"},
        {"reason": "it broke"},
        {"some_other_field": "x"},
    ],
)
async def test_a_close_body_carrying_output_text_reason_or_an_extra_field_is_422(client, db_session, extra_body):
    ctx = await _make_tenant_with_runtime_key(db_session, f"close-422-{uuid.uuid4().hex[:8]}")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx["token"], session_ref)
    subagent = await _register_subagent(client, ctx["token"], session_ref, "inst-422")

    payload = {**_close_payload(), **extra_body}
    response = await client.post(
        f"/api/v1/agent-runtime/subagents/inst-422/close", headers=_auth_headers(ctx["token"]), json=payload
    )

    assert response.status_code == 422, response.text
    task = await db_session.get(Task, uuid.UUID(subagent["task_id"]))
    assert task.status == "queued"  # the rejected body never touched the Task


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_call_count", [-1, 10001])
async def test_tool_call_count_outside_0_to_10000_is_422(client, db_session, tool_call_count):
    ctx = await _make_tenant_with_runtime_key(db_session, f"close-tcc-{uuid.uuid4().hex[:8]}")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx["token"], session_ref)
    await _register_subagent(client, ctx["token"], session_ref, "inst-tcc")

    response = await client.post(
        "/api/v1/agent-runtime/subagents/inst-tcc/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(tool_call_count=tool_call_count),
    )

    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Test 5 -- cross-tenant close is 404; an unknown ref is 404; the agent-runtime key
# still gets 403 on tasks.py routes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_close_is_404(client, db_session):
    ctx_a = await _make_tenant_with_runtime_key(db_session, "close-cross-a")
    ctx_b = await _make_tenant_with_runtime_key(db_session, "close-cross-b")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx_a["token"], session_ref)
    subagent = await _register_subagent(client, ctx_a["token"], session_ref, "inst-cross-1")

    by_ref = await client.post(
        "/api/v1/agent-runtime/subagents/inst-cross-1/close", headers=_auth_headers(ctx_b["token"]),
        json=_close_payload(),
    )
    by_id = await client.post(
        f"/api/v1/agent-runtime/sessions/{subagent['id']}/close", headers=_auth_headers(ctx_b["token"]),
        json=_close_payload(),
    )

    assert by_ref.status_code == 404
    assert by_id.status_code == 404
    task = await db_session.get(Task, uuid.UUID(subagent["task_id"]))
    assert task.status == "queued"  # untouched by the wrong-tenant attempt


@pytest.mark.asyncio
async def test_closing_an_unknown_ref_is_404(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "close-unknown-ref")

    response = await client.post(
        "/api/v1/agent-runtime/subagents/no-such-ref/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_closing_a_session_kind_row_by_id_is_409_not_404(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "close-wrong-kind")
    session_row = await _register_session(client, ctx["token"])

    response = await client.post(
        f"/api/v1/agent-runtime/sessions/{session_row['id']}/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(),
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_agent_runtime_key_still_gets_403_on_tasks_routes(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "close-tasks-403")
    from common.config import get_settings

    settings = get_settings()
    jwt = create_access_token(
        user_id=ctx["service_user"].id, tenant_id=ctx["tenant"].id, role=UserRole.agent_runtime.value,
        settings=settings,
    )
    fake_id = uuid.uuid4()

    retry = await client.post(f"/api/v1/tasks/{fake_id}/retry", headers=_auth_headers(jwt))
    complete = await client.post(f"/api/v1/tasks/{fake_id}/complete-external", headers=_auth_headers(jwt), json={"output_text": "{}"})
    fail = await client.post(f"/api/v1/tasks/{fake_id}/fail-external", headers=_auth_headers(jwt), json={"reason": "x"})

    assert retry.status_code == 403
    assert complete.status_code == 403
    assert fail.status_code == 403


# ---------------------------------------------------------------------------
# Test 9 -- PATCH with an outcome on a subagent is 409; a session's end state
# cannot be overwritten.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_with_outcome_on_a_subagent_is_409(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "patch-subagent-409")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx["token"], session_ref)
    subagent = await _register_subagent(client, ctx["token"], session_ref, "inst-patch-409")

    response = await client.patch(
        f"/api/v1/agent-runtime/sessions/{subagent['id']}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "completed"},
    )

    assert response.status_code == 409
    task = await db_session.get(Task, uuid.UUID(subagent["task_id"]))
    assert task.status == "queued"


@pytest.mark.asyncio
async def test_a_sessions_end_state_is_set_once_and_a_second_patch_changes_nothing(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "patch-session-once")
    session_row = await _register_session(client, ctx["token"])

    first = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_row['id']}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "completed"},
    )
    assert first.status_code == 200, first.text
    first_ended_at = first.json()["ended_at"]

    second = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_row['id']}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "failed"},
    )

    assert second.status_code == 200
    assert second.json()["ended_at"] == first_ended_at
    assert second.json()["outcome"] == "completed"  # the first outcome, never overwritten


# ---------------------------------------------------------------------------
# Test 8 -- SessionEnd closes the parent Task, fails open subagents with
# session_ended, and completes the Mission; a second SessionEnd changes nothing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_end_completes_parent_fails_open_subagents_and_completes_mission(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "session-end")
    session_ref = str(uuid.uuid4())
    session_row = await _register_session(client, ctx["token"], session_ref)
    still_open = await _register_subagent(client, ctx["token"], session_ref, "inst-open-1")
    already_closed = await _register_subagent(client, ctx["token"], session_ref, "inst-closed-1")
    await client.post(
        "/api/v1/agent-runtime/subagents/inst-closed-1/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(),
    )

    response = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_row['id']}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "completed"},
    )
    assert response.status_code == 200, response.text

    parent_task = await db_session.get(Task, uuid.UUID(session_row["task_id"]))
    assert parent_task.status == "completed"

    open_task = await db_session.get(Task, uuid.UUID(still_open["task_id"]))
    assert open_task.status == "failed"
    open_closure = (
        await db_session.execute(
            select(AgentRuntimeClosure).where(AgentRuntimeClosure.task_id == uuid.UUID(still_open["task_id"]))
        )
    ).scalar_one()
    assert open_closure.closed_by == "session_end"
    assert open_closure.reason_code == "session_ended"

    already_closed_task = await db_session.get(Task, uuid.UUID(already_closed["task_id"]))
    assert already_closed_task.status == "completed"  # untouched -- it was already closed by the hook

    mission = await db_session.get(Mission, uuid.UUID(session_row["mission_id"]))
    assert mission.status == "completed"

    # A second SessionEnd changes nothing.
    second = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_row['id']}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "failed"},
    )
    assert second.status_code == 200
    await db_session.refresh(mission)
    assert mission.status == "completed"
    assert second.json()["outcome"] == "completed"


# ---------------------------------------------------------------------------
# Test 10 -- every audit_events.payload this phase writes is ids/timestamps/enums only
# ---------------------------------------------------------------------------


_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")
_KNOWN_STRINGS = {
    "user", "agent", "system", "1.0", "dev", "api", "worker",
    "hook", "session_end", "reaper", "completed", "failed",
    "hook_reported", "session_ended", "reaped_stale",
}


def _assert_only_ids_timestamps_and_enums(value, path="$"):
    import datetime as _dt

    if isinstance(value, dict):
        for k, v in value.items():
            _assert_only_ids_timestamps_and_enums(v, f"{path}.{k}")
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            _assert_only_ids_timestamps_and_enums(v, f"{path}[{i}]")
        return
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return
    if isinstance(value, str):
        if _UUID_RE.match(value):
            return
        if value in _KNOWN_STRINGS:
            return
        try:
            _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return
        except ValueError:
            pass
        if re.match(r"^[a-z_]+(\.[a-z_]+)+$", value):
            return
        raise AssertionError(f"Free-text-looking value at {path}: {value!r}")
    raise AssertionError(f"Unexpected type at {path}: {type(value)}")


@pytest.mark.asyncio
async def test_every_audit_payload_this_phase_writes_is_ids_timestamps_and_enums_only(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "close-exposure")
    session_ref = str(uuid.uuid4())
    session_row = await _register_session(client, ctx["token"], session_ref)
    await _register_subagent(client, ctx["token"], session_ref, "inst-exposure-close")
    await client.post(
        "/api/v1/agent-runtime/subagents/inst-exposure-close/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(outcome="failed", reason_code="hook_reported"),
    )
    await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_row['id']}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "completed"},
    )

    events = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.tenant_id == ctx["tenant"].id))
    ).scalars().all()
    assert len(events) >= 4
    for event in events:
        _assert_only_ids_timestamps_and_enums(event.payload)


# ---------------------------------------------------------------------------
# Test 11 -- the hook-loss function/endpoint returns the documented ratio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_loss_rate_endpoint_computes_the_documented_ratio(client, db_session):
    from api.services.agent_runtime_closure import compute_hook_loss_rate

    ctx = await _make_tenant_with_runtime_key(db_session, "hook-loss")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx["token"], session_ref)

    # hook, session_end and reaper closures, plus one late-closed (reaper + late_close_at set).
    for i, (closed_by, outcome, reason, late) in enumerate(
        [
            ("hook", "completed", "hook_reported", None),
            ("hook", "completed", "hook_reported", None),
            ("reaper", "failed", "reaped_stale", None),  # lost
            ("reaper", "failed", "reaped_stale", datetime.now(timezone.utc)),  # late-closed -- not lost
        ]
    ):
        sub = await _register_subagent(client, ctx["token"], session_ref, f"inst-loss-{i}")
        row = AgentRuntimeClosure(
            id=new_id(), tenant_id=ctx["tenant"].id, runtime_session_id=uuid.UUID(sub["id"]),
            task_id=uuid.UUID(sub["task_id"]), closed_by=closed_by, outcome=outcome, reason_code=reason,
            late_close_at=late,
        )
        db_session.add(row)
    await db_session.commit()

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await compute_hook_loss_rate(db_session, ctx["tenant"].id, since=since)
    assert result.total == 4
    assert result.lost == 1
    assert result.rate == pytest.approx(0.25)

    admin_token = await _make_admin(db_session, client, ctx["tenant"].id, "hook-loss")
    response = await client.get(
        "/api/v1/audit/agent-runtime-hook-loss-rate", headers=_auth_headers(admin_token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 4
    assert response.json()["lost"] == 1
    assert response.json()["rate"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_hook_loss_rate_endpoint_is_403_for_the_agent_runtime_credential(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "hook-loss-403")
    from common.config import get_settings

    jwt = create_access_token(
        user_id=ctx["service_user"].id, tenant_id=ctx["tenant"].id, role=UserRole.agent_runtime.value,
        settings=get_settings(),
    )

    response = await client.get(
        "/api/v1/audit/agent-runtime-hook-loss-rate", headers=_auth_headers(jwt)
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test 12 -- after the result hold, GET /agent-rooms shows the closed twins idle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_rooms_shows_closed_twins_idle_after_the_result_hold(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "world-read")
    session_ref = str(uuid.uuid4())
    await _register_session(client, ctx["token"], session_ref)
    subagent = await _register_subagent(client, ctx["token"], session_ref, "inst-world-1")
    await client.post(
        "/api/v1/agent-runtime/subagents/inst-world-1/close", headers=_auth_headers(ctx["token"]),
        json=_close_payload(),
    )

    task = await db_session.get(Task, uuid.UUID(subagent["task_id"]))
    task.completed_at = datetime.now(timezone.utc) - timedelta(seconds=_RESULT_HOLD_SECONDS + 1)
    await db_session.commit()

    admin_token = await _make_admin(db_session, client, ctx["tenant"].id, "world-read")
    response = await client.get("/api/v1/agent-rooms", headers=_auth_headers(admin_token))

    assert response.status_code == 200, response.text
    rooms = {r["agent_id"]: r for r in response.json()["rooms"]}
    twin_room = rooms[subagent["agent_id"]]
    assert twin_room["activity"] == "idle"
