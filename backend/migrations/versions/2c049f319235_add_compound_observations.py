"""add compound observations

Revision ID: 2c049f319235
Revises: 9e87917ddcb3
Create Date: 2026-08-04 18:19:13.237428

Prompt 2 of the phytate/mineral-bioavailability extension (see
prompts.txt, docs/phytate-evidence-review.md). A generic table for
"how much of some dietary compound does this food contain, per one
external dataset" — not phytate-specific, so a later compound (out of
scope for this migration) can reuse it by adding rows with a new
`compound` value rather than needing a schema change.

Purely additive — a new table, no existing table touched. See
app/models.py's CompoundObservation for the field-by-field rationale
(original-vs-normalised value pairs kept separate so the original is
always recoverable, match_relationship reusing
RecipeIngredientProvenance's AliasRelationship vocabulary plus
"needs_review", matched_food_id nullable so an unmatched observation is
still stored rather than discarded).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c049f319235'
down_revision: Union[str, None] = '9e87917ddcb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'compound_observations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('compound', sa.String(), nullable=False),
        sa.Column('compound_fraction', sa.String(), nullable=True),
        sa.Column('original_value', sa.Float(), nullable=False),
        sa.Column('original_unit', sa.String(), nullable=False),
        sa.Column('original_basis', sa.String(), nullable=False),
        sa.Column('normalised_value', sa.Float(), nullable=True),
        sa.Column('normalised_unit', sa.String(), nullable=True),
        sa.Column('normalised_basis', sa.String(), nullable=True),
        sa.Column('normalisation_method', sa.String(), nullable=True),
        sa.Column('source_food_description', sa.String(), nullable=False),
        sa.Column('source_preparation_state', sa.String(), nullable=True),
        sa.Column('source_dataset_name', sa.String(), nullable=False),
        sa.Column('source_dataset_citation', sa.String(), nullable=False),
        sa.Column('source_dataset_version', sa.String(), nullable=False),
        sa.Column('source_access_date', sa.Date(), nullable=False),
        sa.Column('analytical_method', sa.String(), nullable=True),
        sa.Column('source_row_identifier', sa.String(), nullable=True),
        sa.Column('match_relationship', sa.String(), nullable=False),
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('match_rationale', sa.String(), nullable=True),
        sa.Column('matched_food_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "match_relationship IN ('exact', 'regional_equivalent', 'close_analogue', "
            "'category_proxy', 'needs_review')",
            name='ck_compound_observation_match_relationship',
        ),
        sa.CheckConstraint(
            '(normalised_value IS NULL AND normalised_unit IS NULL AND normalised_basis IS NULL '
            'AND normalisation_method IS NULL) '
            'OR (normalised_value IS NOT NULL AND normalised_unit IS NOT NULL AND normalised_basis IS NOT NULL '
            'AND normalisation_method IS NOT NULL)',
            name='ck_compound_observation_normalised_all_or_none',
        ),
        sa.ForeignKeyConstraint(['matched_food_id'], ['foods.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'compound', 'source_dataset_name', 'source_dataset_version', 'source_row_identifier',
            name='uq_compound_observation_source_row',
        ),
    )
    op.create_index(op.f('ix_compound_observations_compound'), 'compound_observations', ['compound'], unique=False)
    op.create_index(
        'ix_compound_observations_compound_food', 'compound_observations', ['compound', 'matched_food_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_compound_observations_matched_food_id'), 'compound_observations', ['matched_food_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_compound_observations_matched_food_id'), table_name='compound_observations')
    op.drop_index('ix_compound_observations_compound_food', table_name='compound_observations')
    op.drop_index(op.f('ix_compound_observations_compound'), table_name='compound_observations')
    op.drop_table('compound_observations')
