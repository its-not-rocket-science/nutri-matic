"""load canonical foods (initial reviewed rows)

Revision ID: 348add18915d
Revises: bddd919dd8dd
Create Date: 2026-11-28 00:00:00.000000

Data migration (owner's answer to plan Q5): loads
app/canonical_foods/canonical_foods_en_gb.csv through
app.canonical_foods.loader, so the load is rehearsed against the restored
production dump before the deploy approval gate.

Pinned to the file's checksum. Every reviewed edit to the CSV ships as a
new data migration like this one with the new CSV_SHA256 (tests/
test_canonical_foods.py fails until it does). When the file on disk no
longer matches this pin, a later data migration owns the load and this one
does nothing, so replaying the chain on a fresh database loads the current
file exactly once, in the newest data migration.

Skipped (not failed) on a database with no FDC catalogue rows (CI, a fresh
dev database). Otherwise any check failure (missing or wrong anchor, bad
row) aborts the whole migration and nothing is written.

Never writes `foods`; the catalogue checksum is unchanged.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '348add18915d'
down_revision: Union[str, None] = 'bddd919dd8dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CSV_SHA256 = "PENDING-REVIEW"


def upgrade() -> None:
    from app.canonical_foods.csv_schema import file_sha256, load_file
    from app.canonical_foods.loader import load

    current = file_sha256()
    if current != CSV_SHA256:
        print(f"canonical foods: file sha256 {current} is not this revision's pin; a later revision loads it")
        return
    db = Session(bind=op.get_bind())
    result = load(db, load_file())
    db.flush()
    print(result.summary())


def downgrade() -> None:
    op.execute("DELETE FROM canonical_typical_values")
    op.execute("DELETE FROM canonical_members")
    op.execute("DELETE FROM canonical_aliases")
    op.execute("DELETE FROM canonical_foods")
