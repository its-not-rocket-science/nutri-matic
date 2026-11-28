"""backfill Foundation Foods energy and folate (canonical foods plan 1.3)

Revision ID: 868a02252a15
Revises: cf2908ff260e
Create Date: 2026-11-28 00:00:00.000000

Data migration: adds the energy (from Atwater 958/957) and folate (from
total folate 417, minus the owner-reviewed fortified exclusions) values in
app/foundation_nutrients_2026_04_30.csv to Foundation rows that lack them,
through app.foundation_nutrients.apply. ingest_fdc.py applies the same
fallbacks from now on; this brings databases ingested before that up to
date.

Only inserts a missing (food, nutrient) row; never changes an existing
one. A food that is absent, or present under a different name (another
FDC release), is skipped and counted. Pinned to the extract's sha256;
skipped on a database with no FDC catalogue rows. Nutrient rows are not
part of the catalogue checksum, so phytate stable ids are unaffected.

downgrade() removes exactly the rows whose (fdc_id, nutrient, amount)
match the extract, i.e. what this migration added.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '868a02252a15'
down_revision: Union[str, None] = 'cf2908ff260e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXTRACT_SHA256 = "c7347c34dfaf8eaee4e7736edc51394e18a8b969eab078346a1267c0ab72e11d"


def upgrade() -> None:
    from app.foundation_nutrients import apply, file_sha256, load_extract

    current = file_sha256()
    if current != EXTRACT_SHA256:
        print(f"foundation nutrients: extract sha256 {current} is not this revision's pin; a later revision loads it")
        return
    db = Session(bind=op.get_bind())
    result = apply(db, load_extract())
    db.flush()
    print(result.summary())
    for line in result.name_mismatch[:20]:
        print(f"  name mismatch: {line}")


def downgrade() -> None:
    from app.foundation_nutrients import file_sha256, load_extract

    if file_sha256() != EXTRACT_SHA256:
        raise RuntimeError("the extract on disk is not the one this revision loaded; downgrade by hand")
    bind = op.get_bind()
    for r in load_extract():
        bind.execute(sa.text(
            "DELETE FROM food_nutrients WHERE nutrient_key = :key AND amount_per_100g = :amount AND food_id IN "
            "(SELECT id FROM foods WHERE fdc_id = :fdc_id AND data_type = 'foundation_food')"
        ), {"key": r.nutrient_key, "amount": r.amount, "fdc_id": r.fdc_id})
