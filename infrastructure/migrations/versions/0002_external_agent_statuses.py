"""Add external_agent_statuses (see ExternalAgentStatus in common.db.models).

Same approach as 0001: delegates to `Base.metadata.create_all(checkfirst=True)`
rather than a hand-written `op.create_table`, so it stays byte-for-byte faithful to
the model. `checkfirst=True` means this only creates the one new table — everything
from 0001 already exists.

Revision ID: 0002_external_agent_statuses
Revises: 0001_initial_schema
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0002_external_agent_statuses"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    models.ExternalAgentStatus.__table__.drop(bind=bind, checkfirst=True)
