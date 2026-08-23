"""Deterministic snapshot/fingerprint of the USDA FDC Food catalogue, for
app.models.ImportManifest (prompts.txt PROMPT 2 of the phytate/mineral-
bioavailability extension).

Why a checksum instead of a recorded release string: neither `Food` nor
`ingest_fdc.py` records which FDC "Download Datasets" release actually
populated the live catalogue (confirmed by inspection — no release/
version field anywhere in the schema or ingestion script), and
`ingest_fdc.py`'s own data-loading logic hasn't changed since the single
historical ingestion run that built the current Food table (per git
history: no commit since "Add USDA FoodData Central ingestion pipeline"
has touched it). There is therefore no honest way to recover *which*
upstream release this is. PROMPT 2 explicitly forbids hard-coding a
guessed date, so `release_version` stays an explicit
"unrecorded_at_ingestion" and `checksum` becomes the actual drift-
detection mechanism: a deterministic fingerprint of exactly the Food
rows the phytate stable-ID resolver depends on (id, fdc_id, name,
data_type, restricted to rows with a non-null fdc_id, since only those
carry external identity) — if the Food table ever changes under it, this
checksum changes too, and the resolver can detect and refuse to proceed
on a mismatch instead of silently resolving against a different
catalogue than the one the review actually judged.
"""

import hashlib
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Food

SOURCE_NAME = "usda_fdc_food_catalogue"

# Bump if the fields/ordering fingerprinted below ever change — see
# ImportManifest.importer_version's column comment. A manifest computed
# under a different version must never be compared byte-for-byte against
# one computed under this version.
IMPORTER_VERSION = "fdc-catalogue-manifest-v1"

UNRECORDED_RELEASE = "unrecorded_at_ingestion"


@dataclass(frozen=True)
class ManifestSnapshot:
    source_name: str
    release_version: str
    import_date: date
    checksum: str
    row_count: int
    importer_version: str
    notes: str | None = None


def compute_fdc_catalogue_manifest(db: Session, *, as_of: date | None = None) -> ManifestSnapshot:
    """Reads (never writes) the current Food table and returns a
    deterministic fingerprint of every row that carries external FDC
    identity (fdc_id IS NOT NULL) — rows with no fdc_id (manually-entered
    foods) are outside what the phytate resolver ever *targets* directly.

    Manually-entered rows are still fingerprinted (in a second pass,
    keyed distinctly so they can never collide with an FDC row's line)
    because they DO participate in the resolver's name-only duplicate-
    detection query (app.resolve_phytate_stable_ids.resolve_mapping_rows)
    -- one appearing, disappearing, or being renamed can turn a target
    from unique to duplicate or vice versa, and that must move the
    checksum so drift detection actually catches it, not just changes to
    the FDC-identified rows themselves."""
    rows = db.execute(
        select(Food.id, Food.fdc_id, Food.name, Food.data_type)
        .where(Food.fdc_id.isnot(None))
        .order_by(Food.fdc_id, Food.id)
    ).all()
    manual_rows = db.execute(
        select(Food.id, Food.name, Food.data_type)
        .where(Food.fdc_id.is_(None))
        .order_by(Food.id)
    ).all()

    hasher = hashlib.sha256()
    for food_id, fdc_id, name, data_type in rows:
        line = f"{food_id}|{fdc_id}|{name}|{data_type or ''}\n"
        hasher.update(line.encode("utf-8"))
    for food_id, name, data_type in manual_rows:
        line = f"manual|{food_id}|{name}|{data_type or ''}\n"
        hasher.update(line.encode("utf-8"))

    return ManifestSnapshot(
        source_name=SOURCE_NAME,
        release_version=UNRECORDED_RELEASE,
        import_date=as_of or date.today(),
        checksum=hasher.hexdigest(),
        row_count=len(rows),
        importer_version=IMPORTER_VERSION,
        notes=(
            "Upstream FDC release/version could not be verified from repository configuration or "
            "ingest metadata (see module docstring) — checksum is the authoritative drift-detection "
            "mechanism, not release_version."
        ),
    )
