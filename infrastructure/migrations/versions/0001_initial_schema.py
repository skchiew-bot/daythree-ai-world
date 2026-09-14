"""Initial schema — all 11 Phase 0 tables (spec §8).

Hand-authored rather than `alembic revision --autogenerate` because this migration was
written while Docker Desktop was not running in the build environment, so no live
Postgres was available to diff against. To guarantee the migration is byte-for-byte
faithful to `common.db.models` (the single source of truth) rather than a manually
retyped copy that could drift, this migration delegates to
`Base.metadata.create_all`/`drop_all` instead of a hand-written sequence of
`op.create_table(...)` calls. Once this has been run once against a real Postgres, any
future *change* to a model should be captured with a normal
`alembic revision --autogenerate` (which will diff against this baseline).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op

from common.db import models  # noqa: F401  (registers tables on Base.metadata)
from common.db.base import Base

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
