"""Add `agent_runtime_closures` (Digital Twin Program T2: twin lifecycle closure,
reaper, SessionEnd) plus one partial index on the existing `agent_runtime_sessions`
table for the reaper's own scan.

Parent revision: `0004_agent_runtime_sessions`. Numbered `0004b` (not `0005`) on
purpose, mirroring `0003b_model_invocations_index`'s precedent: it keeps the reserved
`0005`..`0008` names free for the ADR-011/012/013 migrations already planned.

No column is added to any existing table (T2 hard constraint, mirroring gate finding
T1-F1): `agent_runtime_closures` is a brand-new table, and the one change to
`agent_runtime_sessions` is an ADDITIONAL index, never an ALTER ... ADD COLUMN. As
with `0003b`, `create_all(checkfirst=True)` only checks *table* existence, so on a
database where `agent_runtime_sessions` already exists it would silently skip this
new index — each index is therefore created individually with its own
`checkfirst=True`, a no-op for the three indexes `0004` already created and the one
real effect for the new partial index declared on the model.

`downgrade()` drops the new partial index, then the new table, and is exercised by
`tests/integration/test_migration_0004b.py` on a populated database (same discipline
as `tests/integration/test_migration_0004.py`).

Revision ID: 0004b_agent_runtime_closures
Revises: 0004_agent_runtime_sessions
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0004b_agent_runtime_closures"
down_revision: Union[str, None] = "0004_agent_runtime_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = (models.AgentRuntimeClosure.__table__,)
_NEW_SESSIONS_INDEX_NAME = "ix_agent_runtime_sessions_open"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    for table in _NEW_TABLES:
        for index in table.indexes:
            index.create(bind=bind, checkfirst=True)
    # The operator-approved partial index on the T1 table -- per-index checkfirst
    # sweep so the three indexes `0004` already created are a no-op here and only the
    # new one (declared on the model, not yet created on a live database) is added.
    for index in models.AgentRuntimeSession.__table__.indexes:
        index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    new_index = next(
        i for i in models.AgentRuntimeSession.__table__.indexes if i.name == _NEW_SESSIONS_INDEX_NAME
    )
    new_index.drop(bind=bind, checkfirst=True)
    for table in _NEW_TABLES:
        table.drop(bind=bind, checkfirst=True)
