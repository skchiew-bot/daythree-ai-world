"""R0 (ADR-013): migration `0003b_model_invocations_index` adds the per-task and
per-(tenant, agent, created_at) lookup indexes to `model_invocations`, on a database that
already existed before R0 (where `create_all(checkfirst=True)` alone would skip them) and
on a brand-new one. Sync tests on purpose: alembic's env.py runs its own event loop, so
the checks here use short-lived asyncpg connections driven by `asyncio.run`.
"""
from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from common.config import get_settings

pytestmark = pytest.mark.integration

REVISION = "0003b_model_invocations_index"
TASK_INDEX = "ix_model_invocations_task_id"
TENANT_AGENT_INDEX = "ix_model_invocations_tenant_agent_created"


def _dsn(url) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _fetch(dsn: str, sql: str) -> list:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


def _run(dsn: str, sql: str) -> list:
    return asyncio.run(_fetch(dsn, sql))


class _Db:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def index_names(self, table: str = "model_invocations") -> set[str]:
        rows = _run(self.dsn, f"SELECT indexname FROM pg_indexes WHERE tablename = '{table}'")
        return {r["indexname"] for r in rows}

    def current_revision(self) -> str:
        return _run(self.dsn, "SELECT version_num FROM alembic_version")[0]["version_num"]

    def execute(self, sql: str) -> None:
        _run(self.dsn, sql)


@pytest.fixture
def fresh_database(postgres_container, monkeypatch):
    """A brand-new empty database inside the shared container."""
    base = make_url(postgres_container.get_connection_url())
    name = f"mig_{uuid.uuid4().hex[:10]}"
    admin_dsn = _dsn(base)
    _run(admin_dsn, f'CREATE DATABASE "{name}"')
    monkeypatch.setenv(
        "DATABASE_URL", base.set(drivername="postgresql+asyncpg", database=name).render_as_string(hide_password=False)
    )
    get_settings.cache_clear()
    yield _Db(_dsn(base.set(database=name)))
    get_settings.cache_clear()
    _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _alembic() -> Config:
    return Config("alembic.ini")


def test_revision_id_fits_alembic_version_and_is_the_only_head():
    script = ScriptDirectory.from_config(_alembic())
    assert len(REVISION) <= 32
    revision = script.get_revision(REVISION)
    assert revision.down_revision == "0003_agent_room_assignments"
    assert script.get_heads() == [REVISION]


def test_upgrade_from_an_empty_database_creates_both_indexes(fresh_database):
    command.upgrade(_alembic(), "head")

    assert {TASK_INDEX, TENANT_AGENT_INDEX} <= fresh_database.index_names()
    assert fresh_database.current_revision() == REVISION


def test_upgrade_from_0003_adds_the_indexes_to_an_existing_table(fresh_database):
    command.upgrade(_alembic(), "0003_agent_room_assignments")
    # 0001's create_all already builds the model's indexes on a fresh database; model the
    # pre-R0 production shape (table exists, indexes do not) by dropping them.
    fresh_database.execute(f"DROP INDEX IF EXISTS {TASK_INDEX}")
    fresh_database.execute(f"DROP INDEX IF EXISTS {TENANT_AGENT_INDEX}")
    assert not {TASK_INDEX, TENANT_AGENT_INDEX} & fresh_database.index_names()

    command.upgrade(_alembic(), "head")

    assert {TASK_INDEX, TENANT_AGENT_INDEX} <= fresh_database.index_names()
    assert fresh_database.current_revision() == REVISION


def test_downgrade_drops_only_its_own_indexes(fresh_database):
    command.upgrade(_alembic(), "head")
    other_before = fresh_database.index_names() - {TASK_INDEX, TENANT_AGENT_INDEX}
    room_indexes_before = fresh_database.index_names("agent_room_assignments")

    command.downgrade(_alembic(), "0003_agent_room_assignments")

    assert not {TASK_INDEX, TENANT_AGENT_INDEX} & fresh_database.index_names()
    assert other_before <= fresh_database.index_names()
    assert room_indexes_before == fresh_database.index_names("agent_room_assignments")
    assert fresh_database.current_revision() == "0003_agent_room_assignments"
