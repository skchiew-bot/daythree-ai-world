"""R0 (ADR-013): migration `0003b_model_invocations_index` adds the per-task and
per-(tenant, agent, created_at) lookup indexes to `model_invocations`, on a database that
already existed before R0 (where `create_all(checkfirst=True)` alone would skip them) and
on a brand-new one. Sync tests on purpose: alembic's env.py runs its own event loop.
"""
from __future__ import annotations

import uuid

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from common.config import get_settings

pytestmark = pytest.mark.integration

REVISION = "0003b_model_invocations_index"
TASK_INDEX = "ix_model_invocations_task_id"
TENANT_AGENT_INDEX = "ix_model_invocations_tenant_agent_created"


@pytest.fixture
def fresh_database(postgres_container, monkeypatch):
    """A brand-new empty database inside the shared container; yields (async_url, sync_engine)."""
    base = make_url(postgres_container.get_connection_url())
    name = f"mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(base.set(drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    sync_url = base.set(drivername="postgresql+psycopg", database=name)
    async_url = base.set(drivername="postgresql+asyncpg", database=name)
    monkeypatch.setenv("DATABASE_URL", async_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    engine = create_engine(sync_url)
    yield engine
    engine.dispose()
    get_settings.cache_clear()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _alembic() -> Config:
    return Config("alembic.ini")


def _index_names(engine) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes("model_invocations")}


def _current_revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_revision_id_fits_alembic_version_and_is_the_only_head():
    script = ScriptDirectory.from_config(_alembic())
    assert len(REVISION) <= 32
    revision = script.get_revision(REVISION)
    assert revision.down_revision == "0003_agent_room_assignments"
    assert script.get_heads() == [REVISION]


def test_upgrade_from_an_empty_database_creates_both_indexes(fresh_database):
    command.upgrade(_alembic(), "head")

    assert {TASK_INDEX, TENANT_AGENT_INDEX} <= _index_names(fresh_database)
    assert _current_revision(fresh_database) == REVISION


def test_upgrade_from_0003_adds_the_indexes_to_an_existing_table(fresh_database):
    command.upgrade(_alembic(), "0003_agent_room_assignments")
    # 0001's create_all already builds the model's indexes on a fresh database; model the
    # pre-R0 production shape (table exists, indexes do not) by dropping them.
    with fresh_database.begin() as conn:
        conn.execute(text(f"DROP INDEX IF EXISTS {TASK_INDEX}"))
        conn.execute(text(f"DROP INDEX IF EXISTS {TENANT_AGENT_INDEX}"))
    assert not {TASK_INDEX, TENANT_AGENT_INDEX} & _index_names(fresh_database)

    command.upgrade(_alembic(), "head")

    assert {TASK_INDEX, TENANT_AGENT_INDEX} <= _index_names(fresh_database)
    assert _current_revision(fresh_database) == REVISION


def test_downgrade_drops_only_its_own_indexes(fresh_database):
    command.upgrade(_alembic(), "head")
    other_before = _index_names(fresh_database) - {TASK_INDEX, TENANT_AGENT_INDEX}
    room_indexes_before = {ix["name"] for ix in inspect(fresh_database).get_indexes("agent_room_assignments")}

    command.downgrade(_alembic(), "0003_agent_room_assignments")

    assert not {TASK_INDEX, TENANT_AGENT_INDEX} & _index_names(fresh_database)
    assert other_before <= _index_names(fresh_database)
    assert room_indexes_before == {ix["name"] for ix in inspect(fresh_database).get_indexes("agent_room_assignments")}
    assert _current_revision(fresh_database) == "0003_agent_room_assignments"
