"""load canonical foods (adds sugar, oil, salt and other staple canonicals)

Revision ID: cf2908ff260e
Revises: 5085bc12af5a
Create Date: 2026-11-28 00:00:00.000000

Data migration: reloads the reviewed app/canonical_foods/canonical_foods_en_gb.csv
through app.canonical_foods.loader, as 18067652e674 did. This revision's
file adds 23 canonicals anchored on the protein-free SR staples that
5085bc12af5a inserts, and changes no existing canonical, so the load
creates those 23 and leaves the other 122 unchanged.

Pinned to the file's sha256; see 348add18915d for the pattern. Skipped on
a database with no FDC catalogue rows.

downgrade() removes exactly the 23 canonicals this revision added (and
their aliases and anchors), which is the state 18067652e674 left, so the
staples migration below can then be downgraded too.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'cf2908ff260e'
down_revision: Union[str, None] = '5085bc12af5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CSV_SHA256 = "PENDING-REVIEW"
ADDED_KEYS = (
    'beef_dripping.unspecified', 'lard.unspecified', 'oil_avocado.unspecified', 'oil_coconut.unspecified',
    'oil_corn.unspecified', 'oil_groundnut.unspecified', 'oil_olive.unspecified', 'oil_rapeseed.unspecified',
    'oil_sesame.unspecified', 'oil_soybean.unspecified', 'oil_sunflower.unspecified', 'salt.unspecified',
    'sugar_icing.unspecified', 'sugar_raw_cane.unspecified', 'sugar_white.unspecified', 'syrup_cane.unspecified',
    'syrup_corn.unspecified', 'syrup_maple.unspecified', 'tea_black.unspecified', 'tea_herbal.unspecified',
    'vinegar_cider.unspecified', 'vinegar_distilled.unspecified', 'water.unspecified',
)


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
    keys = sa.bindparam("keys", value=list(ADDED_KEYS), expanding=True)
    ids = "(SELECT id FROM canonical_foods WHERE key IN :keys)"
    bind = op.get_bind()
    for table in ("canonical_typical_values", "canonical_members", "canonical_aliases"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE canonical_food_id IN {ids}").bindparams(keys))
    bind.execute(sa.text("DELETE FROM canonical_foods WHERE key IN :keys").bindparams(keys))
