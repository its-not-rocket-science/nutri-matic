"""preserve censored compound observations

Revision ID: 076155f11b60
Revises: 4cdb265fe305
Create Date: 2026-08-21 00:00:00.000000

Prompt 5 of the phytate/mineral-bioavailability extension (see
prompts.txt). Extends CompoundObservation so a censored/non-numeric
source cell ("< LOD", "trace", a blank cell) can be preserved with its
own provenance instead of being silently dropped (the adapter's prior
behaviour) or coerced to 0 (never done, but now impossible to do by
accident too, since value_qualifier makes the distinction explicit).

original_value becomes nullable — a censored observation has no number
to store there at all. Every pre-existing row is a real measured value,
so the backfill below sets original_value_text/value_qualifier/
original_value_provenance to reproduce exactly what those rows already
represent (a source-reported number), never reinterpreting any of them
as censored.

New NOT NULL columns (original_value_text, value_qualifier) are added
nullable first, backfilled, then tightened — the standard pattern for
adding a NOT NULL column to a populated table without a lock-heavy
single-statement default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '076155f11b60'
down_revision: Union[str, None] = '4cdb265fe305'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

compound_observations = sa.table(
    'compound_observations',
    sa.column('original_value', sa.Float()),
    sa.column('original_value_text', sa.String()),
    sa.column('value_qualifier', sa.String()),
    sa.column('original_value_provenance', sa.String()),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('compound_observations', 'original_value', existing_type=sa.Float(), nullable=True)

    op.add_column('compound_observations', sa.Column('original_value_text', sa.String(), nullable=True))
    op.add_column('compound_observations', sa.Column('value_qualifier', sa.String(), nullable=True))
    op.add_column('compound_observations', sa.Column('detection_limit_value', sa.Float(), nullable=True))
    op.add_column('compound_observations', sa.Column('detection_limit_unit', sa.String(), nullable=True))
    op.add_column('compound_observations', sa.Column('original_value_provenance', sa.String(), nullable=True))

    # Backfill: every existing row is a real, source-reported number —
    # reproduce that exactly, never reinterpret any existing row as
    # censored.
    op.execute(
        compound_observations.update().values(
            original_value_text=sa.func.cast(compound_observations.c.original_value, sa.String()),
            value_qualifier='measured',
            original_value_provenance='source_reported',
        )
    )

    op.alter_column('compound_observations', 'original_value_text', existing_type=sa.String(), nullable=False)
    op.alter_column('compound_observations', 'value_qualifier', existing_type=sa.String(), nullable=False)

    op.create_check_constraint(
        'ck_compound_observation_value_qualifier', 'compound_observations',
        "value_qualifier IN ('measured', 'reported_zero', 'below_detection_limit', "
        "'below_quantification_limit', 'trace', 'not_reported', 'unparseable')",
    )
    op.create_check_constraint(
        'ck_compound_observation_value_qualifier_pairing', 'compound_observations',
        "(value_qualifier IN ('measured', 'reported_zero') "
        "AND original_value IS NOT NULL AND original_value_provenance IS NOT NULL) "
        "OR (value_qualifier NOT IN ('measured', 'reported_zero') "
        "AND original_value IS NULL AND original_value_provenance IS NULL)",
    )
    op.create_check_constraint(
        'ck_compound_observation_original_value_provenance', 'compound_observations',
        "original_value_provenance IS NULL "
        "OR original_value_provenance IN ('source_reported', 'converted', 'imputed')",
    )
    op.create_check_constraint(
        'ck_compound_observation_detection_limit_pairing', 'compound_observations',
        "(detection_limit_value IS NULL AND detection_limit_unit IS NULL) "
        "OR (detection_limit_value IS NOT NULL AND detection_limit_unit IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_compound_observation_detection_limit_pairing', 'compound_observations', type_='check')
    op.drop_constraint('ck_compound_observation_original_value_provenance', 'compound_observations', type_='check')
    op.drop_constraint('ck_compound_observation_value_qualifier_pairing', 'compound_observations', type_='check')
    op.drop_constraint('ck_compound_observation_value_qualifier', 'compound_observations', type_='check')

    op.drop_column('compound_observations', 'original_value_provenance')
    op.drop_column('compound_observations', 'detection_limit_unit')
    op.drop_column('compound_observations', 'detection_limit_value')
    op.drop_column('compound_observations', 'value_qualifier')
    op.drop_column('compound_observations', 'original_value_text')

    # Only safe if no row is currently censored (original_value NULL) —
    # a downgrade after real censored data has been ingested must fail
    # here rather than silently losing which rows were censored.
    op.alter_column('compound_observations', 'original_value', existing_type=sa.Float(), nullable=False)
