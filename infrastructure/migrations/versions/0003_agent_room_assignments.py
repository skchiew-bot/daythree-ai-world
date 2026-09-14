"""Add agent_room_assignments (ADR-009: 20-room, 5-floor x 4-room per-tenant
apartment for governed agents — see AgentRoomAssignment in common.db.models).

Same create_all(checkfirst=True) delegation as 0001/0002, but followed by an
explicit per-index create sweep: create_all's checkfirst only checks *table*
existence, not index existence, so if this table already existed for any reason
the two partial unique indexes (the actual concurrency guarantee for this
feature) would be silently skipped. Creating each index individually with its own
checkfirst=True closes that gap.

Revision ID: 0003_agent_room_assignments
Revises: 0002_external_agent_statuses
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0003_agent_room_assignments"
down_revision: Union[str, None] = "0002_external_agent_statuses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    for index in models.AgentRoomAssignment.__table__.indexes:
        index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    models.AgentRoomAssignment.__table__.drop(bind=bind, checkfirst=True)
