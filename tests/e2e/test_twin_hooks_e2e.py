"""T3 e2e (build plan test 9): the real hook script, real bash and curl, against the real
compose stack (API, Postgres, worker with its reaper).

A throwaway key is issued INSIDE this run with the platform's own issue script, kept only in
a temporary key file the hook reads, never printed or asserted on, and revoked at the end.
Nothing here touches any other tenant's data; every payload is synthetic with run-time
generated ids and canary tokens.

Covers: SessionStart, two SubagentStart, two SubagentStop and SessionEnd give one Mission,
closed Tasks, two closures with closed_by=hook, no artifact and a hook-loss rate of 0; a
never-stopped subagent is reaped and its late close returns 200 with late_close_at; a hook
heartbeat keeps a session out of the reaper; every audit payload is ids, timestamps and
enums; the canaries appear in no table; and the key gets no access to the operator routes.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from common.config import get_settings
from common.db.base import Base
from common.db.models import (
    Agent,
    AgentRuntimeClosure,
    AgentRuntimeSession,
    Artifact,
    AuditEvent,
    Mission,
    Task,
)
from contracts.enums import AgentRuntimeKind
from api.services.agent_runtime_closure import compute_hook_loss_rate

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "report_twin_lifecycle.sh"
ISSUE_SCRIPT = REPO / "infrastructure" / "scripts" / "issue_agent_runtime_key.py"
API_URL = "http://localhost:8000"
BASH = shutil.which("bash")
KEY_SHAPE = re.compile(r"^dtk_[0-9a-f]{32}_[A-Za-z0-9_-]{20,128}$")
_PYTHONPATH = os.pathsep.join(
    str(REPO / part)
    for part in (
        "packages", "packages/policy-sdk", "packages/tool-sdk", "services", "services/mission-engine",
        "services/agent-runtime", "services/model-gateway", "services/event-service", "services/artifact-service",
    )
)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _db(work):
    """Run `work(session)` in its own short-lived engine (no pooled connection survives the
    event loop that `asyncio.run` closes)."""

    async def runner():
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await work(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(runner())


def _issue(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": _PYTHONPATH}
    return subprocess.run(
        [sys.executable, str(ISSUE_SCRIPT), "--tenant-code", get_settings().seed_tenant_code, *args],
        capture_output=True, text=True, cwd=REPO, env=env, timeout=120,
    )


class Twin:
    def __init__(self, home: Path, key: str) -> None:
        self.home = home
        self.key = key

    def fire(self, event: str, session_id: str, **fields) -> None:
        body = json.dumps({"session_id": session_id, "hook_event_name": event, **fields}).encode()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TWIN_", "DAYTHREE_TWIN_"))}
        env["TWIN_HOME"] = str(self.home)
        result = subprocess.run([BASH, SCRIPT.as_posix()], input=body, capture_output=True, env=env, timeout=60)
        assert result.returncode == 0
        assert result.stdout == b"" and result.stderr == b""

    def state_path(self, session_id: str) -> Path:
        return self.home / ".hook-debug" / "twin-state" / session_id

    def state(self, session_id: str) -> tuple[str, str, int]:
        run, runtime, heartbeat = self.state_path(session_id).read_text().split()
        return run, runtime, int(heartbeat)

    def age_heartbeat(self, session_id: str) -> None:
        run, runtime, _hb = self.state(session_id)
        self.state_path(session_id).write_text(f"{run} {runtime} 0\n")

    def log_classes(self) -> list[str]:
        log = self.home / ".hook-debug" / "twin_lifecycle.log"
        return [line.split(" ")[2] for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture(scope="module")
def twin(tmp_path_factory) -> Twin:
    if BASH is None:
        pytest.skip("bash is not available")
    if not (os.environ.get("CI") or os.environ.get("TWIN_E2E_ALLOW") == "1"):
        # This test issues (and revokes) a key and writes twin rows in the stack's own
        # tenant. CI's throwaway stack is the intended target; a developer's local stack
        # can hold real data, so it needs an explicit opt-in.
        pytest.skip("runs in CI, or locally only with TWIN_E2E_ALLOW=1")
    issued = _issue("--expires-in-days", "1", "--label", "t3 e2e throwaway")
    assert issued.returncode == 0, f"issue script failed: {issued.stderr[-300:]}"
    key = issued.stdout.strip().splitlines()[-1]
    assert KEY_SHAPE.match(key), "the issue script's last output line is not a key"
    home = tmp_path_factory.mktemp("twin-home")
    (home / ".daythree").mkdir()
    (home / ".daythree" / "twin_env.sh").write_text(
        f"DAYTHREE_TWIN_BASE_URL={API_URL}\nDAYTHREE_TWIN_KEY={key}\n", newline="\n"
    )
    yield Twin(home, key)
    revoked = _issue("--revoke", key.split("_", 2)[1])
    assert revoked.returncode == 0, "the throwaway key was not revoked"


# ------------------------------------------------------------------------------ helpers


def _canaries() -> dict:
    tag = secrets.token_hex(6)
    return {
        "prompt": f"CANARY-prompt-{tag}", "cwd": f"X:/CANARY-cwd-{tag}", "transcript_path": f"X:/CANARY-tp-{tag}.txt",
        "last_assistant_message": f"CANARY-message-{tag} error failed", "session_title": f"CANARY-title-{tag}",
        "permission_mode": f"CANARY-mode-{tag}", "tool_input": {"command": f"CANARY-tool-{tag}"},
    }


def _new_agent_id() -> str:
    return secrets.token_hex(8) + "0"


def _runtime_row(kind: str, **where):
    async def work(session):
        stmt = select(AgentRuntimeSession).where(AgentRuntimeSession.kind == kind)
        for column, value in where.items():
            stmt = stmt.where(getattr(AgentRuntimeSession, column) == value)
        return (await session.execute(stmt)).scalar_one()

    return _db(work)


def _closure_for(runtime_session_id):
    async def work(session):
        return (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == runtime_session_id)
            )
        ).scalar_one_or_none()

    return _db(work)


def _backdate(ids: list, hours: int = 3) -> None:
    async def work(session):
        await session.execute(
            update(AgentRuntimeSession)
            .where(AgentRuntimeSession.id.in_(ids))
            .values(started_at=func.now() - dt.timedelta(hours=hours), last_heartbeat_at=None)
        )

    _db(work)


def _assert_ids_timestamps_and_enums(value, path="payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_ids_timestamps_and_enums(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_ids_timestamps_and_enums(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if _UUID.match(value) or re.match(r"^[a-z_]+(\.[a-z_]+)*$", value):
            return
        try:
            dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise AssertionError(f"free-text-looking value at {path}") from None
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise AssertionError(f"unexpected type at {path}: {type(value)}")


# ------------------------------------------------------------------------------ tests


def test_one_session_and_two_subagents_give_one_mission_two_hook_closures_and_no_artifact(twin):
    started = dt.datetime.now(dt.timezone.utc)
    session_id, first, second = str(uuid.uuid4()), _new_agent_id(), _new_agent_id()
    canaries = _canaries()

    twin.fire("SessionStart", session_id, source="startup", **canaries)
    run = twin.state(session_id)[0]
    twin.fire("SubagentStart", session_id, agent_id=first, agent_type="planner", **canaries)
    twin.fire("SubagentStart", session_id, agent_id=second, agent_type="architect", **canaries)
    twin.fire("SubagentStop", session_id, agent_id=first, agent_type="planner", **canaries)
    twin.fire("SubagentStop", session_id, agent_id=second, agent_type="architect", **canaries)
    twin.fire("SessionEnd", session_id, reason="clear", **canaries)
    finished = dt.datetime.now(dt.timezone.utc)
    assert not twin.state_path(session_id).exists()

    async def inspect(session):
        missions = (await session.execute(select(Mission).where(Mission.mission_code == run))).scalars().all()
        assert len(missions) == 1
        mission = missions[0]
        assert re.match(r"^Claude Code session [0-9a-f-]{36}$", mission.title)
        tasks = (await session.execute(select(Task).where(Task.mission_id == mission.id))).scalars().all()
        codes = {
            (await session.get(Agent, task.assigned_agent_id)).agent_code for task in tasks
        }
        runtime = (
            await session.execute(select(AgentRuntimeSession).where(AgentRuntimeSession.mission_id == mission.id))
        ).scalars().all()
        closures = (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.task_id.in_([t.id for t in tasks]))
            )
        ).scalars().all()
        artifacts = (
            await session.execute(select(func.count()).select_from(Artifact).where(Artifact.mission_id == mission.id))
        ).scalar_one()
        events = (
            await session.execute(select(AuditEvent).where(AuditEvent.mission_id == mission.id))
        ).scalars().all()
        loss = await compute_hook_loss_rate(session, mission.tenant_id, since=started, until=finished)
        return mission, tasks, codes, runtime, closures, artifacts, events, loss

    mission, tasks, codes, runtime, closures, artifacts, events, loss = _db(inspect)

    assert mission.status == "completed"
    assert len(tasks) == 3 and {t.status for t in tasks} == {"completed"}
    assert {"AGT-CC-PLANNER", "AGT-CC-ARCHITECT", "AGT-CLAUDE-CODE"} == codes
    assert sorted(r.kind for r in runtime) == ["session", "subagent", "subagent"]
    assert {r.external_instance_ref for r in runtime if r.kind == "subagent"} == {first, second}
    assert all(r.ended_at is not None for r in runtime if r.kind == "session")
    assert len(closures) == 2
    assert all(c.closed_by == "hook" and c.outcome == "completed" and c.reason_code == "hook_reported" for c in closures)
    assert all(c.artifact_id is None and c.tool_call_count is None and c.late_close_at is None for c in closures)
    assert artifacts == 0
    assert (loss.lost, loss.total, loss.rate) == (0, 2, 0.0)
    assert events, "the lifecycle must have written audit events"
    for event in events:
        _assert_ids_timestamps_and_enums(event.payload)

    async def scan(session):
        hits = {}
        for table in Base.metadata.sorted_tables:
            count = (
                await session.execute(
                    text(f'SELECT count(*) FROM "{table.name}" t WHERE row_to_json(t)::text ILIKE :pattern'),
                    {"pattern": "%CANARY-%"},
                )
            ).scalar_one()
            if count:
                hits[table.name] = count
        return hits

    assert _db(scan) == {}, "a canary field reached the database"


def test_a_silent_subagent_is_reaped_a_late_close_is_200_and_a_heartbeat_keeps_a_session_alive(twin):
    started = dt.datetime.now(dt.timezone.utc)
    silent_session, silent_agent = str(uuid.uuid4()), _new_agent_id()
    live_session, live_agent = str(uuid.uuid4()), _new_agent_id()

    twin.fire("SessionStart", silent_session, source="startup")
    twin.fire("SubagentStart", silent_session, agent_id=silent_agent, agent_type="code-reviewer")
    twin.fire("SessionStart", live_session, source="startup")
    twin.fire("SubagentStart", live_session, agent_id=live_agent, agent_type="tdd-guide")

    silent_run = twin.state(silent_session)[0]
    live_run = twin.state(live_session)[0]
    silent_parent = _runtime_row(AgentRuntimeKind.session.value, external_session_ref=silent_run)
    silent_sub = _runtime_row(AgentRuntimeKind.subagent.value, external_instance_ref=silent_agent)
    live_parent = _runtime_row(AgentRuntimeKind.session.value, external_session_ref=live_run)
    live_sub = _runtime_row(AgentRuntimeKind.subagent.value, external_instance_ref=live_agent)

    # The heartbeat protects a session whose own rows look hours old. Staleness is the
    # GREATEST of the subagent's and the parent's last activity, so each step below leaves
    # at least one fresh row for the reaper to see: parent aged, hook heartbeat refreshes it,
    # then the subagent aged.
    _backdate([live_parent.id])
    twin.age_heartbeat(live_session)
    twin.fire("Stop", live_session)  # the hook's heartbeat PATCH
    _backdate([live_sub.id])
    refreshed = _runtime_row(AgentRuntimeKind.session.value, external_session_ref=live_run)
    assert refreshed.last_heartbeat_at is not None
    assert (dt.datetime.now(dt.timezone.utc) - refreshed.last_heartbeat_at) < dt.timedelta(minutes=5)

    # The silent session ages as a whole, atomically: the hook never spoke again.
    _backdate([silent_parent.id, silent_sub.id])

    deadline = time.monotonic() + 240  # the worker's reaper sweeps every 60 s
    closure = None
    while time.monotonic() < deadline:
        closure = _closure_for(silent_sub.id)
        if closure is not None:
            break
        time.sleep(5)
    assert closure is not None, "the reaper never closed the silent subagent"
    assert closure.closed_by == "reaper" and closure.outcome == "failed" and closure.reason_code == "reaped_stale"
    assert closure.late_close_at is None

    # ...and the session whose hook heartbeated was NOT reaped in the same sweeps.
    assert _closure_for(live_sub.id) is None

    async def loss_now(session):
        return await compute_hook_loss_rate(session, silent_parent.tenant_id, since=started)

    assert _db(loss_now).lost == 1

    twin.fire("SubagentStop", silent_session, agent_id=silent_agent)  # the hook finally speaks: a late close
    late = _closure_for(silent_sub.id)
    assert late.late_close_at is not None and late.closed_by == "reaper"  # still failed, now marked late
    assert _db(loss_now).lost == 0

    twin.fire("SubagentStop", live_session, agent_id=live_agent)
    twin.fire("SessionEnd", live_session, reason="clear")
    assert _closure_for(live_sub.id).closed_by == "hook"


def test_the_key_gets_no_access_to_the_operator_routes(twin):
    headers = {"Authorization": f"Bearer {twin.key}"}
    probes = [
        f"{API_URL}/api/v1/missions",
        f"{API_URL}/api/v1/agents",
        f"{API_URL}/api/v1/tasks/{uuid.uuid4()}",
        f"{API_URL}/api/v1/artifacts/{uuid.uuid4()}/download",
    ]

    statuses = [httpx.get(url, headers=headers, timeout=15).status_code for url in probes]

    # A `dtk_` bearer is not a JWT, so the operator routes refuse it before any role check
    # (401); a JWT for the same service user is the 403 case T1's own suite covers.
    assert all(status in (401, 403) for status in statuses), statuses
