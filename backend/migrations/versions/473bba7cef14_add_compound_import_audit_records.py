"""add compound import audit records

Revision ID: 473bba7cef14
Revises: 076155f11b60
Create Date: 2026-08-24 02:43:08.881545

Prompt 10 of the phytate/mineral-bioavailability extension (see
prompts.txt). An immutable audit row for one real (--apply) reviewed
compound import — never written for a dry run, see
CompoundImportAuditRecord's own docstring in app.models. Source-agnostic
by construction (compound/source_key columns, not phytate-specific), same
reasoning as CompoundObservation and ImportManifest before it.

Purely additive — a new table, no existing table touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '473bba7cef14'
down_revision: Union[str, None] = '076155f11b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'compound_import_audit_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('compound', sa.String(), nullable=False),
        sa.Column('source_key', sa.String(), nullable=False),
        sa.Column('dataset_version', sa.String(), nullable=False),
        sa.Column('licence_status_at_import', sa.String(), nullable=False),
        sa.Column('destination_surface', sa.String(), nullable=False),
        sa.Column('workbook_checksum', sa.String(), nullable=False),
        sa.Column('catalogue_checksum', sa.String(), nullable=False),
        sa.Column('importer_version', sa.String(), nullable=False),
        sa.Column('operator_confirmed_dataset_version', sa.String(), nullable=False),
        sa.Column('operator_confirmed_workbook_checksum', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_compound_import_audit_records_compound'),
        'compound_import_audit_records', ['compound'], unique=False,
    )
    op.create_index(
        op.f('ix_compound_import_audit_records_source_key'),
        'compound_import_audit_records', ['source_key'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_compound_import_audit_records_source_key'), table_name='compound_import_audit_records')
    op.drop_index(op.f('ix_compound_import_audit_records_compound'), table_name='compound_import_audit_records')
    op.drop_table('compound_import_audit_records')
