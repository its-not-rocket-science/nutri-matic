"""add user demo lifecycle fields

Revision ID: 92158621e2f3
Revises: d7819c868cf4
Create Date: 2026-07-26 00:00:00.000000

Public-launch hardening prompt 2: adds `is_demo` and `expires_at` to
`users`, so a demo account (see app/demo_data.py) has a first-class,
enforced lifetime instead of living forever.

Deliberately mechanical and non-destructive — this migration does NOT
attempt to identify or mark any EXISTING demo account created before
this column existed. `is_demo` defaults to `false` for every existing
row (both real users and any pre-existing demo accounts from manual
testing — see this repo's EXECUTION SAFETY REQUIREMENTS: production
already contains real demo accounts from before this feature). That is
correct and safe for real users; it under-marks any pre-existing demo
account, which is the safe direction to be wrong in — an unmarked demo
account just keeps behaving as it always has (indefinitely usable)
until identified, rather than an incorrectly-marked real account being
expired/purged.

Identifying and marking pre-existing demo accounts is a deliberately
SEPARATE, human-reviewed step — `python -m app.backfill_demo_flag`
(dry-run by default; see that module's docstring and
docs/demo-lifecycle.md) — not folded into this migration's upgrade(),
because doing so reliably requires inspecting the actual current
contents of the production users table, which cannot be verified from
here. Same two-step shape this repo already uses for
app/migrate_profiles.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92158621e2f3'
down_revision: Union[str, None] = 'd7819c868cf4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "expires_at")
    op.drop_column("users", "is_demo")
