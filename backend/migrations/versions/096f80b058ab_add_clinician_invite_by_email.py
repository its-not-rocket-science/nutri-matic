"""add clinician invite by email

Revision ID: 096f80b058ab
Revises: 19c243569c7d
Create Date: 2026-08-01 09:00:00.000000

Lets a clinician invite someone who doesn't have a Nutri-Matic account
yet. clinician_client_links.client_user_id becomes nullable (an
unregistered invite has no user to point at until they register) and
three new nullable columns are added: invite_email (who was invited),
invite_token (unguessable, used by the public /invite/{token} preview
page and by registration to auto-resolve client_user_id), and
invite_message (the clinician's own wording, sent verbatim in the
email). Purely additive — no existing row's client_user_id is touched,
and every existing row already satisfies NOT NULL so relaxing the
constraint changes nothing about data already there."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '096f80b058ab'
down_revision: Union[str, None] = '19c243569c7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('clinician_client_links', 'client_user_id', existing_type=sa.Integer(), nullable=True)
    op.add_column('clinician_client_links', sa.Column('invite_email', sa.String(), nullable=True))
    op.add_column('clinician_client_links', sa.Column('invite_token', sa.String(), nullable=True))
    op.add_column('clinician_client_links', sa.Column('invite_message', sa.String(), nullable=True))
    op.create_index(
        op.f('ix_clinician_client_links_invite_token'), 'clinician_client_links', ['invite_token'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema.

    Any row with client_user_id still NULL (an invite nobody has
    registered against yet) cannot survive re-tightening the NOT NULL
    constraint — deleted here rather than left to fail the ALTER
    outright, same tradeoff this repo's other destructive downgrades
    document rather than hide (see docs/migrations.md)."""
    op.execute("DELETE FROM clinician_client_links WHERE client_user_id IS NULL")
    op.drop_index(op.f('ix_clinician_client_links_invite_token'), table_name='clinician_client_links')
    op.drop_column('clinician_client_links', 'invite_message')
    op.drop_column('clinician_client_links', 'invite_token')
    op.drop_column('clinician_client_links', 'invite_email')
    op.alter_column('clinician_client_links', 'client_user_id', existing_type=sa.Integer(), nullable=False)
