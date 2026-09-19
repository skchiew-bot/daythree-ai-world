"""Add projects and mission_projects (ADR-014 decision 1: the platform's first-class
project entity, and the side table a mission links to it through).

Parent revision: `0003b_model_invocations_index` (the real head at the time this
migration was written — PR #24 landed first). No column is added to any existing
table: gate finding F1 established that `create_all(checkfirst=True)` only checks
*table* existence, so a column added to `missions` through this pattern would pass
every model-built test and CI's from-empty `alembic upgrade head`, yet be silently
absent from a live database whose `missions` table already exists. The two tables
below are brand new, so that hazard does not apply to them, but the same
create_all-plus-explicit-index-sweep pattern as 0003/0003b is kept for consistency
and because it is a no-op cost against the alternative of relying purely on
`checkfirst`.

`mission_projects` carries a composite FK `(tenant_id, project_id) ->
projects(tenant_id, id)` (gate finding F4): a mission can never link to another
tenant's project, enforced at the database, not just the API.

`downgrade()` drops both tables in dependent-then-parent order and is exercised by
`tests/integration/test_migration_0003c.py` on a populated database.

Revision ID: 0003c_projects
Revises: 0003b_model_invocations_index
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0003c_projects"
down_revision: Union[str, None] = "0003b_model_invocations_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    for index in models.Project.__table__.indexes:
        index.create(bind=bind, checkfirst=True)
    for index in models.MissionProject.__table__.indexes:
        index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    models.MissionProject.__table__.drop(bind=bind, checkfirst=True)
    models.Project.__table__.drop(bind=bind, checkfirst=True)
