"""T1 gate finding T1-F1 / acceptance test 1: migration `0004_agent_runtime_sessions` adds
three NEW tables on top of `0003c_projects` and touches nothing else. Runs on a database
that already holds rows in `missions`/`tasks`/`agents`, because a migration exercised only
against CI's empty database can silently misbehave on the operator's live one. CI has no
migration round-trip step, so this file is the only proof `downgrade()` works.

Every earlier migration calls `Base.metadata.create_all(checkfirst=True)`, which creates
EVERY table in today's models, this phase's three included. A live database that is
already at `0003c` never ran that code with these models, so the populated-database test
below drops the three tables after upgrading to `0003c` to reproduce the live state.
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

REVISION = "0004_agent_runtime_sessions"
PARENT_REVISION = "0003c_projects"
NEW_TABLES = {"agent_runtime_sessions", "agent_runtime_persona_slots", "agent_runtime_api_keys"}
GUARDED_TABLES = ("missions", "tasks", "agents", "users", "agent_versions")


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

    def columns(self, table: str) -> set[str]:
        rows = _run(
            self.dsn, f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'"
        )
        return {r["column_name"] for r in rows}

    def indexdefs(self, table: str) -> dict[str, str]:
        rows = _run(self.dsn, f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename = '{table}'")
        return {r["indexname"]: r["indexdef"] for r in rows}


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


def _assert_all_new_indexes(db: _Db) -> None:
    sessions = db.indexdefs("agent_runtime_sessions")
    session_ref = sessions["uq_agent_runtime_sessions_session_ref"]
    assert "UNIQUE" in session_ref
    assert "(tenant_id, external_session_ref)" in session_ref
    assert "'session'" in session_ref.split("WHERE")[1]
    instance_ref = sessions["uq_agent_runtime_sessions_instance_ref"]
    assert "UNIQUE" in instance_ref
    assert "(tenant_id, external_instance_ref)" in instance_ref
    assert "'subagent'" in instance_ref.split("WHERE")[1]
    assert "(mission_id)" in sessions["ix_agent_runtime_sessions_mission_id"]

    slots = db.indexdefs("agent_runtime_persona_slots")
    assert "UNIQUE" in slots["uq_agent_runtime_persona_slots_tenant_slot"]
    assert "(tenant_id, slot)" in slots["uq_agent_runtime_persona_slots_tenant_slot"]
    assert "UNIQUE" in slots["uq_agent_runtime_persona_slots_tenant_code"]
    assert "(tenant_id, agent_code)" in slots["uq_agent_runtime_persona_slots_tenant_code"]

    keys = db.indexdefs("agent_runtime_api_keys")
    assert "UNIQUE" in keys["uq_agent_runtime_api_keys_key_hash"]
    assert "(key_hash)" in keys["uq_agent_runtime_api_keys_key_hash"]
    assert "(user_id)" in keys["ix_agent_runtime_api_keys_user_id"]


def _seed_populated_rows(db: _Db) -> dict[str, str]:
    ids = {name: str(uuid.uuid4()) for name in ("tenant", "user", "agent", "mission", "task")}
    db.execute(
        f"INSERT INTO tenants (id, code, name, status) VALUES ('{ids['tenant']}', 'pop-tenant', 'Pop', 'active')"
    )
    db.execute(
        f"INSERT INTO users (id, tenant_id, email, display_name, role, status, password_hash) VALUES "
        f"('{ids['user']}', '{ids['tenant']}', 'pop@test.local', 'Pop', 'operator', 'active', 'x')"
    )
    db.execute(
        f"INSERT INTO agents (id, tenant_id, agent_code, display_name, lifecycle_state) VALUES "
        f"('{ids['agent']}', '{ids['tenant']}', 'AGT-POP', 'Pop Agent', 'active')"
    )
    db.execute(
        f"INSERT INTO missions (id, tenant_id, mission_code, title, objective, status, priority, risk_level, budget_policy) "
        f"VALUES ('{ids['mission']}', '{ids['tenant']}', 'MSN-POP', 't', 'o', 'draft', 'normal', 'low', '{{}}')"
    )
    db.execute(
        f"INSERT INTO tasks (id, mission_id, assigned_agent_id, title, instructions, status, retry_count, "
        f"idempotency_key, budget_policy, input_context) VALUES "
        f"('{ids['task']}', '{ids['mission']}', '{ids['agent']}', 't', 'i', 'queued', 0, 'idem-pop', '{{}}', '{{}}')"
    )
    return ids


def test_revision_id_fits_alembic_version_and_chains_onto_the_projects_head():
    script = ScriptDirectory.from_config(_alembic())
    assert len(REVISION) <= 32
    assert script.get_revision(REVISION).down_revision == PARENT_REVISION
    assert len(script.get_heads()) == 1


def test_upgrade_from_an_empty_database_creates_the_three_tables_and_every_index(fresh_database):
    command.upgrade(_alembic(), "head")

    assert NEW_TABLES <= fresh_database.table_names()
    _assert_all_new_indexes(fresh_database)


def test_upgrade_on_a_populated_database_adds_no_column_to_any_existing_table(fresh_database):
    command.upgrade(_alembic(), PARENT_REVISION)
    fresh_database.execute(
        "DROP TABLE IF EXISTS agent_runtime_sessions, agent_runtime_persona_slots, agent_runtime_api_keys CASCADE"
    )
    assert not (NEW_TABLES & fresh_database.table_names())  # the live-database starting state
    ids = _seed_populated_rows(fresh_database)
    columns_before = {t: fresh_database.columns(t) for t in GUARDED_TABLES}

    command.upgrade(_alembic(), "head")

    assert NEW_TABLES <= fresh_database.table_names()
    _assert_all_new_indexes(fresh_database)
    assert {t: fresh_database.columns(t) for t in GUARDED_TABLES} == columns_before
    assert fresh_database.scalar(f"SELECT title FROM missions WHERE id = '{ids['mission']}'") == "t"
    assert fresh_database.scalar(f"SELECT title FROM tasks WHERE id = '{ids['task']}'") == "t"
    assert fresh_database.scalar(f"SELECT role FROM users WHERE id = '{ids['user']}'") == "operator"


def test_downgrade_drops_only_the_three_tables_and_upgrade_restores_them(fresh_database):
    """Downgrades run newest-first in a real alembic history: from `head` (today,
    0004b stacks on top of this migration), downgrading to a named revision undoes
    EVERYTHING after that revision, not just 0004 in isolation -- so this test
    downgrades one named revision at a time (`head` -> 0004 -> 0003c), never a
    relative offset (`-1`), which broke the moment 0004b became the new head (found
    via 0004b's own CI run: `-1` from head then undid 0004b, not 0004)."""
    script = ScriptDirectory.from_config(_alembic())
    command.upgrade(_alembic(), "head")
    assert len(script.get_heads()) == 1
    head_revision = script.get_heads()[0]

    ids = _seed_populated_rows(fresh_database)
    tables_at_head = fresh_database.table_names()

    command.downgrade(_alembic(), REVISION)

    assert fresh_database.current_revision() == REVISION
    assert "agent_runtime_closures" not in fresh_database.table_names()  # 0004b undone
    assert NEW_TABLES <= fresh_database.table_names()  # 0004's own three tables remain
    assert fresh_database.scalar(f"SELECT title FROM tasks WHERE id = '{ids['task']}'") == "t"

    command.downgrade(_alembic(), PARENT_REVISION)

    assert fresh_database.current_revision() == PARENT_REVISION
    dropped = tables_at_head - fresh_database.table_names()
    assert dropped == NEW_TABLES | {"agent_runtime_closures"}  # dropped exactly these, across both steps
    assert fresh_database.table_names() <= tables_at_head  # and created nothing
    assert fresh_database.scalar(f"SELECT title FROM tasks WHERE id = '{ids['task']}'") == "t"  # pre-existing row untouched

    command.upgrade(_alembic(), "head")

    assert fresh_database.current_revision() == head_revision
    assert NEW_TABLES <= fresh_database.table_names()
    assert "agent_runtime_closures" in fresh_database.table_names()
    _assert_all_new_indexes(fresh_database)


def test_the_database_itself_refuses_a_26th_persona_slot(fresh_database):
    command.upgrade(_alembic(), "head")
    tenant = str(uuid.uuid4())
    fresh_database.execute(f"INSERT INTO tenants (id, code, name, status) VALUES ('{tenant}', 'cap-t', 'C', 'active')")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        fresh_database.execute(
            f"INSERT INTO agent_runtime_persona_slots (id, tenant_id, slot, agent_code) "
            f"VALUES ('{uuid.uuid4()}', '{tenant}', 25, 'AGT-CC-OVER')"
        )
