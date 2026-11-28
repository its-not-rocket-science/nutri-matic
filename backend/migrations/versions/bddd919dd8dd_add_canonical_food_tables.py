"""add canonical food tables

Revision ID: bddd919dd8dd
Revises: 473bba7cef14
Create Date: 2026-11-28 00:00:00.000000

Canonical foods plan (docs/plans/canonical-foods-plan.md), PR 4a, section
3.5: creates the four canonical_* tables and their indexes. Purely
additive: no existing table or column is altered and `foods` is not
written, so the FDC catalogue checksum is unchanged. downgrade() drops them.

The CHECK vocabularies are written out literally (not imported from
app.models) so this revision keeps meaning what it meant when it was
written.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bddd919dd8dd'
down_revision: Union[str, None] = '473bba7cef14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREPARATION_STATES = (
    "'unspecified', 'raw', 'dry', 'soaked', 'sprouted', 'cooked_boiled', 'canned_drained', "
    "'canned_with_liquid', 'frozen', 'roasted', 'fried', 'dehydrated'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'canonical_foods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('concept', sa.String(), nullable=False),
        sa.Column('preparation_state', sa.String(), nullable=False),
        sa.Column('display_name_en_gb', sa.String(), nullable=False),
        sa.Column('display_name_en_us', sa.String(), nullable=True),
        sa.Column('default_food_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('review_ref', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"preparation_state IN ({_PREPARATION_STATES})", name='ck_canonical_food_preparation_state'),
        sa.CheckConstraint("status IN ('active', 'retired')", name='ck_canonical_food_status'),
        sa.ForeignKeyConstraint(['default_food_id'], ['foods.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_canonical_foods_concept'), 'canonical_foods', ['concept'], unique=False)

    op.create_table(
        'canonical_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical_food_id', sa.Integer(), nullable=False),
        sa.Column('alias', sa.String(), nullable=False),
        sa.Column('locale', sa.String(), nullable=False),
        sa.Column('relationship', sa.String(), nullable=False),
        sa.Column('display_note', sa.String(), nullable=True),
        sa.CheckConstraint("locale IN ('en-GB', 'en-US', '*')", name='ck_canonical_alias_locale'),
        sa.CheckConstraint(
            "relationship IN ('exact', 'regional_equivalent', 'close_analogue', 'category_proxy')",
            name='ck_canonical_alias_relationship',
        ),
        sa.ForeignKeyConstraint(['canonical_food_id'], ['canonical_foods.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('locale', 'alias', 'canonical_food_id', name='uq_canonical_alias_locale_alias_food'),
    )
    op.create_index(
        op.f('ix_canonical_aliases_canonical_food_id'), 'canonical_aliases', ['canonical_food_id'], unique=False,
    )
    op.create_index('ix_canonical_aliases_lower_alias', 'canonical_aliases', [sa.text('lower(alias)')], unique=False)

    op.create_table(
        'canonical_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical_food_id', sa.Integer(), nullable=False),
        sa.Column('food_id', sa.Integer(), nullable=False),
        sa.Column('match_method', sa.String(), nullable=False),
        sa.Column('confidence', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.CheckConstraint("confidence IN ('high', 'medium', 'low')", name='ck_canonical_member_confidence'),
        sa.CheckConstraint("role IN ('anchor', 'member', 'excluded')", name='ck_canonical_member_role'),
        sa.ForeignKeyConstraint(['canonical_food_id'], ['canonical_foods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['food_id'], ['foods.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_food_id', 'food_id', name='uq_canonical_member_food'),
    )
    op.create_index(op.f('ix_canonical_members_food_id'), 'canonical_members', ['food_id'], unique=False)

    op.create_table(
        'canonical_typical_values',
        sa.Column('canonical_food_id', sa.Integer(), nullable=False),
        sa.Column('nutrient_key', sa.String(), nullable=False),
        sa.Column('median', sa.Float(), nullable=False),
        sa.Column('p25', sa.Float(), nullable=True),
        sa.Column('p75', sa.Float(), nullable=True),
        sa.Column('n_members', sa.Integer(), nullable=False),
        sa.Column('computed_from_catalogue_checksum', sa.String(), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['canonical_food_id'], ['canonical_foods.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('canonical_food_id', 'nutrient_key'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('canonical_typical_values')
    op.drop_index(op.f('ix_canonical_members_food_id'), table_name='canonical_members')
    op.drop_table('canonical_members')
    op.drop_index('ix_canonical_aliases_lower_alias', table_name='canonical_aliases')
    op.drop_index(op.f('ix_canonical_aliases_canonical_food_id'), table_name='canonical_aliases')
    op.drop_table('canonical_aliases')
    op.drop_index(op.f('ix_canonical_foods_concept'), table_name='canonical_foods')
    op.drop_table('canonical_foods')
