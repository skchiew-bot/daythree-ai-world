"""T2 acceptance tests 4, 6 and 7: the runtime-session row lock plus the closure
table's UNIQUE `runtime_session_id` (not application-level check-then-act) is what
actually makes ten concurrent duplicate closes produce one closure row (test 4); the
reaper's `FOR UPDATE SKIP LOCKED` is what makes two concurrent sweeps reap one stale
row exactly once (test 6). Uses its own sessions against the shared `postgres_container`
(bypassing `tests/conftest.py`'s single `db_session` fixture) so requests can race for
real -- the same pattern `test_agent_runtime_concurrency.py` already uses.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db.base import Base
from common.db import models  # noqa: F401
from common.db.models import (
    Agent,
    AgentRuntimeClosure,
    AgentRuntimeSession,
    AgentVersion,
    ModelPolicy,
    Task,
    Tenant,
    User,
)
from contracts.enums import (
    ActorType,
    AgentLifecycleState,
    AgentRuntimeCloseOutcome,
    AgentRuntimeClosedBy,
    AgentRuntimeKind,
    AgentRuntimeReasonCode,
    AutonomyLevel,
    UserRole,
    UserStatus,
)
from contracts.events import Actor
from contracts.ids import new_id
from contracts.policy import BudgetPolicy, ToolPolicy

from api.routes.agent_runtime import _register_session, _register_subagent
from api.schemas.agent_runtime import AgentRuntimeSessionCreateRequest
from api.services.agent_runtime_closure import close_task, compute_hook_loss_rate, reap_stale_runtime_sessions

pytestmark = pytest.mark.integration


class _NoopEventPublisher:
    async def publish(self, event, session) -> None:
        pass


class _CountingEventPublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event, session) -> None:
        self.events.append(event)
        from common.db.models import AuditEvent

        session.add(
            AuditEvent(
                id=event.event_id, tenant_id=event.tenant_id, event_type=event.event_type.value,
                actor_type=event.actor.type.value, actor_id=event.actor.id, mission_id=event.mission_id,
                task_id=event.task_id, agent_id=event.agent_id, correlation_id=event.correlation_id,
                causation_id=event.causation_id, payload=event.model_dump(mode="json"),
                occurred_at=event.occurred_at,
            )
        )


@pytest.fixture
async def sessionmaker(postgres_container):
    async_url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    engine = create_async_engine(async_url, pool_size=20, max_overflow=20)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _make_tenant_and_agent(sessionmaker, *, runtime_adapter: str = "external_manual") -> dict:
    async with sessionmaker() as session:
        tenant = Tenant(id=new_id(), code=f"clo-{uuid.uuid4().hex[:10]}", name="Closure Concurrency Tenant")
        session.add(tenant)
        await session.flush()
        model_policy = ModelPolicy(
            id=new_id(), tenant_id=tenant.id, name="claude-code-external", primary_provider="claude-code",
            primary_model="claude-code-session", max_input_tokens=0, max_output_tokens=0,
            max_cost_per_task=0, timeout_seconds=0,
        )
        session.add(model_policy)
        user = User(
            id=new_id(), tenant_id=tenant.id, email=f"clo-{uuid.uuid4().hex[:8]}@test.local",
            display_name="Agent Runtime", role=UserRole.agent_runtime.value, status=UserStatus.active.value,
            password_hash="unused",
        )
        session.add(user)
        await session.flush()
        claude_code = Agent(
            id=new_id(), tenant_id=tenant.id, agent_code="AGT-CLAUDE-CODE", display_name="Claude Code",
            lifecycle_state=AgentLifecycleState.active.value,
        )
        session.add(claude_code)
        await session.flush()
        version = AgentVersion(
            id=new_id(), agent_id=claude_code.id, version=1, system_prompt="x", runtime_adapter="external_manual",
            model_policy_id=model_policy.id, autonomy_level=AutonomyLevel.a3.value,
            tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
        )
        session.add(version)
        await session.flush()
        claude_code.active_version_id = version.id
        await session.commit()
        return {"tenant_id": tenant.id, "user_id": user.id, "model_policy_id": model_policy.id}


async def _register_session_and_subagent(sessionmaker, ctx: dict, instance_ref: str) -> dict:
    async with sessionmaker() as session:
        user = await session.get(User, ctx["user_id"])
        session_ref = str(uuid.uuid4())
        session_row = await _register_session(
            session, _NoopEventPublisher(), user,
            AgentRuntimeSessionCreateRequest(kind="session", external_session_ref=session_ref),
        )
        await session.commit()
        subagent_row = await _register_subagent(
            session, _NoopEventPublisher(), user,
            AgentRuntimeSessionCreateRequest(
                kind="subagent", agent_type="planner", external_instance_ref=instance_ref,
                parent_external_session_ref=session_ref,
            ),
        )
        await session.commit()
        return {"session_id": session_row.id, "subagent_id": subagent_row.id, "task_id": subagent_row.task_id}


# ---------------------------------------------------------------------------
# Test 4 -- ten concurrent duplicate closes produce one closure row and one set
# of events.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ten_concurrent_duplicate_closes_produce_one_closure_row_and_one_set_of_events(sessionmaker):
    ctx = await _make_tenant_and_agent(sessionmaker)
    rows = await _register_session_and_subagent(sessionmaker, ctx, "inst-dup-close")
    actor = Actor(type=ActorType.user, id=ctx["user_id"])
    publisher = _CountingEventPublisher()

    async def _attempt():
        async with sessionmaker() as session:
            closure, is_new = await close_task(
                session, publisher, tenant_id=ctx["tenant_id"], actor=actor,
                runtime_session_id=rows["subagent_id"], outcome=AgentRuntimeCloseOutcome.completed,
                reason_code=AgentRuntimeReasonCode.hook_reported, closed_by=AgentRuntimeClosedBy.hook,
                tool_call_count=None,
            )
            await session.commit()
            return closure.id, is_new

    results = await asyncio.gather(*(_attempt() for _ in range(10)))

    closure_ids = {r[0] for r in results}
    assert len(closure_ids) == 1
    assert sum(1 for _, is_new in results if is_new) == 1

    async with sessionmaker() as session:
        closures = (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == rows["subagent_id"])
            )
        ).scalars().all()
        assert len(closures) == 1

        task_started = (
            await session.execute(select(func.count()).select_from(models.AuditEvent).where(
                models.AuditEvent.task_id == rows["task_id"], models.AuditEvent.event_type == "task.started"
            ))
        ).scalar_one()
        task_completed = (
            await session.execute(select(func.count()).select_from(models.AuditEvent).where(
                models.AuditEvent.task_id == rows["task_id"], models.AuditEvent.event_type == "task.completed"
            ))
        ).scalar_one()
        assert task_started == 1
        assert task_completed == 1

        task = await session.get(Task, rows["task_id"])
        assert task.status == "completed"


# ---------------------------------------------------------------------------
# Test 6 -- the reaper: fresh parent heartbeat spares a heartbeat-less subagent;
# a genuinely stale one is reaped; two reapers at once reap it once; a
# custom_durable task is never touched.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaper_spares_a_subagent_with_a_fresh_parent_heartbeat(sessionmaker):
    ctx = await _make_tenant_and_agent(sessionmaker)
    rows = await _register_session_and_subagent(sessionmaker, ctx, "inst-fresh-parent")
    now = datetime.now(timezone.utc)
    reap_window = timedelta(minutes=30)

    async with sessionmaker() as session:
        parent = await session.get(AgentRuntimeSession, rows["session_id"])
        parent.last_heartbeat_at = now  # fresh
        sub = await session.get(AgentRuntimeSession, rows["subagent_id"])
        sub.last_heartbeat_at = None
        sub.started_at = now - timedelta(hours=3)  # its OWN activity is old
        await session.commit()

        reaped = await reap_stale_runtime_sessions(
            session, _NoopEventPublisher(), reap_window=reap_window, now=now
        )
        await session.commit()

    assert reaped == 0
    async with sessionmaker() as session:
        task = await session.get(Task, rows["task_id"])
        assert task.status == "queued"  # never touched


@pytest.mark.asyncio
async def test_reaper_closes_a_genuinely_stale_subagent_and_ends_its_silent_parent(sessionmaker):
    ctx = await _make_tenant_and_agent(sessionmaker)
    rows = await _register_session_and_subagent(sessionmaker, ctx, "inst-genuinely-stale")
    now = datetime.now(timezone.utc)
    reap_window = timedelta(minutes=30)
    stale_at = now - timedelta(hours=3)

    async with sessionmaker() as session:
        parent = await session.get(AgentRuntimeSession, rows["session_id"])
        parent.started_at = stale_at
        parent.last_heartbeat_at = None
        sub = await session.get(AgentRuntimeSession, rows["subagent_id"])
        sub.started_at = stale_at
        sub.last_heartbeat_at = None
        await session.commit()

        reaped = await reap_stale_runtime_sessions(
            session, _NoopEventPublisher(), reap_window=reap_window, now=now
        )
        await session.commit()

    assert reaped == 1
    async with sessionmaker() as session:
        task = await session.get(Task, rows["task_id"])
        assert task.status == "failed"
        closure = (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == rows["subagent_id"])
            )
        ).scalar_one()
        assert closure.closed_by == "reaper"
        assert closure.reason_code == "reaped_stale"

        parent_row = await session.get(AgentRuntimeSession, rows["session_id"])
        assert parent_row.ended_at is not None  # SessionEnd ran for the now-silent parent
        parent_task_row = await session.get(Task, parent_row.task_id)
        assert parent_task_row.status == "completed"


@pytest.mark.asyncio
async def test_two_reapers_at_once_reap_one_stale_subagent_exactly_once(sessionmaker):
    ctx = await _make_tenant_and_agent(sessionmaker)
    rows = await _register_session_and_subagent(sessionmaker, ctx, "inst-two-reapers")
    now = datetime.now(timezone.utc)
    reap_window = timedelta(minutes=30)
    stale_at = now - timedelta(hours=3)

    async with sessionmaker() as session:
        parent = await session.get(AgentRuntimeSession, rows["session_id"])
        parent.started_at = stale_at
        sub = await session.get(AgentRuntimeSession, rows["subagent_id"])
        sub.started_at = stale_at
        await session.commit()

    async def _sweep():
        async with sessionmaker() as session:
            reaped = await reap_stale_runtime_sessions(
                session, _NoopEventPublisher(), reap_window=reap_window, now=now
            )
            await session.commit()
            return reaped

    results = await asyncio.gather(_sweep(), _sweep())

    assert sum(results) == 1  # exactly one of the two sweeps actually reaped it
    async with sessionmaker() as session:
        closures = (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == rows["subagent_id"])
            )
        ).scalars().all()
        assert len(closures) == 1


@pytest.mark.asyncio
async def test_reaper_never_touches_a_custom_durable_task(sessionmaker):
    """A hypothetical misuse/edge case: an `agent_runtime_sessions` row whose Task is
    assigned to a `custom_durable` agent must never be reaped -- the explicit
    `runtime_adapter != 'custom_durable'` guard in the reaper's own query (T2-F1),
    not just "this never happens in practice"."""
    ctx = await _make_tenant_and_agent(sessionmaker)
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(hours=3)

    async with sessionmaker() as session:
        durable_agent = Agent(
            id=new_id(), tenant_id=ctx["tenant_id"], agent_code="AGT-DURABLE", display_name="Durable",
            lifecycle_state=AgentLifecycleState.active.value,
        )
        session.add(durable_agent)
        await session.flush()
        durable_version = AgentVersion(
            id=new_id(), agent_id=durable_agent.id, version=1, system_prompt="x", runtime_adapter="custom_durable",
            model_policy_id=ctx["model_policy_id"], autonomy_level=AutonomyLevel.a1.value,
            tool_policy=ToolPolicy.allow_only([]).model_dump(), checksum="x",
        )
        session.add(durable_version)
        await session.flush()
        durable_agent.active_version_id = durable_version.id

        parent_session_row = AgentRuntimeSession(
            id=new_id(), tenant_id=ctx["tenant_id"], kind=AgentRuntimeKind.session.value,
            agent_id=durable_agent.id, external_session_ref=str(uuid.uuid4()), started_at=stale_at,
        )
        session.add(parent_session_row)
        await session.flush()

        mission = models.Mission(
            id=new_id(), tenant_id=ctx["tenant_id"], mission_code=f"MSN-{uuid.uuid4().hex[:10]}", title="t",
            objective="o", status="running", assigned_agent_id=durable_agent.id, budget_policy=BudgetPolicy().model_dump(),
        )
        session.add(mission)
        await session.flush()
        durable_task = Task(
            id=new_id(), mission_id=mission.id, assigned_agent_id=durable_agent.id, title="t", instructions="i",
            status="running", idempotency_key=f"idem-{uuid.uuid4().hex}", budget_policy={}, input_context={},
        )
        session.add(durable_task)
        await session.flush()

        durable_subagent_row = AgentRuntimeSession(
            id=new_id(), tenant_id=ctx["tenant_id"], kind=AgentRuntimeKind.subagent.value,
            agent_id=durable_agent.id, mission_id=mission.id, task_id=durable_task.id,
            external_session_ref=parent_session_row.external_session_ref,
            external_instance_ref=f"inst-durable-{uuid.uuid4().hex[:8]}", parent_session_id=parent_session_row.id,
            started_at=stale_at,
        )
        session.add(durable_subagent_row)
        await session.commit()

        reaped = await reap_stale_runtime_sessions(
            session, _NoopEventPublisher(), reap_window=timedelta(minutes=30), now=now
        )
        await session.commit()

    assert reaped == 0
    async with sessionmaker() as session:
        task = await session.get(Task, durable_task.id)
        assert task.status == "running"  # never touched
        closures = (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == durable_subagent_row.id)
            )
        ).scalars().all()
        assert closures == []


# ---------------------------------------------------------------------------
# Test 7 -- a late close after reaping is 200-equivalent, leaves the Task
# `failed`, sets `late_close_at`, and removes it from the loss count.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_late_hook_close_after_reaping_sets_late_close_at_and_leaves_the_task_failed(sessionmaker):
    ctx = await _make_tenant_and_agent(sessionmaker)
    rows = await _register_session_and_subagent(sessionmaker, ctx, "inst-late-close")
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(hours=3)
    actor = Actor(type=ActorType.system)

    async with sessionmaker() as session:
        sub = await session.get(AgentRuntimeSession, rows["subagent_id"])
        sub.started_at = stale_at
        parent = await session.get(AgentRuntimeSession, rows["session_id"])
        parent.last_heartbeat_at = now  # keep the parent fresh so only the subagent reaps
        await session.commit()

        await reap_stale_runtime_sessions(session, _NoopEventPublisher(), reap_window=timedelta(minutes=30), now=now)
        await session.commit()

    since = now - timedelta(hours=1)
    async with sessionmaker() as session:
        before = await compute_hook_loss_rate(session, ctx["tenant_id"], since=since)
    assert before.lost == 1
    assert before.total == 1

    async with sessionmaker() as session:
        closure, is_new = await close_task(
            session, _NoopEventPublisher(), tenant_id=ctx["tenant_id"], actor=actor,
            runtime_session_id=rows["subagent_id"], outcome=AgentRuntimeCloseOutcome.completed,
            reason_code=AgentRuntimeReasonCode.hook_reported, closed_by=AgentRuntimeClosedBy.hook,
            tool_call_count=3,
        )
        await session.commit()

    assert is_new is False  # a 200, not a new closure row
    assert closure.closed_by == "reaper"  # the ORIGINAL closer is preserved
    assert closure.late_close_at is not None

    async with sessionmaker() as session:
        task = await session.get(Task, rows["task_id"])
        assert task.status == "failed"  # never overwritten to the late hook's "completed"

        closures = (
            await session.execute(
                select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == rows["subagent_id"])
            )
        ).scalars().all()
        assert len(closures) == 1  # no second row was created

        after = await compute_hook_loss_rate(session, ctx["tenant_id"], since=since)
    assert after.lost == 0  # removed from the loss count
    assert after.total == 1
