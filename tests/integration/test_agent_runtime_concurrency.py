"""T1 acceptance tests 5 (concurrent halves) and 6: the partial unique indexes on
`agent_runtime_sessions` and `agent_runtime_persona_slots`, not application-level
check-then-act, are what actually prevent duplicate rows / cap overrun under real
concurrent registration. Uses its own sessions against the shared `postgres_container`
(bypassing `tests/conftest.py`'s single `db_session` fixture) so requests can race for
real, the same pattern as `test_agent_rooms_concurrency.py`/`test_projects_concurrency.py`.
Calls the route module's own registration functions directly (not over HTTP) since the
object under test is the race inside them, not routing or auth.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db.base import Base
from common.db import models  # noqa: F401
from common.db.models import (
    Agent,
    AgentRuntimePersonaSlot,
    AgentRuntimeSession,
    AgentVersion,
    Mission,
    ModelPolicy,
    Task,
    Tenant,
    User,
)
from contracts.enums import AgentLifecycleState, AutonomyLevel, UserRole, UserStatus
from contracts.ids import EntityId, new_id
from contracts.policy import ToolPolicy

from api.persona_registry import PERSONA_SLOT_CAP, PersonaDefinition
from api.routes.agent_runtime import _register_session, _register_subagent
from api.schemas.agent_runtime import AgentRuntimeSessionCreateRequest
from api.services.persona_slots import ensure_persona

pytestmark = pytest.mark.integration


class _NoopEventPublisher:
    async def publish(self, event, session) -> None:
        pass


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


@pytest.fixture
async def tenant_with_service_user(sessionmaker) -> tuple[EntityId, EntityId]:
    async with sessionmaker() as session:
        tenant = Tenant(id=new_id(), code="ar-conc", name="Concurrency Tenant")
        session.add(tenant)
        await session.flush()
        model_policy = ModelPolicy(
            id=new_id(), tenant_id=tenant.id, name="claude-code-external", primary_provider="claude-code",
            primary_model="claude-code-session", max_input_tokens=0, max_output_tokens=0,
            max_cost_per_task=0, timeout_seconds=0,
        )
        session.add(model_policy)
        user = User(
            id=new_id(), tenant_id=tenant.id, email="ar-conc@test.local", display_name="Agent Runtime",
            role=UserRole.agent_runtime.value, status=UserStatus.active.value, password_hash="unused",
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
        return tenant.id, user.id


@pytest.mark.asyncio
async def test_ten_concurrent_duplicate_session_registrations_yield_one_row(
    sessionmaker, tenant_with_service_user
):
    tenant_id, user_id = tenant_with_service_user
    session_ref = str(uuid.uuid4())
    payload = AgentRuntimeSessionCreateRequest(kind="session", external_session_ref=session_ref)

    async def _attempt():
        async with sessionmaker() as session:
            user = await session.get(User, user_id)
            row = await _register_session(session, _NoopEventPublisher(), user, payload)
            await session.commit()
            return row.id

    results = await asyncio.gather(*(_attempt() for _ in range(10)))

    assert len(set(results)) == 1
    async with sessionmaker() as session:
        missions = (
            await session.execute(select(Mission).where(Mission.mission_code == session_ref))
        ).scalars().all()
        rows = (
            await session.execute(
                select(AgentRuntimeSession).where(
                    AgentRuntimeSession.tenant_id == tenant_id, AgentRuntimeSession.kind == "session"
                )
            )
        ).scalars().all()
        assert len(missions) == 1
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_ten_concurrent_duplicate_subagent_registrations_yield_one_task(
    sessionmaker, tenant_with_service_user
):
    tenant_id, user_id = tenant_with_service_user
    session_ref = str(uuid.uuid4())
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        await _register_session(
            session, _NoopEventPublisher(), user,
            AgentRuntimeSessionCreateRequest(kind="session", external_session_ref=session_ref),
        )
        await session.commit()

    payload = AgentRuntimeSessionCreateRequest(
        kind="subagent", agent_type="planner", external_instance_ref="inst-conc-1",
        parent_external_session_ref=session_ref,
    )

    async def _attempt():
        async with sessionmaker() as session:
            user = await session.get(User, user_id)
            row = await _register_subagent(session, _NoopEventPublisher(), user, payload)
            await session.commit()
            return row.id

    results = await asyncio.gather(*(_attempt() for _ in range(10)))

    assert len(set(results)) == 1
    async with sessionmaker() as session:
        tasks = (
            await session.execute(select(Task).where(Task.idempotency_key.like("%:ar:inst-conc-1")))
        ).scalars().all()
        assert len(tasks) == 1


@pytest.mark.asyncio
async def test_ten_concurrent_first_sights_of_distinct_personas_at_the_cap_boundary(
    sessionmaker, tenant_with_service_user
):
    """Tenant already has 24 of 25 slots filled; 10 DISTINCT new personas race for the
    one remaining slot -- exactly one succeeds, the other nine 409 (T1 acceptance
    test 6), and the slot table never exceeds 25 rows."""
    tenant_id, user_id = tenant_with_service_user
    async with sessionmaker() as session:
        for i in range(PERSONA_SLOT_CAP - 1):
            session.add(
                AgentRuntimePersonaSlot(id=new_id(), tenant_id=tenant_id, slot=i, agent_code=f"AGT-CC-SEED-{i}")
            )
        await session.commit()

    personas = [
        PersonaDefinition(f"AGT-CC-RACE-{i}", f"Race {i}", AutonomyLevel.a1, ToolPolicy.allow_only([]))
        for i in range(10)
    ]

    async def _attempt(persona: PersonaDefinition):
        async with sessionmaker() as session:
            try:
                agent = await ensure_persona(session, tenant_id=tenant_id, persona=persona, created_by=user_id)
                await session.commit()
                return "ok", agent.id
            except HTTPException as exc:
                return exc.status_code, None

    results = await asyncio.gather(*(_attempt(p) for p in personas))
    outcomes = [r[0] for r in results]

    assert outcomes.count("ok") == 1
    assert outcomes.count(409) == 9

    async with sessionmaker() as session:
        slot_count = (
            await session.execute(
                select(func.count()).select_from(AgentRuntimePersonaSlot).where(
                    AgentRuntimePersonaSlot.tenant_id == tenant_id
                )
            )
        ).scalar_one()
        assert slot_count == PERSONA_SLOT_CAP
