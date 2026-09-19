"""Add `agent_runtime_sessions`, `agent_runtime_persona_slots` and `agent_runtime_api_keys`
(ADR-010 Phase A / Digital Twin Program T1: registering Claude Code sessions and subagent
spawns as governed objects behind a scoped credential).

Parent revision: `0003c_projects` (the real head when this was written; re-point
`down_revision` if another migration merges first). No column is added to any existing
table (gate finding T1-F1): `create_all(checkfirst=True)` only checks *table* existence, so
a column added to `missions`/`tasks`/`agents` this way would pass every model-built test and
CI's from-empty `alembic upgrade head`, yet be silently absent from a live database whose
table already exists. That is also why "is this an agent-runtime mission" is an EXISTS
against `agent_runtime_sessions` rather than a `source` column on `missions`.

The same create_all-plus-explicit-index-sweep pattern as 0003/0003b/0003c is kept. The
unique constraints (`uq_agent_runtime_persona_slots_*`, `uq_agent_runtime_api_keys_key_hash`)
and the CHECK that caps a tenant at 25 persona slots are part of each table's own DDL.

`downgrade()` drops only these three tables, dependent-then-parent order, and is exercised
by `tests/integration/test_migration_0004.py` on a populated database. It does not delete
the `agent_runtime` service `users` rows the issue script may have created.

Revision ID: 0004_agent_runtime_sessions
Revises: 0003c_projects
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0004_agent_runtime_sessions"
down_revision: Union[str, None] = "0003c_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = (
    models.AgentRuntimeSession.__table__,
    models.AgentRuntimePersonaSlot.__table__,
    models.AgentRuntimeApiKey.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    for table in _NEW_TABLES:
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in _NEW_TABLES:
        table.drop(bind=bind, checkfirst=True)
