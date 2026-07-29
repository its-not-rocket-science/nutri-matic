"""add profile goals

Revision ID: 19c243569c7d
Revises: 92158621e2f3
Create Date: 2026-07-29 15:19:29.427706

Prompt 2.1: a profile can now hold a set of goals (ranked by priority)
instead of exactly one. Purely additive — `profiles.goal` (the existing
single-value column) is untouched and stays populated as a mirror of
whichever goal is priority 1 (see app/goals.py's replace_goals()); no
existing row's data is reinterpreted or dropped.

Two steps:
1. Create `profile_goals` (profile_id, goal, priority), unique on
   (profile_id, goal) and on (profile_id, priority).
2. Backfill: every existing profile with a non-null `goal` gets exactly
   one row, priority=1, goal=<that value> — the same value app/goals.py's
   fallback (`goal_keys_of()`) would already treat it as if this table
   were empty, so this step is "make explicit what was already implied,"
   not a reinterpretation. A profile with goal IS NULL gets no row (an
   empty goal set), which is what NULL already meant.

Application code (app/goals.py, app/energy_goal.py, routers/profiles.py)
reads this table as the real source of truth going forward; `profiles.
goal` is kept in sync by every write path but nothing reads it as
authoritative anymore except a defensive fallback for a Profile object
that was never attached to a request-scoped goal set (see
goals.goal_keys_of's docstring)."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19c243569c7d'
down_revision: Union[str, None] = '92158621e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'profile_goals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('goal', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id', 'goal', name='uq_profile_goal'),
        sa.UniqueConstraint('profile_id', 'priority', name='uq_profile_goal_priority'),
    )
    op.create_index(op.f('ix_profile_goals_profile_id'), 'profile_goals', ['profile_id'], unique=False)

    op.execute(
        """
        INSERT INTO profile_goals (profile_id, goal, priority)
        SELECT id, goal, 1 FROM profiles WHERE goal IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_profile_goals_profile_id'), table_name='profile_goals')
    op.drop_table('profile_goals')
