"""ADR-009: the partial unique index (`uq_agent_room_assignments_active_room`), not
application-level check-then-act, is what actually prevents double-booking under
concurrent allocation. Uses its own sessions against the shared postgres_container
(bypassing tests/conftest.py's single db_session fixture) so two allocations can
race for real.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db.base import Base
from common.db import models  # noqa: F401
from common.db.models import Agent, Tenant
from contracts.enums import AgentLifecycleState
from contracts.ids import EntityId, new_id

from api.services.room_assignment import ensure_assignment, get_assignment, release_assignment

pytestmark = pytest.mark.integration


@pytest.fixture
async def sessionmaker(postgres_container):
    async_url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    engine = create_async_engine(async_url, pool_size=10, max_overflow=10)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def tenant_id(sessionmaker):
    async with sessionmaker() as session:
        tenant = Tenant(id=new_id(), code="rooms-concurrency", name="Concurrency Tenant")
        session.add(tenant)
        await session.commit()
        return tenant.id


async def _make_agent(sessionmaker, tenant_id, agent_code: str) -> EntityId:
    async with sessionmaker() as session:
        agent = Agent(
            id=new_id(), tenant_id=tenant_id, agent_code=agent_code, display_name=agent_code,
            lifecycle_state=AgentLifecycleState.active.value,
        )
        session.add(agent)
        await session.commit()
        return agent.id


@pytest.mark.asyncio
async def test_eight_concurrent_distinct_agents_get_eight_distinct_rooms(sessionmaker, tenant_id):
    agent_ids = [await _make_agent(sessionmaker, tenant_id, f"AGT-CONC-{i}") for i in range(8)]

    async def _allocate(agent_id):
        async with sessionmaker() as session:
            assignment = await ensure_assignment(session, tenant_id, agent_id)
            await session.commit()
            return assignment.floor, assignment.room_index

    results = await asyncio.gather(*(_allocate(agent_id) for agent_id in agent_ids))
    assert all(r is not None for r in results)
    assert len(set(results)) == 8  # no two agents share a room


@pytest.mark.asyncio
async def test_two_concurrent_ensures_for_one_agent_yield_one_active_row(sessionmaker, tenant_id):
    agent_id = await _make_agent(sessionmaker, tenant_id, "AGT-CONC-SAME")

    async def _allocate():
        async with sessionmaker() as session:
            assignment = await ensure_assignment(session, tenant_id, agent_id)
            await session.commit()
            return assignment

    results = await asyncio.gather(_allocate(), _allocate())
    assert all(r is not None for r in results)
    assert {(r.floor, r.room_index) for r in results} == {(results[0].floor, results[0].room_index)}

    async with sessionmaker() as session:
        from sqlalchemy import func, select
        from common.db.models import AgentRoomAssignment

        count = (
            await session.execute(
                select(func.count()).select_from(AgentRoomAssignment).where(
                    AgentRoomAssignment.agent_id == agent_id, AgentRoomAssignment.released_at.is_(None)
                )
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_room_is_reusable_after_release(sessionmaker, tenant_id):
    first_agent = await _make_agent(sessionmaker, tenant_id, "AGT-CONC-FIRST")
    async with sessionmaker() as session:
        first = await ensure_assignment(session, tenant_id, first_agent)
        await session.commit()
        first_slot = (first.floor, first.room_index)

    async with sessionmaker() as session:
        await release_assignment(session, tenant_id, first_agent)
        await session.commit()

    second_agent = await _make_agent(sessionmaker, tenant_id, "AGT-CONC-SECOND")
    async with sessionmaker() as session:
        second = await ensure_assignment(session, tenant_id, second_agent)
        await session.commit()
        assert (second.floor, second.room_index) == first_slot  # the freed slot, since it's the lowest free one
