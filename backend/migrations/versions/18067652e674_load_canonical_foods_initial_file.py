"""load canonical foods (initial file: plan queries and recipe aliases)

Revision ID: 18067652e674
Revises: 348add18915d
Create Date: 2026-11-28 00:00:00.000000

Data migration: loads the reviewed app/canonical_foods/canonical_foods_en_gb.csv
(canonical foods PR 4b: the plan 1.2 queries plus the UK entries of
stock_recipes/ingredient_aliases.py, anchors only) through
app.canonical_foods.loader, exactly as 348add18915d did for the six 4a
rows. The load is replace-by-key, so the six rows already in production
are kept or updated, never duplicated.

Pinned to the file's checksum; see 348add18915d for why. Skipped on a
database with no FDC catalogue rows; otherwise any failed check aborts the
migration and nothing is written. Never writes `foods`.

downgrade() empties the canonical tables. The previous revision's file is
not kept, and the code before PR 4b does not read these tables, so an empty
set is the safe state to go back to. Upgrading again reloads the file.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '18067652e674'
down_revision: Union[str, None] = '348add18915d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CSV_SHA256 = "2a2eb670c92415c0be55305fb7400d4050fbcbb5913b4203f10025b5c88c84d8"


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
