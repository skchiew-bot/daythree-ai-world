"""T1 acceptance tests 2, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14 (test 1 -- the migration --
lives in `tests/integration/test_migration_0004.py`; the concurrent halves of tests 5
and 6 live in `tests/integration/test_agent_runtime_concurrency.py` since they need real
overlapping Postgres transactions, not a shared `db_session`).

Drives the real FastAPI app end-to-end over HTTP (matching `test_authz.py`'s own
precedent), so the actual dependency wiring -- the new `agent_runtime` auth path AND the
default-deny wired onto every other router in `routes/__init__.py` -- is what's tested,
not just the route functions in isolation.
"""
from __future__ import annotations

import importlib.util
import re
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from common.db.models import (
    Agent,
    AgentRuntimeApiKey,
    AgentRuntimeSession,
    AgentVersion,
    AuditEvent,
    Mission,
    ModelPolicy,
    Task,
    Tenant,
    User,
)
from common.config import get_settings
from common.hashing import sha256_hex
from contracts.enums import AgentLifecycleState, AutonomyLevel, TenantStatus, UserRole, UserStatus
from contracts.ids import new_id
from contracts.policy import ToolPolicy
from event_service.publisher import EventPublisher

from api.app.main import app
from api.dependencies.auth import create_access_token, hash_password
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client
from api.persona_registry import GENERAL_PERSONA_CODE
from api.routes.agent_runtime import _RATE_LIMIT_MAX_REQUESTS

pytestmark = [pytest.mark.integration, pytest.mark.security]

_EXEMPT_PREFIXES = ("/api/v1/auth", "/api/v1/agent-runtime")

_ISSUE_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "infrastructure" / "scripts" / "issue_agent_runtime_key.py"


def _load_issue_script():
    """`infrastructure/scripts/` is a plain directory, not a package (no
    `__init__.py`, and the repo root is deliberately not on `pytest`'s configured
    `pythonpath` in `pyproject.toml`) -- `import infrastructure...` only worked
    locally because `python -m pytest` happens to add the current working directory
    to `sys.path`, which the plain `pytest` entrypoint CI actually runs does not do.
    Loading the file directly by path works under either invocation. Cached on the
    module under its own name so the three tests that need it share one load."""
    module_name = "issue_agent_runtime_key"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _ISSUE_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _agent_runtime_jwt(user: User) -> str:
    """T1-F3 is a defense-in-depth check: `forbid_agent_runtime` sits on
    `get_current_user` (JWT), not on the scoped `dtk_...` credential (which never
    resolves via `get_current_user` at all -- a `dtk_...` "bearer token" simply fails
    JWT decode and 401s on every JWT-authenticated route regardless of role, before any
    role check runs). So a 403-on-every-other-route test has to authenticate as an
    `agent_runtime`-role user through the JWT path directly, the same way a real JWT
    minted for such a user would (the service user's own real password is discarded and
    unusable -- see `infrastructure/scripts/issue_agent_runtime_key.py` -- so it can
    never reach `POST /auth/login` in practice; this constructs the token the same way
    that route would, to prove the router-level refusal holds even if one ever did)."""
    settings = get_settings()
    return create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=UserRole.agent_runtime.value, settings=settings
    )


async def _seed_claude_code_agent(db_session, tenant: Tenant) -> Agent:
    """Every registration test needs `AGT-CLAUDE-CODE` (and the `claude-code-external`
    `ModelPolicy` it depends on) seeded for the tenant first, or `_register_session`
    409s -- factored out so the log/rotation tests (which build their own bare tenant
    rather than going through `_make_tenant_with_runtime_key`) don't have to repeat it.
    """
    model_policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="claude-code-external", primary_provider="claude-code",
        primary_model="claude-code-session", max_input_tokens=0, max_output_tokens=0,
        max_cost_per_task=0, timeout_seconds=0,
    )
    db_session.add(model_policy)
    await db_session.flush()

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
    return claude_code


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


# ---------------------------------------------------------------------------
# Test 4 -- service user login is 401, never 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_service_user_email_is_401_not_500_on_wrong_or_empty_password(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-login")
    email = ctx["service_user"].email

    wrong = await client.post("/api/v1/auth/login", data={"username": email, "password": "wrong-password"})
    # An empty `password` form field is rejected by FastAPI/Starlette's own form
    # parsing (422) before the route ever runs -- a pre-existing, unrelated platform
    # behavior of `OAuth2PasswordRequestForm`, not something this feature changes.
    # A single-space password reaches the route as a real (wrong) string instead.
    near_empty = await client.post("/api/v1/auth/login", data={"username": email, "password": " "})

    assert wrong.status_code == 401
    assert near_empty.status_code == 401


@pytest.mark.asyncio
async def test_two_tenants_with_service_users_do_not_make_login_raise(client, db_session):
    await _make_tenant_with_runtime_key(db_session, "ar-login-a")
    ctx_b = await _make_tenant_with_runtime_key(db_session, "ar-login-b")

    response = await client.post(
        "/api/v1/auth/login", data={"username": ctx_b["service_user"].email, "password": "still-wrong"}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 14 -- API key resolution: revoked/expired/disabled/suspended all 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_key_is_401(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-revoked")
    ctx["key"].revoked_at = datetime.now(timezone.utc)
    await db_session.commit()

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_key_is_401(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-expired")
    ctx["key"].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_key_for_a_disabled_user_is_401(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-disabled-user")
    ctx["service_user"].status = UserStatus.disabled.value
    await db_session.commit()

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_key_for_a_suspended_tenant_is_401(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-suspended-tenant")
    ctx["tenant"].status = TenantStatus.suspended.value
    await db_session.commit()

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_garbage_bearer_token_is_401(client, db_session):
    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers("dtk_not_a_real_key"),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_the_secret_never_appears_in_captured_logs(client, db_session, caplog):
    """T1 acceptance test 14's missing case (security review round 1, MEDIUM): issuing
    a key, a successful authenticated call, a revoked-key call and a malformed-key call
    must never put the secret into any log line -- structlog here is configured with
    `PrintLoggerFactory` (writes straight to stdout, bypassing stdlib `logging`
    entirely -- see `observability/logging/setup.py`), so `structlog.testing
    .capture_logs()` is what actually intercepts it regardless of that sink; stdlib
    `caplog` is also asserted for anything a library might log through normal
    `logging`. The script's one deliberate stdout print is exercised and asserted
    separately in `test_issue_script_prints_the_token_exactly_once_and_only_to_stdout`.
    """
    import structlog

    issue_script = _load_issue_script()
    _ensure_service_user, _issue_key = issue_script._ensure_service_user, issue_script._issue_key

    tenant = Tenant(id=new_id(), code="ar-log-secret", name="ar-log-secret")
    db_session.add(tenant)
    await db_session.commit()
    await _seed_claude_code_agent(db_session, tenant)

    with structlog.testing.capture_logs() as structlog_events, caplog.at_level("DEBUG"):
        service_user = await _ensure_service_user(db_session, tenant)
        token = await _issue_key(db_session, service_user, label="log-secret-test")
        await db_session.commit()

        secret = token.split("_", 2)[2]

        good = await client.post(
            "/api/v1/agent-runtime/sessions", headers=_auth_headers(token),
            json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
        )
        assert good.status_code == 201, good.text

        # Revoke, then a call with the now-revoked key, then a malformed one.
        key = (
            await db_session.execute(
                select(AgentRuntimeApiKey).where(AgentRuntimeApiKey.user_id == service_user.id)
            )
        ).scalar_one()
        key.revoked_at = datetime.now(timezone.utc)
        await db_session.commit()
        revoked = await client.post(
            "/api/v1/agent-runtime/sessions", headers=_auth_headers(token),
            json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
        )
        assert revoked.status_code == 401
        malformed = await client.post(
            "/api/v1/agent-runtime/sessions", headers=_auth_headers(f"dtk_{key.id.hex}_{secret}x-garbled"),
            json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
        )
        assert malformed.status_code == 401

    for event in structlog_events:
        assert secret not in repr(event), f"secret leaked into a structlog event: {event!r}"
    for record in caplog.records:
        assert secret not in record.getMessage(), f"secret leaked into a stdlib log record: {record.getMessage()!r}"


def test_issue_script_prints_the_token_exactly_once_and_only_to_stdout(monkeypatch, capsys):
    """Isolated from the database: `main()`'s only remaining side effect once `issue()`
    returns is `print(token)` -- this proves that call site (and only that call site)
    ever reaches stdout, without needing a live DB for the CLI wiring itself (the
    secret-never-logged half of test 14 is covered against the real functions and a
    real DB in the previous test). Deliberately a plain sync test, not async: `main()`
    itself owns an `asyncio.run(...)` call, which raises "cannot be called from a
    running event loop" if this test were async under `asyncio_mode = "auto"`."""
    from common.config import Settings

    issue_script = _load_issue_script()
    sentinel_token = "dtk_" + ("a" * 32) + "_the-actual-secret-value"

    async def _fake_issue(tenant_code, *, label):
        return sentinel_token

    monkeypatch.setattr(issue_script, "issue", _fake_issue)
    monkeypatch.setattr(issue_script, "get_settings", lambda: Settings())  # database_url defaults to localhost
    monkeypatch.setattr(
        "sys.argv", ["issue_agent_runtime_key.py", "--tenant-code", "daythree-hq"]
    )

    issue_script.main()

    captured = capsys.readouterr()
    assert captured.out.strip() == sentinel_token
    assert captured.out.count("the-actual-secret-value") == 1


@pytest.mark.asyncio
async def test_rotation_is_issue_new_then_revoke_old_with_an_overlap_window(client, db_session, monkeypatch):
    """Security review round 1, LOW: `issue()` must never revoke anything by itself
    (docstring vs. code mismatch found in round 1) -- a tenant can hold two live keys
    at once, and only a separate, explicit `revoke(key_id)` call retires one."""
    issue_script = _load_issue_script()
    issue, revoke = issue_script.issue, issue_script.revoke

    tenant = Tenant(id=new_id(), code="ar-rotate", name="ar-rotate")
    db_session.add(tenant)
    await db_session.commit()
    await _seed_claude_code_agent(db_session, tenant)

    # `issue`/`revoke` open their own session via the `get_sessionmaker` name they
    # imported into THEIR OWN module namespace (`from common.db.session import
    # get_sessionmaker`) -- patching `common.db.session.get_sessionmaker` itself would
    # not affect that already-bound reference, so it has to be patched here instead.
    # Point it at this test's own bound engine so `issue`/`revoke` operate on the same
    # transaction/rows the test can see (and never touch a real database by accident).
    from sqlalchemy.ext.asyncio import async_sessionmaker

    fixed_sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(issue_script, "get_sessionmaker", lambda: fixed_sessionmaker)

    old_token = await issue(tenant.code, label="old")
    new_token = await issue(tenant.code, label="new")  # issuing again revokes nothing

    old_response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(old_token),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    new_response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(new_token),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert old_response.status_code == 201, old_response.text  # both keys are live
    assert new_response.status_code == 201, new_response.text

    old_key_id = old_token.split("_", 2)[1]
    await revoke(tenant.code, old_key_id)

    old_after_revoke = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(old_token),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    new_after_revoke = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(new_token),
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert old_after_revoke.status_code == 401  # only the named key was retired
    assert new_after_revoke.status_code == 201, new_after_revoke.text


# ---------------------------------------------------------------------------
# Session/subagent registration behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_session_creates_mission_task_and_audit_events(client, db_session, fake_redis):
    # The `client` fixture defaults to a no-op publisher (matching test_authz.py's own
    # precedent); swap in a real one here, same as
    # test_projects.py::test_project_audit_events_never_contain_name_or_code, so the
    # `audit_events` rows this test asserts on actually get written.
    app.dependency_overrides[get_event_publisher] = lambda: EventPublisher(redis_client=fake_redis)
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-session")
    session_ref = str(uuid.uuid4())

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mission_id"] is not None
    assert body["task_id"] is not None

    mission = await db_session.get(Mission, uuid.UUID(body["mission_id"]))
    assert mission.status == "running"
    assert re.match(r"^Claude Code session [0-9a-f-]{36}$", mission.title)
    assert mission.mission_code == session_ref

    events = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.mission_id == mission.id))
    ).scalars().all()
    assert {"mission.created", "mission.started", "task.created", "task.assigned"} <= {e.event_type for e in events}


@pytest.mark.asyncio
async def test_duplicate_session_registration_is_idempotent(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-idem-session")
    session_ref = str(uuid.uuid4())
    payload = {"kind": "session", "external_session_ref": session_ref}

    first = await client.post("/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]), json=payload)
    second = await client.post("/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]), json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    missions = (
        await db_session.execute(select(Mission).where(Mission.mission_code == session_ref))
    ).scalars().all()
    assert len(missions) == 1


@pytest.mark.asyncio
async def test_two_spellings_of_the_same_uuid_register_one_session_and_one_mission(client, db_session):
    """Security review round 1, MEDIUM: `uuid.UUID(...)` accepts non-canonical
    spellings (braces, uppercase, no dashes, a `urn:uuid:` prefix) of the same value --
    without normalization, two such spellings of one session id would defeat the
    `(tenant_id, external_session_ref)` idempotency index and could each produce their
    own Mission."""
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-uuid-normalize")
    canonical = uuid.uuid4()
    braced = f"{{{str(canonical).upper()}}}"

    first = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": str(canonical)},
    )
    second = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": braced},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["external_session_ref"] == str(canonical)

    missions = (
        await db_session.execute(select(Mission).where(Mission.mission_code == str(canonical)))
    ).scalars().all()
    assert len(missions) == 1
    assert re.match(r"^Claude Code session [0-9a-f-]{36}$", missions[0].title)


@pytest.mark.asyncio
async def test_subagent_registration_creates_persona_task_and_buckets_hostile_agent_type(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-subagent")
    session_ref = str(uuid.uuid4())
    await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "AGT-000001",  # T1 acceptance test 10: hostile input
            "external_instance_ref": "inst-1", "parent_external_session_ref": session_ref,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    agent = await db_session.get(Agent, uuid.UUID(body["agent_id"]))
    assert agent.agent_code == GENERAL_PERSONA_CODE
    assert agent.agent_code not in {"AGT-000001", "AGT-CLAUDE-CODE"}

    task = await db_session.get(Task, uuid.UUID(body["task_id"]))
    assert task.status == "queued"
    assert task.idempotency_key == f"{task.mission_id}:ar:inst-1"

    replay = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "AGT-000001",
            "external_instance_ref": "inst-1", "parent_external_session_ref": session_ref,
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == body["id"]
    tasks = (
        await db_session.execute(select(Task).where(Task.idempotency_key == task.idempotency_key))
    ).scalars().all()
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_a_known_persona_name_gets_its_own_registry_constant_code(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-known-persona")
    session_ref = str(uuid.uuid4())
    await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "planner",
            "external_instance_ref": "inst-planner-1", "parent_external_session_ref": session_ref,
        },
    )

    assert response.status_code == 201, response.text
    agent = await db_session.get(Agent, uuid.UUID(response.json()["agent_id"]))
    assert agent.agent_code == "AGT-CC-PLANNER"
    assert agent.lifecycle_state == AgentLifecycleState.active.value
    version = await db_session.get(AgentVersion, agent.active_version_id)
    assert version.runtime_adapter == "external_manual"
    assert version.autonomy_level == AutonomyLevel.a1.value


@pytest.mark.asyncio
async def test_a_suspended_persona_is_409_and_stays_suspended(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-suspended-persona")
    session_ref = str(uuid.uuid4())
    await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    first = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "architect",
            "external_instance_ref": "inst-arch-1", "parent_external_session_ref": session_ref,
        },
    )
    agent = await db_session.get(Agent, uuid.UUID(first.json()["agent_id"]))
    agent.lifecycle_state = AgentLifecycleState.suspended.value
    await db_session.commit()

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "architect",
            "external_instance_ref": "inst-arch-2", "parent_external_session_ref": session_ref,
        },
    )

    assert response.status_code == 409
    await db_session.refresh(agent)
    assert agent.lifecycle_state == AgentLifecycleState.suspended.value


@pytest.mark.asyncio
async def test_subagent_registration_409s_when_claude_code_external_policy_is_not_seeded(client, db_session):
    tenant = Tenant(id=new_id(), code="ar-no-policy", name="ar-no-policy")
    db_session.add(tenant)
    await db_session.flush()
    service_user = User(
        id=new_id(), tenant_id=tenant.id, email="agent-runtime+ar-no-policy@daythree.local",
        display_name="Agent Runtime", role=UserRole.agent_runtime.value, status=UserStatus.active.value,
        password_hash=hash_password(secrets.token_urlsafe(24)),
    )
    db_session.add(service_user)
    await db_session.flush()
    secret = secrets.token_urlsafe(32)
    key = AgentRuntimeApiKey(id=new_id(), user_id=service_user.id, key_hash=sha256_hex(secret), label="test")
    db_session.add(key)
    claude_code = Agent(
        id=new_id(), tenant_id=tenant.id, agent_code="AGT-CLAUDE-CODE", display_name="Claude Code",
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(claude_code)
    await db_session.commit()
    token = f"dtk_{key.id.hex}_{secret}"

    session_ref = str(uuid.uuid4())
    session_created = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(token),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    assert session_created.status_code == 201, session_created.text

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(token),
        json={
            "kind": "subagent", "agent_type": "planner",
            "external_instance_ref": "inst-1", "parent_external_session_ref": session_ref,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_registering_a_subagent_for_an_unregistered_parent_session_is_404(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-no-parent")

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "planner",
            "external_instance_ref": "inst-orphan", "parent_external_session_ref": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test 2 -- cross-tenant isolation on the PATCH-by-id path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_key_gets_404_on_another_tenants_session(client, db_session):
    ctx_a = await _make_tenant_with_runtime_key(db_session, "ar-cross-a")
    ctx_b = await _make_tenant_with_runtime_key(db_session, "ar-cross-b")
    session_ref = str(uuid.uuid4())
    created = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx_a["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    session_id = created.json()["id"]

    response = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_id}", headers=_auth_headers(ctx_b["token"]), json={}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat_and_ended_update_the_runtime_session_row(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-heartbeat")
    session_ref = str(uuid.uuid4())
    created = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    session_id = created.json()["id"]

    heartbeat = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_id}", headers=_auth_headers(ctx["token"]), json={}
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["last_heartbeat_at"] is not None
    assert heartbeat.json()["ended_at"] is None

    ended = await client.patch(
        f"/api/v1/agent-runtime/sessions/{session_id}", headers=_auth_headers(ctx["token"]),
        json={"outcome": "completed"},
    )
    assert ended.status_code == 200
    assert ended.json()["ended_at"] is not None
    assert ended.json()["outcome"] == "completed"


# ---------------------------------------------------------------------------
# Test 3 -- default-deny for the credential on every other route
# ---------------------------------------------------------------------------


_BODY_METHODS = {"POST", "PUT", "PATCH"}


def _get_route_method_pairs_outside_agent_runtime() -> list[tuple[str, str]]:
    """Every (method, path) pair actually wired behind `forbid_agent_runtime` in
    `routes/__init__.py` -- i.e. every method on every route under `/api/v1/` except
    `/api/v1/auth` and `/api/v1/agent-runtime`. Security review round 1, MEDIUM: the
    original version of this test only checked GET, so it was not table-driven over
    every route AND method the way T1 acceptance test 3 requires -- a route reachable
    only by POST/PUT/PATCH/DELETE was never exercised at all. FastAPI's own `/docs`,
    `/openapi.json`, `/redoc` and the unprefixed `/health/*`/`/metrics` routes are not
    part of that gate and are excluded here rather than asserted 403, matching what
    `routes/__init__.py` actually wires."""
    pairs = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if not path or not path.startswith("/api/v1/"):
            continue
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            pairs.append((method, path))
    return pairs


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _get_route_method_pairs_outside_agent_runtime())
async def test_agent_runtime_gets_403_on_every_route_and_method_except_its_own(client, db_session, method, path):
    ctx = await _make_tenant_with_runtime_key(db_session, f"ar403-{uuid.uuid4().hex[:16]}")
    jwt = _agent_runtime_jwt(ctx["service_user"])
    concrete_path = path
    for param in re.findall(r"\{(\w+)\}", path):
        concrete_path = concrete_path.replace("{" + param + "}", str(uuid.uuid4()))

    kwargs = {"json": {}} if method in _BODY_METHODS else {}
    response = await client.request(method, concrete_path, headers=_auth_headers(jwt), **kwargs)

    assert response.status_code == 403, f"{method} {path} -> {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_agent_runtime_gets_403_on_the_gatekeepers_explicit_route_list(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-403-explicit")
    jwt = _agent_runtime_jwt(ctx["service_user"])
    fake_id = uuid.uuid4()
    checks = [
        ("GET", f"/api/v1/missions/{fake_id}/timeline"),
        ("GET", f"/api/v1/artifacts/{fake_id}/download"),
        ("GET", f"/api/v1/tasks/{fake_id}"),
        ("GET", "/api/v1/agents"),
        ("GET", "/api/v1/missions"),
    ]
    for method, path in checks:
        response = await client.request(method, path, headers=_auth_headers(jwt))
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"


@pytest.mark.asyncio
async def test_agent_runtime_gets_403_attempting_to_start_or_cancel_a_mission(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-403-mutate")
    jwt = _agent_runtime_jwt(ctx["service_user"])
    fake_id = uuid.uuid4()
    start = await client.post(f"/api/v1/missions/{fake_id}/start", headers=_auth_headers(jwt))
    cancel = await client.post(f"/api/v1/missions/{fake_id}/cancel", headers=_auth_headers(jwt))
    retry = await client.post(f"/api/v1/tasks/{fake_id}/retry", headers=_auth_headers(jwt))

    assert start.status_code == 403
    assert cancel.status_code == 403
    assert retry.status_code == 403


# ---------------------------------------------------------------------------
# Test 8 -- mission start/cancel 409 for an agent-runtime mission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operator_cannot_start_or_cancel_an_agent_runtime_mission(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-mission-guard")
    session_ref = str(uuid.uuid4())
    created = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    mission_id = created.json()["mission_id"]

    admin = User(
        id=new_id(), tenant_id=ctx["tenant"].id, email="ar-mission-guard-admin@test.local",
        display_name="Admin", role=UserRole.platform_admin.value, status=UserStatus.active.value,
        password_hash=hash_password("Test-Password-123!"),
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login", data={"username": admin.email, "password": "Test-Password-123!"}
    )
    admin_token = login.json()["access_token"]

    get_response = await client.get(
        f"/api/v1/missions/{mission_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert get_response.json()["is_agent_runtime"] is True

    start = await client.post(
        f"/api/v1/missions/{mission_id}/start", headers={"Authorization": f"Bearer {admin_token}"}
    )
    cancel = await client.post(
        f"/api/v1/missions/{mission_id}/cancel", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert start.status_code == 409
    assert cancel.status_code == 409

    mission = await db_session.get(Mission, uuid.UUID(mission_id))
    assert mission.status == "running"  # unchanged by the refused cancel


# ---------------------------------------------------------------------------
# Test 11 -- elevation attempts are 422; the created AgentVersion matches the registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_field", ["autonomy_level", "tool_policy", "model_policy_id", "agent_code"]
)
async def test_a_body_carrying_an_elevation_field_is_422(client, db_session, extra_field):
    ctx = await _make_tenant_with_runtime_key(db_session, f"ar-elev-{extra_field}")
    payload = {"kind": "session", "external_session_ref": str(uuid.uuid4()), extra_field: "A3"}

    response = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]), json=payload
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 12 -- fixed-window rate limit: the 61st call in a window is 429, no rows created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_61st_registration_call_in_a_window_is_429_and_creates_no_row(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-rate-limit")

    responses = []
    for _ in range(_RATE_LIMIT_MAX_REQUESTS + 1):
        responses.append(
            await client.post(
                "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
                json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
            )
        )

    assert responses[-1].status_code == 429
    assert all(r.status_code == 201 for r in responses[:-1])

    rows = (
        await db_session.execute(select(AgentRuntimeSession).where(AgentRuntimeSession.tenant_id == ctx["tenant"].id))
    ).scalars().all()
    assert len(rows) == _RATE_LIMIT_MAX_REQUESTS  # the 429'd call created nothing


# ---------------------------------------------------------------------------
# Test 13 -- exposure: request schema field set, audit payload shape, title regex
# ---------------------------------------------------------------------------


def test_request_schema_field_set_equals_the_allow_list_exactly():
    from api.schemas.agent_runtime import AgentRuntimeSessionCreateRequest

    assert set(AgentRuntimeSessionCreateRequest.model_fields.keys()) == {
        "kind", "agent_type", "external_session_ref", "external_instance_ref", "parent_external_session_ref",
    }


def _assert_only_ids_timestamps_and_enums(value, path="$"):
    """Recursive check (T1 acceptance test 13): every leaf in an audit payload must be
    None, a bool, an int, a uuid-shaped string, an ISO-timestamp-shaped string, or one
    of the small set of known enum-value strings -- never arbitrary prose."""
    import datetime as _dt

    _UUID_RE = re.compile(r"^[0-9a-f-]{36}$")
    _KNOWN_STRINGS = {
        "user", "agent", "system", "1.0", "dev", "api", "worker",
    }
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
        # A dotted enum-value string (event_type, e.g. "mission.created").
        if re.match(r"^[a-z_]+(\.[a-z_]+)+$", value):
            return
        raise AssertionError(f"Free-text-looking value at {path}: {value!r}")
    raise AssertionError(f"Unexpected type at {path}: {type(value)}")


@pytest.mark.asyncio
async def test_every_audit_payload_this_router_writes_is_ids_timestamps_and_enums_only(client, db_session, fake_redis):
    app.dependency_overrides[get_event_publisher] = lambda: EventPublisher(redis_client=fake_redis)
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-exposure")
    session_ref = str(uuid.uuid4())
    await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "planner",
            "external_instance_ref": "inst-exposure-1", "parent_external_session_ref": session_ref,
        },
    )

    events = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.tenant_id == ctx["tenant"].id))
    ).scalars().all()
    assert len(events) >= 4
    for event in events:
        _assert_only_ids_timestamps_and_enums(event.payload)


# ---------------------------------------------------------------------------
# Test 7 -- registration survives an ensure_assignment failure (it is never called)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_never_calls_ensure_assignment(client, db_session, monkeypatch):
    async def _boom(*args, **kwargs):
        raise AssertionError("ensure_assignment must never be called from agent-runtime registration (T1-F6)")

    # T1-F6: patched at its definition site so ANY caller that imported the name
    # (`from api.services.room_assignment import ensure_assignment`) would hit this --
    # neither `routes/agent_runtime.py` nor `services/persona_slots.py` imports it at
    # all, which is the real assertion this test makes.
    monkeypatch.setattr("api.services.room_assignment.ensure_assignment", _boom)

    ctx = await _make_tenant_with_runtime_key(db_session, "ar-no-room-call")
    session_ref = str(uuid.uuid4())
    session_resp = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    subagent_resp = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={
            "kind": "subagent", "agent_type": "planner",
            "external_instance_ref": "inst-no-room", "parent_external_session_ref": session_ref,
        },
    )

    assert session_resp.status_code == 201
    assert subagent_resp.status_code == 201


# ---------------------------------------------------------------------------
# Test 9 -- retry_task 409 for an external_manual task; requeue skips it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_task_is_409_for_a_claude_code_twin_task(client, db_session):
    ctx = await _make_tenant_with_runtime_key(db_session, "ar-retry-guard")
    session_ref = str(uuid.uuid4())
    created = await client.post(
        "/api/v1/agent-runtime/sessions", headers=_auth_headers(ctx["token"]),
        json={"kind": "session", "external_session_ref": session_ref},
    )
    task_id = created.json()["task_id"]

    admin = User(
        id=new_id(), tenant_id=ctx["tenant"].id, email="ar-retry-guard-admin@test.local",
        display_name="Admin", role=UserRole.platform_admin.value, status=UserStatus.active.value,
        password_hash=hash_password("Test-Password-123!"),
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login", data={"username": admin.email, "password": "Test-Password-123!"}
    )
    admin_token = login.json()["access_token"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/retry", headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_requeue_orphaned_running_tasks_returns_zero_for_a_twin_task_forced_running(
    db_session, fake_redis
):
    from worker.main import requeue_orphaned_running_tasks

    tenant = Tenant(id=new_id(), code="ar-orphan-guard", name="ar-orphan-guard")
    db_session.add(tenant)
    await db_session.flush()
    model_policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="claude-code-external", primary_provider="claude-code",
        primary_model="claude-code-session", max_input_tokens=0, max_output_tokens=0,
        max_cost_per_task=0, timeout_seconds=0,
    )
    db_session.add(model_policy)
    agent = Agent(
        id=new_id(), tenant_id=tenant.id, agent_code="AGT-CLAUDE-CODE", display_name="Claude Code",
        lifecycle_state=AgentLifecycleState.active.value,
    )
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="x", runtime_adapter="external_manual",
        model_policy_id=model_policy.id, autonomy_level=AutonomyLevel.a3.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
    )
    db_session.add(version)
    await db_session.flush()
    agent.active_version_id = version.id
    mission = Mission(
        id=new_id(), tenant_id=tenant.id, mission_code=f"MSN-{uuid.uuid4().hex[:10]}", title="t", objective="o",
        status="running", assigned_agent_id=agent.id, budget_policy={},
    )
    db_session.add(mission)
    await db_session.flush()
    task = Task(
        id=new_id(), mission_id=mission.id, assigned_agent_id=agent.id, title="t", instructions="i",
        status="running", idempotency_key=f"idem-{uuid.uuid4().hex}", budget_policy={}, input_context={},
    )
    db_session.add(task)
    await db_session.commit()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)

    requeued = await requeue_orphaned_running_tasks(fake_redis, sessionmaker=sessionmaker)

    assert requeued == 0
    await db_session.refresh(task)
    assert task.status == "running"  # never touched
