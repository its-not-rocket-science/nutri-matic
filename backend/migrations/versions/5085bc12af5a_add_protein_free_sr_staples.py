"""add protein-free SR Legacy staples (sugar, oils, salt, vinegar, tea, water)

Revision ID: 5085bc12af5a
Revises: 18067652e674
Create Date: 2026-11-28 00:00:00.000000

Data migration: inserts the owner-approved shortlist in
app/fdc_staples_sr_legacy_2018_04.csv (USDA SR Legacy April 2018, public
domain) as real sr_legacy_food rows with their FDC ids, through
app.fdc_staples.apply. ingest_fdc.py skips these because they have no
protein; see app/fdc_staples.py for exactly what is written.

Pinned to the extract's sha256; when the file on disk no longer matches, a
later data migration owns the load and this one does nothing. A row whose fdc_id is already present is
left untouched, so re-running is a no-op. Skipped on a database with no FDC
catalogue rows (CI, a fresh dev database), like the canonical load.

This writes `foods` and `food_nutrients`, so the catalogue snapshot checksum
changes: re-run app.resolve_phytate_stable_ids before the next phytate
import. Existing rows keep their id and fdc_id.

downgrade() deletes these rows and their nutrients. If anything refers to
one of them (a diary entry, a recipe ingredient, a canonical anchor), the
foreign key stops the downgrade instead of deleting user data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '5085bc12af5a'
down_revision: Union[str, None] = '18067652e674'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXTRACT_SHA256 = "f3864d6340d74c84410071399f050a21eb735d5c9d0f6ba8a6c1cfc38e328cd1"
FDC_IDS = (
    167743, 168837, 169655, 169656, 170276, 170674, 171016, 171025, 171029, 171400, 171401, 171410,
    171411, 171412, 171413, 172237, 172336, 173227, 173232, 173468, 173469, 173573, 173647,
)


def upgrade() -> None:
    from app.fdc_staples import apply, file_sha256, load_extract

    current = file_sha256()
    if current != EXTRACT_SHA256:
        print(f"fdc staples: extract sha256 {current} is not this revision's pin; a later revision loads it")
        return
    db = Session(bind=op.get_bind())
    result = apply(db, load_extract())
    db.flush()
    print(result.summary())


def downgrade() -> None:
    ids = sa.bindparam("ids", value=list(FDC_IDS), expanding=True)
    op.get_bind().execute(
        sa.text("DELETE FROM food_nutrients WHERE food_id IN (SELECT id FROM foods WHERE fdc_id IN :ids)")
        .bindparams(ids)
    )
    op.get_bind().execute(sa.text("DELETE FROM foods WHERE fdc_id IN :ids").bindparams(ids))
