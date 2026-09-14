"""Shared fixtures for the integration suite. Every fixture here requires a running
Docker daemon (testcontainers spins up real Postgres/Redis) — if Docker isn't
available, the whole suite is skipped with a clear reason rather than silently
passing (see the `docker_available` check below).
"""
from __future__ import annotations

import subprocess

import fakeredis.aioredis
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db.base import Base
from common.db import models  # noqa: F401
from common.db.models import Agent, AgentVersion, ModelPolicy, Tenant, User
from contracts.enums import AgentLifecycleState, AutonomyLevel, UserRole, UserStatus
from contracts.ids import new_id
from contracts.policy import ToolPolicy
from event_service.publisher import EventPublisher
from model_gateway.gateway import ModelGateway
from model_gateway.providers.mock import MockModelProvider
from mission_engine.engine.task_executor import EngineDeps


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "ps"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


DOCKER_AVAILABLE = _docker_available()


@pytest.fixture(scope="session")
def postgres_container():
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker is not available in this environment — integration suite requires it.")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest_asyncio.fixture
async def db_session(postgres_container):
    async_url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    engine = create_async_engine(async_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def fake_redis():
    """fakeredis stands in for the queue/stream client in integration tests that don't
    specifically need to prove real Redis Streams behavior (that's covered by the one
    test in `test_event_stream.py` that uses a real Redis testcontainer instead).
    """
    return fakeredis.aioredis.FakeRedis()


class NullObjectStore:
    """In-memory stand-in for MinIO — proves the artifact-commit *logic* (idempotency,
    metadata) without needing a third testcontainer for every integration test."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}

    async def put_object(self, key: str, body: bytes, content_type: str) -> str:
        self._objects[key] = body
        return f"s3://test-bucket/{key}"

    async def get_object(self, key: str) -> bytes:
        return self._objects[key]

    async def generate_presigned_download_url(self, key: str) -> str:
        return f"http://fake-signed-url/{key}"


@pytest_asyncio.fixture
async def seeded(db_session):
    """One tenant + admin + mock model policy + active Atlas agent — the minimum
    every mission/task/security test needs, without re-typing it in every module."""
    tenant = Tenant(id=new_id(), code="test-tenant", name="Test Tenant")
    db_session.add(tenant)
    await db_session.flush()

    admin = User(
        id=new_id(), tenant_id=tenant.id, email="admin@test.local", display_name="Admin",
        role=UserRole.platform_admin.value, status=UserStatus.active.value, password_hash="unused",
    )
    db_session.add(admin)

    model_policy = ModelPolicy(
        id=new_id(), tenant_id=tenant.id, name="mock-policy", primary_provider="mock",
        primary_model="claude-sonnet-5", max_input_tokens=8000, max_output_tokens=8000,
        max_cost_per_task=2.00, timeout_seconds=60,
    )
    db_session.add(model_policy)
    await db_session.flush()

    agent = Agent(
        id=new_id(), tenant_id=tenant.id, agent_code="AGT-000001", display_name="Atlas",
        lifecycle_state=AgentLifecycleState.active.value, created_by=admin.id,
    )
    db_session.add(agent)
    await db_session.flush()

    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1, system_prompt="You are Atlas.",
        runtime_adapter="custom_durable", model_policy_id=model_policy.id,
        autonomy_level=AutonomyLevel.a1.value,
        tool_policy=ToolPolicy.allow_only([]).model_dump(), memory_policy={}, settings={},
        checksum="test-checksum", created_by=admin.id,
    )
    db_session.add(version)
    await db_session.flush()

    agent.active_version_id = version.id
    await db_session.flush()

    return {"tenant": tenant, "admin": admin, "model_policy": model_policy, "agent": agent}


@pytest.fixture
def engine_deps(fake_redis) -> EngineDeps:
    """A fixture (not a plain helper import) so every test file gets it for free via
    pytest's normal fixture injection — no cross-module `tests.*` import needed."""
    return EngineDeps(
        model_gateway=ModelGateway(providers={"mock": MockModelProvider()}),
        object_store=NullObjectStore(),
        event_publisher=EventPublisher(redis_client=fake_redis),
    )
