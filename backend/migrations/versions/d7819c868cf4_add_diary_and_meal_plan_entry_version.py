"""add diary and meal plan entry version

Revision ID: d7819c868cf4
Revises: dba3649596f0
Create Date: 2026-07-25 13:44:43.608979

Production-hardening prompt 3: replaces the timestamp-based optimistic-
concurrency check (`updated_at`, previous migration) with a plain
integer row-version for `SubstitutionApplyIn.expected_version` to
compare against.

Unlike `updated_at`, this doesn't need the nullable→backfill→NOT NULL
dance: every row's correct backfill value is the same constant (1,
"never yet mutated by anything version-aware"), not a per-row-varying
"whenever this row happened to last change." A single `ADD COLUMN ...
NOT NULL DEFAULT 1` is both correct and — on Postgres 11+ — a fast,
metadata-only operation for a constant default; it doesn't rewrite the
table the way a per-row backfill would.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7819c868cf4'
down_revision: Union[str, None] = 'dba3649596f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("diary_entries", "meal_plan_entries")


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    """Downgrade schema."""
    for table in _TABLES:
        op.drop_column(table, "version")
