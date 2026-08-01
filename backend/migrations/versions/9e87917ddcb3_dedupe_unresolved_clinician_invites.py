"""dedupe unresolved clinician invites

Revision ID: 9e87917ddcb3
Revises: 096f80b058ab
Create Date: 2026-08-01 10:00:00.000000

Caught by PR review on 096f80b058ab: clinician_client_links' existing
unique constraint is on (clinician_user_id, client_user_id), and most
DBs treat every NULL as distinct for uniqueness — so two concurrent
POST /invites for the same unregistered email from the same clinician
could both be created with client_user_id still NULL. Both would later
try to resolve to the same client_user_id the moment that email
registers (see routers/auth.py's register()) and collide with that same
constraint, returning a 500 that blocks the new account from being
created at all, not just the invite.

Adds a partial unique index on (clinician_user_id, invite_email),
enforced only while client_user_id IS NULL — a resolved/active/revoked
link is never constrained by it. Before creating the index, de-dupes
any row that already violates it (there's no ordering guarantee for
which invite "should" win a race that already happened, so this keeps
the most recently created one per (clinician_user_id, invite_email) and
deletes the rest — the deleted rows' tokens were only ever useful to
whoever received that specific email, and a fresh invite can always be
sent again)."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e87917ddcb3'
down_revision: Union[str, None] = '096f80b058ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        DELETE FROM clinician_client_links
        WHERE client_user_id IS NULL
          AND id NOT IN (
              SELECT MAX(id) FROM clinician_client_links
              WHERE client_user_id IS NULL
              GROUP BY clinician_user_id, invite_email
          )
        """
    )
    op.create_index(
        'uq_clinician_invite_email_unresolved', 'clinician_client_links', ['clinician_user_id', 'invite_email'],
        unique=True, postgresql_where=sa.text('client_user_id IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_clinician_invite_email_unresolved', table_name='clinician_client_links')
