"""Security review follow-up on PR #26 (MEDIUM): the 48-active-project cap
(`api.routes.projects._MAX_ACTIVE_PROJECTS`) was check-then-insert with no DB
backstop, so concurrent creates racing inside the same rate-limit window could
leave a tenant above the cap the W2 grid (48 lots) depends on. Uses its own
sessionmaker against the shared `postgres_container` (bypassing
`tests/conftest.py`'s single `db_session` fixture) so eight creates can race for
real, the same pattern as `test_agent_rooms_concurrency.py`. Calls the route
function directly rather than over HTTP, since the object under test is the
count-then-insert race inside it, not routing or auth.
"""
from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db.base import Base
from common.db import models  # noqa: F401
from common.db.models import Project, Tenant, User
from contracts.enums import ProjectStatus, UserRole, UserStatus
from contracts.ids import EntityId, new_id

from api.routes.projects import _MAX_ACTIVE_PROJECTS, create_project
from api.schemas.projects import ProjectCreateRequest

pytestmark = [pytest.mark.integration, pytest.mark.security]


class _NoopEventPublisher:
    async def publish(self, event, session) -> None:
        pass


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
async def tenant_at_the_cap_boundary(sessionmaker) -> tuple[EntityId, EntityId]:
    """A tenant with 47 active projects already seeded — one below the cap."""
    async with sessionmaker() as session:
        tenant = Tenant(id=new_id(), code="proj-conc", name="Concurrency Tenant")
        session.add(tenant)
        await session.flush()
        admin = User(
            id=new_id(), tenant_id=tenant.id, email="proj-conc-admin@test.local", display_name="Admin",
            role=UserRole.tenant_admin.value, status=UserStatus.active.value, password_hash="unused",
        )
        session.add(admin)
        for i in range(_MAX_ACTIVE_PROJECTS - 1):
            session.add(
                Project(
                    id=new_id(), tenant_id=tenant.id, code=f"SEED{i}", name=f"Seed {i}",
                    status=ProjectStatus.active.value,
                )
            )
        await session.commit()
        return tenant.id, admin.id


@pytest.mark.asyncio
async def test_only_one_of_eight_concurrent_creates_succeeds_at_the_cap_boundary(
    sessionmaker, tenant_at_the_cap_boundary
):
    tenant_id, admin_id = tenant_at_the_cap_boundary
    redis = fakeredis.aioredis.FakeRedis()

    async def _attempt(i: int) -> str | int:
        async with sessionmaker() as session:
            user = await session.get(User, admin_id)
            try:
                await create_project(
                    ProjectCreateRequest(code=f"RACE{i}", name=f"Race {i}"),
                    user=user, session=session, redis=redis, publisher=_NoopEventPublisher(),
                )
                await session.commit()
                return "ok"
            except HTTPException as exc:
                return exc.status_code

    results = await asyncio.gather(*(_attempt(i) for i in range(8)))

    assert results.count("ok") == 1
    assert results.count(409) == 7

    async with sessionmaker() as session:
        active_count = (
            await session.execute(
                select(func.count()).select_from(Project).where(
                    Project.tenant_id == tenant_id, Project.status == ProjectStatus.active.value
                )
            )
        ).scalar_one()
        assert active_count == _MAX_ACTIVE_PROJECTS
