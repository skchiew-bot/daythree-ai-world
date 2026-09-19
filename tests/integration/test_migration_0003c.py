"""ADR-014 decision 1: migration `0003c_projects` adds `projects` and
`mission_projects` on top of `0003b_model_invocations_index`, on a database that
already has rows in `missions`/`tasks` (gate finding F1/F2's whole point — a
migration that only ever gets exercised against an empty CI database can silently
misbehave against a live one). Mirrors `test_migration_0003b.py`'s sync-connection
pattern (alembic's `env.py` runs its own event loop).
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

REVISION = "0003c_projects"
PARENT_REVISION = "0003b_model_invocations_index"


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

    def table_names(self) -> set[str]:
        rows = _run(self.dsn, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    def current_revision(self) -> str:
        return _run(self.dsn, "SELECT version_num FROM alembic_version")[0]["version_num"]

    def execute(self, sql: str) -> None:
        _run(self.dsn, sql)

    def scalar(self, sql: str):
        return _run(self.dsn, sql)[0][0]


@pytest.fixture
def fresh_database(postgres_container, monkeypatch):
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
    assert revision.down_revision == PARENT_REVISION
    assert script.get_heads() == [REVISION]


def test_upgrade_from_an_empty_database_creates_both_tables(fresh_database):
    command.upgrade(_alembic(), "head")

    assert {"projects", "mission_projects"} <= fresh_database.table_names()
    assert fresh_database.current_revision() == REVISION


def test_upgrade_on_a_populated_database_adds_no_column_to_missions_or_tasks(fresh_database):
    """Gate finding F1: the whole reason for a side table instead of a column on
    `missions`. Seeds a tenant + mission + task at the parent revision (rows that
    exist BEFORE 0003c runs), then upgrades and proves the existing tables are
    untouched while the two new tables exist."""
    command.upgrade(_alembic(), PARENT_REVISION)

    tenant_id = str(uuid.uuid4())
    mission_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    fresh_database.execute(
        f"INSERT INTO tenants (id, code, name, status) VALUES "
        f"('{tenant_id}', 'pop-tenant', 'Populated Tenant', 'active')"
    )
    fresh_database.execute(
        f"INSERT INTO agents (id, tenant_id, agent_code, display_name, lifecycle_state) VALUES "
        f"('{agent_id}', '{tenant_id}', 'AGT-POP', 'Pop Agent', 'active')"
    )
    fresh_database.execute(
        f"INSERT INTO missions (id, tenant_id, mission_code, title, objective, status, budget_policy) VALUES "
        f"('{mission_id}', '{tenant_id}', 'MSN-POP', 't', 'o', 'draft', '{{}}')"
    )
    fresh_database.execute(
        f"INSERT INTO tasks (id, mission_id, assigned_agent_id, title, instructions, idempotency_key, budget_policy) "
        f"VALUES ('{task_id}', '{mission_id}', '{agent_id}', 't', 'i', 'idem-pop', '{{}}')"
    )
    missions_columns_before = {
        r["column_name"]
        for r in _run(fresh_database.dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'missions'")
    }

    command.upgrade(_alembic(), "head")

    assert fresh_database.current_revision() == REVISION
    assert {"projects", "mission_projects"} <= fresh_database.table_names()
    missions_columns_after = {
        r["column_name"]
        for r in _run(fresh_database.dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = 'missions'")
    }
    assert missions_columns_after == missions_columns_before  # not one column added
    assert fresh_database.scalar(f"SELECT title FROM missions WHERE id = '{mission_id}'") == "t"
    assert fresh_database.scalar(f"SELECT title FROM tasks WHERE id = '{task_id}'") == "t"


def test_downgrade_drops_both_tables_and_leaves_missions_and_tasks_untouched(fresh_database):
    command.upgrade(_alembic(), "head")

    command.downgrade(_alembic(), PARENT_REVISION)

    assert not ({"projects", "mission_projects"} & fresh_database.table_names())
    assert {"missions", "tasks"} <= fresh_database.table_names()
    assert fresh_database.current_revision() == PARENT_REVISION


def test_composite_fk_rejects_a_mission_project_row_naming_another_tenants_project(fresh_database):
    command.upgrade(_alembic(), "head")

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    project_b = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    mission_a = str(uuid.uuid4())

    fresh_database.execute(f"INSERT INTO tenants (id, code, name, status) VALUES ('{tenant_a}', 't-a', 'A', 'active')")
    fresh_database.execute(f"INSERT INTO tenants (id, code, name, status) VALUES ('{tenant_b}', 't-b', 'B', 'active')")
    fresh_database.execute(
        f"INSERT INTO agents (id, tenant_id, agent_code, display_name, lifecycle_state) VALUES "
        f"('{agent_a}', '{tenant_a}', 'AGT-A', 'A', 'active')"
    )
    fresh_database.execute(
        f"INSERT INTO missions (id, tenant_id, mission_code, title, objective, status, budget_policy) VALUES "
        f"('{mission_a}', '{tenant_a}', 'MSN-A', 't', 'o', 'draft', '{{}}')"
    )
    fresh_database.execute(
        f"INSERT INTO projects (id, tenant_id, code, name, status) VALUES "
        f"('{project_b}', '{tenant_b}', 'PB', 'Project B', 'active')"
    )

    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        fresh_database.execute(
            f"INSERT INTO mission_projects (mission_id, tenant_id, project_id) VALUES "
            f"('{mission_a}', '{tenant_a}', '{project_b}')"
        )
