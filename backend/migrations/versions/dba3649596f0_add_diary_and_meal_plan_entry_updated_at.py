"""add diary and meal plan entry updated_at

Revision ID: dba3649596f0
Revises: aac138c38096
Create Date: 2026-07-25 01:59:25.122299

Production-hardening prompt 2's "safe updated_at backfill", for the
entry-version column `SubstitutionApplyIn.expected_updated_at` checks
against (see `models.DiaryEntry.updated_at`'s own docstring). Three
steps, in order, so this is safe to run against a table with real
existing rows without ever violating a NOT NULL constraint mid-flight:

1. Add the column nullable — no existing row is touched, so this step
   alone can never fail regardless of how many rows already exist.
2. Backfill every existing NULL row to a single fixed "now" captured
   once at the start of this migration. There's no real prior mutation
   timestamp to recover for rows that predate this column, so "the
   moment this migration ran" is the most honest available value — it
   correctly means "unknown, but not stale as of right now," which is
   exactly the semantics `expected_updated_at` needs (nothing served to
   a client before this migration ran could have captured a value that
   would ever incorrectly match or mismatch a backfilled row, since no
   `current_entry_updated_at` existed to serve before this migration).
3. Add the NOT NULL constraint — safe now that step 2 guarantees no row
   is left NULL.

On a fresh database (this migration running immediately after the
baseline with zero rows in either table), step 2 is a no-op — there's
nothing to backfill — and the whole thing behaves exactly like a single
`ADD COLUMN ... NOT NULL`."""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dba3649596f0'
down_revision: Union[str, None] = 'aac138c38096'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("diary_entries", "meal_plan_entries")


def upgrade() -> None:
    """Upgrade schema."""
    backfill_at = datetime.now(timezone.utc)

    for table in _TABLES:
        op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    for table in _TABLES:
        op.execute(
            sa.text(f"UPDATE {table} SET updated_at = :backfill_at WHERE updated_at IS NULL")
            .bindparams(backfill_at=backfill_at)
        )

    for table in _TABLES:
        op.alter_column(table, "updated_at", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    for table in _TABLES:
        op.drop_column(table, "updated_at")
