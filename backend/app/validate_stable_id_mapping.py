"""Offline-validatable structural checks for the canonical private
stable-ID mapping artifact (docs/phytate-review/stable_id_mapping.csv,
untracked since PROMPT 9's quarantine) — prompts.txt PROMPT 12.

Two deliberately separate things:

  - `validate_structure`: checks that need only the mapping file itself
    — schema, uniqueness, allowed values, internal consistency — never
    the real FDC catalogue or a database connection. Runs in ordinary
    public CI against a synthetic fixture shaped like the real file
    (tests/fixtures/synthetic_stable_id_mapping.csv), never the real
    private one, so public CI stays deterministic without needing the
    real licensed data or a secret.

  - `compute_mapping_integrity_digest`: a deterministic fingerprint of
    the real private artifact's full byte content. Safe to publish — a
    hash reveals nothing about the PhyFoodComp source text/values it was
    computed from, the same reasoning app.catalogue_manifest already
    relies on for `catalogue_snapshot_checksum` — so a committed PUBLIC
    digest file (docs/phytate-review/stable_id_mapping_digest.json) can
    catch "the real mapping changed" without ever containing the mapping
    itself.

  - `verify_against_live_catalogue`: full catalogue verification
    (requirement 4) — for every row already present in a *given*
    stable-ID mapping file, looks up `Food.id` directly and checks
    `Food.fdc_id` matches exactly. Zero name lookup, zero fuzzy matching.
    A bot-review finding on PR #60 correctly caught that
    app.resolve_phytate_stable_ids does NOT do this: it reads
    `final_approved_mapping.csv` (approved-name/data_type pairs) and
    resolves fresh `food_id`/`fdc_id` targets by name from scratch — it
    never loads an *existing* `stable_id_mapping.csv` and confirms its
    specific recorded pairs are still valid. An operator who hand-altered
    a `food_id`/`fdc_id` pair in the committed digest's covered file (and
    updated the digest to match) would have that tampering caught here,
    not by re-running the resolver, which would just silently regenerate
    a fresh, correct file over it without ever having examined the
    altered pair.

Usage (an authorised operator, with the real private mapping file
present locally):
    python -m app.validate_stable_id_mapping --mapping-csv docs/phytate-review/stable_id_mapping.csv
    python -m app.validate_stable_id_mapping --mapping-csv docs/phytate-review/stable_id_mapping.csv --verify-live-catalogue
"""

import argparse
import csv
import dataclasses
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Food
from .resolve_phytate_stable_ids import MAPPING_OUT_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING_CSV = REPO_ROOT / "docs" / "phytate-review" / "stable_id_mapping.csv"
DEFAULT_DIGEST_FILE = REPO_ROOT / "docs" / "phytate-review" / "stable_id_mapping_digest.json"

ALLOWED_VERDICTS = frozenset({"approve", "replace"})

# Bump if what `compute_mapping_integrity_digest` covers or how it's
# computed ever changes -- a digest computed under a different version
# must never be compared byte-for-byte against one computed under this
# version, same convention as catalogue_manifest.IMPORTER_VERSION.
SCHEMA_VERSION = "stable-id-mapping-digest-v1"


def validate_structure(rows: list[dict]) -> list[str]:
    """Returns every structural problem found (empty list = clean, never
    stops at the first one, same convention as
    resolve_phytate_stable_ids.resolve_mapping_rows). Every check here is
    computable from the mapping file alone."""
    problems: list[str] = []

    if not rows:
        return ["mapping is empty -- nothing to validate"]

    missing_columns = set(MAPPING_OUT_COLUMNS) - rows[0].keys()
    if missing_columns:
        # Nothing else below can be checked safely against an unknown shape.
        return [f"missing required column(s): {sorted(missing_columns)}"]

    seen_ids: set[str] = set()
    checksums: set[str] = set()
    row_identifiers = [r["row_identifier"] for r in rows]

    for row in rows:
        rid = row["row_identifier"]
        if rid in seen_ids:
            problems.append(f"{rid}: duplicate row_identifier")
        seen_ids.add(rid)

        if not row["food_id"].strip().isdigit():
            problems.append(f"{rid}: food_id {row['food_id']!r} is not a positive integer")
        if not row["fdc_id"].strip().isdigit():
            problems.append(f"{rid}: fdc_id {row['fdc_id']!r} is not a positive integer")

        if row["review_verdict"] not in ALLOWED_VERDICTS:
            problems.append(
                f"{rid}: review_verdict {row['review_verdict']!r} is not one of {sorted(ALLOWED_VERDICTS)} -- "
                "only an approved/replaced row should ever appear as a resolved stable target"
            )
        if not row["match_scope"].strip():
            problems.append(f"{rid}: match_scope is blank")
        if not row["reviewer"].strip():
            problems.append(f"{rid}: reviewer is blank")

        checksums.add(row["catalogue_checksum"])

    if len(checksums) > 1:
        problems.append(
            f"catalogue_checksum is not consistent across all rows ({len(checksums)} distinct values found) "
            "-- every row in one mapping file must have been resolved against the exact same catalogue snapshot"
        )

    if row_identifiers != sorted(row_identifiers):
        problems.append(
            "rows are not sorted by row_identifier -- resolve_mapping_rows always sorts its output; an "
            "unsorted file did not come from that function unmodified"
        )

    return problems


def verify_against_live_catalogue(db: Session, rows: list[dict]) -> list[str]:
    """Requirement 4, done for real: for every row already in a *given*
    stable-ID mapping file, look up Food.id directly and confirm
    Food.fdc_id matches exactly. Zero name lookup, zero fuzzy fallback --
    the opposite of resolve_phytate_stable_ids, which never sees this
    file at all and instead resolves fresh targets by name from
    final_approved_mapping.csv. Reports every mismatch, never stops at
    the first (same convention as validate_structure)."""
    problems: list[str] = []
    for row in rows:
        rid = row["row_identifier"]
        food_id_raw, fdc_id_raw = row["food_id"].strip(), row["fdc_id"].strip()
        if not food_id_raw.isdigit() or not fdc_id_raw.isdigit():
            problems.append(f"{rid}: food_id/fdc_id not numeric, skipping live check ({food_id_raw!r}/{fdc_id_raw!r})")
            continue
        food_id, fdc_id = int(food_id_raw), int(fdc_id_raw)

        food = db.get(Food, food_id)
        if food is None:
            problems.append(f"{rid}: food_id={food_id} does not exist in the live catalogue")
        elif food.fdc_id != fdc_id:
            problems.append(
                f"{rid}: food_id={food_id} has fdc_id={food.fdc_id} in the live catalogue, "
                f"mapping records fdc_id={fdc_id} -- mismatch"
            )
    return problems


@dataclass(frozen=True)
class MappingIntegrityDigest:
    row_count: int
    digest: str
    schema_version: str


def compute_mapping_integrity_digest(mapping_csv: Path) -> MappingIntegrityDigest:
    hasher = hashlib.sha256()
    with open(mapping_csv, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    with open(mapping_csv, encoding="utf-8", newline="") as f:
        row_count = sum(1 for _ in csv.DictReader(f))
    return MappingIntegrityDigest(row_count=row_count, digest=hasher.hexdigest(), schema_version=SCHEMA_VERSION)


def load_expected_digest(digest_file: Path) -> MappingIntegrityDigest | None:
    if not digest_file.is_file():
        return None
    data = json.loads(digest_file.read_text(encoding="utf-8"))
    return MappingIntegrityDigest(**data)


def write_digest(digest_file: Path, digest: MappingIntegrityDigest) -> None:
    digest_file.parent.mkdir(parents=True, exist_ok=True)
    digest_file.write_text(
        json.dumps(dataclasses.asdict(digest), indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mapping-csv", default=str(DEFAULT_MAPPING_CSV))
    parser.add_argument("--digest-file", default=str(DEFAULT_DIGEST_FILE))
    parser.add_argument(
        "--write-digest", action="store_true",
        help="Write the freshly-computed digest to --digest-file. Without this, only compares against "
             "whatever digest is already recorded there (if any) and reports drift.",
    )
    parser.add_argument(
        "--verify-live-catalogue", action="store_true",
        help="Also check every row's food_id/fdc_id pair directly against the live database (requires "
             "DB access). Zero fuzzy/name fallback -- exact Food.id lookup, exact fdc_id equality.",
    )
    args = parser.parse_args()

    mapping_csv = Path(args.mapping_csv)
    digest_file = Path(args.digest_file)

    if not mapping_csv.is_file():
        print(f"error: not a file: {mapping_csv}", file=sys.stderr)
        sys.exit(1)

    with open(mapping_csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    problems = validate_structure(rows)
    if problems:
        print(f"{len(problems)} structural problem(s) found:", file=sys.stderr)
        for p in problems[:30]:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)
    print(f"Structure OK: {len(rows)} rows, all required columns present, no duplicates, sorted, consistent checksum.")

    if args.verify_live_catalogue:
        db = SessionLocal()
        try:
            live_problems = verify_against_live_catalogue(db, rows)
        finally:
            db.close()
        if live_problems:
            print(f"\n{len(live_problems)} live-catalogue problem(s) found:", file=sys.stderr)
            for p in live_problems[:30]:
                print(f"  {p}", file=sys.stderr)
            sys.exit(1)
        print(f"Live catalogue OK: all {len(rows)} food_id/fdc_id pairs verified exactly against the live Food table.")

    actual_digest = compute_mapping_integrity_digest(mapping_csv)
    print(f"Digest: {actual_digest.digest} (row_count={actual_digest.row_count})")

    expected_digest = load_expected_digest(digest_file)
    if expected_digest is not None and expected_digest != actual_digest:
        print(
            f"\nWARNING: recorded digest at {digest_file} does not match the current file "
            f"(expected {expected_digest}, got {actual_digest}) -- the real mapping has changed since that "
            "digest was recorded.",
            file=sys.stderr,
        )
        if not args.write_digest:
            sys.exit(1)

    if args.write_digest:
        write_digest(digest_file, actual_digest)
        print(f"Wrote digest to {digest_file}")

    if not args.verify_live_catalogue:
        print(
            "\nThis run only validated the mapping file's own shape. It did NOT verify fdc_id/Food.id pairs "
            "against the live FDC catalogue -- pass --verify-live-catalogue for that."
        )


if __name__ == "__main__":
    main()
