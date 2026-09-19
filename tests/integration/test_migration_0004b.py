"""T2 acceptance test 1: migration `0004b_agent_runtime_closures` adds one NEW table
plus one new partial index on the existing `agent_runtime_sessions` table, and touches
nothing else. Mirrors `tests/integration/test_migration_0004.py`'s own precedent
exactly, including exercising `downgrade()` on a populated database (CI has no
migration round-trip step of its own).
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

REVISION = "0004b_agent_runtime_closures"
PARENT_REVISION = "0004_agent_runtime_sessions"
NEW_TABLES = {"agent_runtime_closures"}
NEW_SESSIONS_INDEX = "ix_agent_runtime_sessions_open"
GUARDED_TABLES = ("missions", "tasks", "agents", "users", "agent_versions", "agent_runtime_sessions")


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
    closures = db.indexdefs("agent_runtime_closures")
    unique_idx = closures["uq_agent_runtime_closures_runtime_session_id"]
    assert "UNIQUE" in unique_idx
    assert "(runtime_session_id)" in unique_idx

    sessions = db.indexdefs("agent_runtime_sessions")
    open_idx = sessions[NEW_SESSIONS_INDEX]
    assert "(kind)" in open_idx
    assert "ended_at IS NULL" in open_idx.split("WHERE")[1]
    # The three indexes 0004 already created must still be present, untouched.
    assert "uq_agent_runtime_sessions_session_ref" in sessions
    assert "uq_agent_runtime_sessions_instance_ref" in sessions
    assert "ix_agent_runtime_sessions_mission_id" in sessions


def _seed_populated_rows(db: _Db) -> dict[str, str]:
    ids = {name: str(uuid.uuid4()) for name in ("tenant", "user", "agent", "mission", "task", "runtime_session")}
    db.execute(
        f"INSERT INTO tenants (id, code, name, status) VALUES ('{ids['tenant']}', 'pop-tenant-b', 'Pop', 'active')"
    )
    db.execute(
        f"INSERT INTO users (id, tenant_id, email, display_name, role, status, password_hash) VALUES "
        f"('{ids['user']}', '{ids['tenant']}', 'pop-b@test.local', 'Pop', 'operator', 'active', 'x')"
    )
    db.execute(
        f"INSERT INTO agents (id, tenant_id, agent_code, display_name, lifecycle_state) VALUES "
        f"('{ids['agent']}', '{ids['tenant']}', 'AGT-POP-B', 'Pop Agent', 'active')"
    )
    db.execute(
        f"INSERT INTO missions (id, tenant_id, mission_code, title, objective, status, priority, risk_level, budget_policy) "
        f"VALUES ('{ids['mission']}', '{ids['tenant']}', 'MSN-POP-B', 't', 'o', 'draft', 'normal', 'low', '{{}}')"
    )
    db.execute(
        f"INSERT INTO tasks (id, mission_id, assigned_agent_id, title, instructions, status, retry_count, "
        f"idempotency_key, budget_policy, input_context) VALUES "
        f"('{ids['task']}', '{ids['mission']}', '{ids['agent']}', 't', 'i', 'queued', 0, 'idem-pop-b', '{{}}', '{{}}')"
    )
    db.execute(
        f"INSERT INTO agent_runtime_sessions (id, tenant_id, kind, agent_id, mission_id, task_id, "
        f"external_session_ref) VALUES "
        f"('{ids['runtime_session']}', '{ids['tenant']}', 'session', '{ids['agent']}', '{ids['mission']}', "
        f"'{ids['task']}', '{uuid.uuid4()}')"
    )
    return ids


def test_revision_id_fits_alembic_version_and_chains_onto_0004():
    script = ScriptDirectory.from_config(_alembic())
    assert len(REVISION) <= 32
    assert script.get_revision(REVISION).down_revision == PARENT_REVISION
    assert len(script.get_heads()) == 1


def test_upgrade_from_an_empty_database_creates_the_table_and_every_index(fresh_database):
    # Revision-targeted, not "head" (defensive per the same lesson T1's own test
    # learned the hard way once a migration lands on top of this one): this file is
    # about 0004b specifically, regardless of what stacks on top of it later.
    command.upgrade(_alembic(), REVISION)

    assert NEW_TABLES <= fresh_database.table_names()
    _assert_all_new_indexes(fresh_database)


def test_upgrade_on_a_populated_database_adds_no_column_to_any_existing_table(fresh_database):
    command.upgrade(_alembic(), PARENT_REVISION)
    fresh_database.execute("DROP TABLE IF EXISTS agent_runtime_closures CASCADE")
    fresh_database.execute(f'DROP INDEX IF EXISTS "{NEW_SESSIONS_INDEX}"')
    assert "agent_runtime_closures" not in fresh_database.table_names()  # the live-database starting state
    ids = _seed_populated_rows(fresh_database)
    columns_before = {t: fresh_database.columns(t) for t in GUARDED_TABLES}

    command.upgrade(_alembic(), REVISION)

    assert NEW_TABLES <= fresh_database.table_names()
    _assert_all_new_indexes(fresh_database)
    assert {t: fresh_database.columns(t) for t in GUARDED_TABLES} == columns_before
    assert fresh_database.scalar(f"SELECT title FROM missions WHERE id = '{ids['mission']}'") == "t"
    assert (
        fresh_database.scalar(f"SELECT kind FROM agent_runtime_sessions WHERE id = '{ids['runtime_session']}'")
        == "session"
    )


def test_downgrade_drops_only_the_new_table_and_index_and_upgrade_restores_them(fresh_database):
    """Same newest-first, by-name discipline as `test_migration_0004.py`: upgrade to
    `head` (today, 0004b IS head) and confirm there is exactly one, then downgrade to
    a named revision rather than a relative offset -- so this stays correct once
    something stacks on top of 0004b too."""
    script = ScriptDirectory.from_config(_alembic())
    command.upgrade(_alembic(), "head")
    assert len(script.get_heads()) == 1
    head_revision = script.get_heads()[0]

    ids = _seed_populated_rows(fresh_database)
    tables_at_head = fresh_database.table_names()

    command.downgrade(_alembic(), PARENT_REVISION)

    assert fresh_database.current_revision() == PARENT_REVISION
    assert tables_at_head - fresh_database.table_names() == NEW_TABLES  # dropped exactly this table
    assert fresh_database.table_names() <= tables_at_head  # and created nothing
    assert NEW_SESSIONS_INDEX not in fresh_database.indexdefs("agent_runtime_sessions")
    assert "uq_agent_runtime_sessions_session_ref" in fresh_database.indexdefs("agent_runtime_sessions")
    assert (
        fresh_database.scalar(f"SELECT kind FROM agent_runtime_sessions WHERE id = '{ids['runtime_session']}'")
        == "session"
    )

    command.upgrade(_alembic(), "head")

    assert fresh_database.current_revision() == head_revision
    assert NEW_TABLES <= fresh_database.table_names()
    _assert_all_new_indexes(fresh_database)


def test_the_database_itself_refuses_a_second_closure_for_one_runtime_session(fresh_database):
    command.upgrade(_alembic(), "head")
    ids = _seed_populated_rows(fresh_database)

    db = fresh_database
    db.execute(
        f"INSERT INTO agent_runtime_closures (id, tenant_id, runtime_session_id, task_id, closed_by, outcome, "
        f"reason_code) VALUES ('{uuid.uuid4()}', '{ids['tenant']}', '{ids['runtime_session']}', '{ids['task']}', "
        f"'hook', 'completed', 'hook_reported')"
    )

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        db.execute(
            f"INSERT INTO agent_runtime_closures (id, tenant_id, runtime_session_id, task_id, closed_by, outcome, "
            f"reason_code) VALUES ('{uuid.uuid4()}', '{ids['tenant']}', '{ids['runtime_session']}', "
            f"'{ids['task']}', 'reaper', 'failed', 'reaped_stale')"
        )


def test_the_database_itself_refuses_an_unknown_closed_by_or_outcome_value(fresh_database):
    command.upgrade(_alembic(), REVISION)
    ids = _seed_populated_rows(fresh_database)

    # 'bogus' fits comfortably inside `closed_by`'s own varchar(16) so the CHECK
    # constraint is what actually fires here -- a too-long value would instead (and
    # did, on the first version of this test) raise a length-truncation error, which
    # proves nothing about the CHECK itself.
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        fresh_database.execute(
            f"INSERT INTO agent_runtime_closures (id, tenant_id, runtime_session_id, task_id, closed_by, outcome, "
            f"reason_code) VALUES ('{uuid.uuid4()}', '{ids['tenant']}', '{ids['runtime_session']}', "
            f"'{ids['task']}', 'bogus', 'completed', 'hook_reported')"
        )

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        fresh_database.execute(
            f"INSERT INTO agent_runtime_closures (id, tenant_id, runtime_session_id, task_id, closed_by, outcome, "
            f"reason_code) VALUES ('{uuid.uuid4()}', '{ids['tenant']}', '{ids['runtime_session']}', "
            f"'{ids['task']}', 'hook', 'bogus', 'hook_reported')"
        )
