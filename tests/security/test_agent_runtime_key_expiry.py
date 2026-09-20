"""T3 deliverable 5 / T3-F18 (database half): a key issued with `expires_in_days` stores
that expiry, authenticates while live and 401s once it has passed; a key issued without
the flag never expires (unchanged behaviour). The CLI-wiring half is a unit test in
`services/api/tests/test_issue_agent_runtime_key_cli.py`.
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from common.db.models import Agent, AgentRuntimeApiKey, AgentVersion, ModelPolicy, Tenant
from contracts.enums import AgentLifecycleState, AutonomyLevel
from contracts.ids import new_id
from contracts.policy import ToolPolicy
from event_service.publisher import EventPublisher

from api.app.main import app
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.object_store import get_object_store
from api.dependencies.redis_client import get_redis_client

pytestmark = [pytest.mark.integration, pytest.mark.security]

_SCRIPT = Path(__file__).resolve().parents[2] / "infrastructure" / "scripts" / "issue_agent_runtime_key.py"


def _load_issue_script():
    name = "issue_agent_runtime_key"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


async def _seed_tenant(db_session, code: str) -> Tenant:
    tenant = Tenant(id=new_id(), code=code, name=code)
    db_session.add(tenant)
    await db_session.flush()
    model_policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="claude-code-external", primary_provider="claude-code",
        primary_model="claude-code-session", max_input_tokens=0, max_output_tokens=0,
        max_cost_per_task=0, timeout_seconds=0,
    )
    db_session.add(model_policy)
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
    return tenant


def _point_script_at_test_db(monkeypatch, script, db_session) -> None:
    fixed = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(script, "get_sessionmaker", lambda: fixed)


@pytest.mark.asyncio
async def test_expires_in_days_stores_an_expiry_that_many_days_ahead(db_session, monkeypatch):
    script = _load_issue_script()
    tenant = await _seed_tenant(db_session, "ar-expiry-set")
    _point_script_at_test_db(monkeypatch, script, db_session)

    before = datetime.now(timezone.utc)
    token = await script.issue(tenant.code, label="t3", expires_in_days=90)
    after = datetime.now(timezone.utc)

    row = await db_session.get(AgentRuntimeApiKey, uuid.UUID(token.split("_", 2)[1]))
    assert row.expires_at is not None
    assert before + timedelta(days=90) <= row.expires_at <= after + timedelta(days=90)


@pytest.mark.asyncio
async def test_no_flag_means_no_expiry_as_before(db_session, monkeypatch):
    script = _load_issue_script()
    tenant = await _seed_tenant(db_session, "ar-expiry-none")
    _point_script_at_test_db(monkeypatch, script, db_session)

    token = await script.issue(tenant.code, label="t3")

    row = await db_session.get(AgentRuntimeApiKey, uuid.UUID(token.split("_", 2)[1]))
    assert row.expires_at is None


@pytest.mark.asyncio
async def test_a_key_with_an_expiry_works_now_and_401s_once_it_has_passed(client, db_session, monkeypatch):
    script = _load_issue_script()
    tenant = await _seed_tenant(db_session, "ar-expiry-live")
    _point_script_at_test_db(monkeypatch, script, db_session)
    token = await script.issue(tenant.code, label="t3", expires_in_days=90)
    headers = {"Authorization": f"Bearer {token}"}

    live = await client.post(
        "/api/v1/agent-runtime/sessions", headers=headers,
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert live.status_code == 201, live.text

    row = await db_session.get(AgentRuntimeApiKey, uuid.UUID(token.split("_", 2)[1]))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    expired = await client.post(
        "/api/v1/agent-runtime/sessions", headers=headers,
        json={"kind": "session", "external_session_ref": str(uuid.uuid4())},
    )
    assert expired.status_code == 401
