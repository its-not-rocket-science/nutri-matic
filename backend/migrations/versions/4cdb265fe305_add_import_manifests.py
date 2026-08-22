"""add import manifests

Revision ID: 4cdb265fe305
Revises: 2c049f319235
Create Date: 2026-08-21 00:00:00.000000

Prompt 2 of the phytate/mineral-bioavailability extension (see
prompts.txt). A generic, source-agnostic table recording a deterministic
snapshot of one externally-sourced dataset/catalogue — starting with the
USDA FDC Food catalogue backing the phytate reviewed-mapping resolver
(app.catalogue_manifest), but not phytate-specific: any later source
gets its own manifest rows without a schema change.

Purely additive — a new table, no existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cdb265fe305'
down_revision: Union[str, None] = '2c049f319235'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'import_manifests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_name', sa.String(), nullable=False),
        sa.Column('release_version', sa.String(), nullable=False),
        sa.Column('import_date', sa.Date(), nullable=False),
        sa.Column('checksum', sa.String(), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('importer_version', sa.String(), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_name', 'checksum', name='uq_import_manifest_source_checksum'),
    )
    op.create_index(
        op.f('ix_import_manifests_source_name'), 'import_manifests', ['source_name'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_import_manifests_source_name'), table_name='import_manifests')
    op.drop_table('import_manifests')
