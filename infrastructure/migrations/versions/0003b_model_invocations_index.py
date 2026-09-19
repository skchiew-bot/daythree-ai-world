"""Index model_invocations for per-task usage and per-(tenant, agent, time) spend
lookups (R0, ADR-013).

The budget check now sums a task's invocations before every model call, and metering
(ADR-013 R1+) sums an agent's spend over a period; without these indexes both scan the
whole table.

Numbered `0003b` on purpose: it keeps 0004 to 0008 free for the ADR-010/011/012/013
migrations already planned. Follows the ADR-009 (0003) pattern: `create_all(checkfirst=True)`
only checks *table* existence, so on a database whose `model_invocations` already exists
it would silently skip the new indexes. Each index is therefore created individually with
its own `checkfirst=True`, which is a no-op where 0001's `create_all` already built it.

Revision ID: 0003b_model_invocations_index
Revises: 0003_agent_room_assignments
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0003b_model_invocations_index"
down_revision: Union[str, None] = "0003_agent_room_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    for index in models.ModelInvocation.__table__.indexes:
        index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for index in models.ModelInvocation.__table__.indexes:
        index.drop(bind=bind, checkfirst=True)
