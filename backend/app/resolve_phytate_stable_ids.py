"""PROMPT 2 of the phytate/mineral-bioavailability extension (see
prompts.txt) — resolves the 1,139 human-approved rows in
docs/phytate-review/final_approved_mapping.csv (each an
approved_fdc_food NAME string + candidate_data_type, not a stable
identity) against the exact FDC catalogue that backed the review, and
emits a canonical stable-ID mapping keyed on fdc_id rather than the
locally-generated Food.id.

Read-only with respect to the database: every lookup is a plain SELECT
against Food. Nothing here writes to the database, and nothing here
performs fuzzy/similarity matching — only exact (name, data_type)
equality, per prompts.txt's explicit rule that missing/ambiguous targets
must never be silently rematched fuzzily.

Resolution outcomes per row_identifier:
  - exactly one Food row matches (name, data_type) and it has an
    fdc_id -> resolved.
  - zero Food rows match -> exception, reason="missing".
  - the one matching Food row has no fdc_id (a manually-entered/
    non-FDC food) -> exception, reason="stale_no_fdc_id": the review
    approved a target this app cannot express as external FDC identity.
  - more than one Food row matches -> exception, reason="duplicate",
    UNLESS a human has supplied an explicit fdc_id for this
    row_identifier via --overrides-csv, in which case that fdc_id is
    used only if it actually belongs to one of the candidates found for
    this row (never picked out of thin air) -- an override naming an
    fdc_id that isn't among the candidates is itself a blocking
    exception, reason="override_mismatch", not silently accepted.

The canonical stable_id_mapping.csv is written only when the exceptions
list is empty (prompts.txt rule 8) -- a non-empty run always writes
stable_id_exceptions.csv (for a human to add entries to
--overrides-csv) and exits non-zero, never a partial/best-effort mapping
file.

Catalogue safety: before resolving anything, the current Food table's
deterministic fingerprint (app.catalogue_manifest) is compared against
whatever fdc_catalogue_manifest.json already records. A first run with
no recorded manifest writes one and proceeds; a later run whose
fingerprint no longer matches means the Food table has drifted since the
review judged these targets, and the whole resolution is refused --
never a partial/best-effort result computed against a catalogue the
review never saw.
"""

import argparse
import csv
import dataclasses
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalogue_manifest import ManifestSnapshot, compute_fdc_catalogue_manifest
from .database import SessionLocal
from .models import Food

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING_CSV = REPO_ROOT / "docs" / "phytate-review" / "final_approved_mapping.csv"
DEFAULT_MANIFEST_FILE = REPO_ROOT / "docs" / "phytate-review" / "fdc_catalogue_manifest.json"
DEFAULT_OVERRIDES_CSV = REPO_ROOT / "docs" / "phytate-review" / "stable_id_exceptions_resolved.csv"
DEFAULT_OUT_MAPPING = REPO_ROOT / "docs" / "phytate-review" / "stable_id_mapping.csv"
DEFAULT_OUT_EXCEPTIONS = REPO_ROOT / "docs" / "phytate-review" / "stable_id_exceptions.csv"

MAPPING_OUT_COLUMNS = [
    "row_identifier", "food_description", "compound_fraction", "value",
    "food_id", "fdc_id", "approved_fdc_food", "data_type",
    "review_verdict", "match_scope", "reviewer", "review_date", "review_notes",
    "catalogue_checksum",
]
EXCEPTIONS_OUT_COLUMNS = [
    "row_identifier", "reason", "approved_fdc_food", "data_type", "detail",
]


class CatalogueDriftError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedRow:
    row_identifier: str
    food_description: str
    compound_fraction: str
    value: str
    food_id: int
    fdc_id: int
    approved_fdc_food: str
    data_type: str
    review_verdict: str
    match_scope: str
    reviewer: str
    review_date: str
    review_notes: str
    catalogue_checksum: str


@dataclass(frozen=True)
class ExceptionRow:
    row_identifier: str
    reason: str  # missing | duplicate | stale_no_fdc_id | override_mismatch
    approved_fdc_food: str
    data_type: str
    detail: str


def load_mapping_rows(mapping_csv: Path) -> list[dict]:
    with open(mapping_csv, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_overrides(overrides_csv: Path) -> dict[str, str]:
    """row_identifier -> chosen fdc_id (as a string), for previously
    duplicate/ambiguous rows a human has since disambiguated. Missing
    file means no overrides yet -- not an error."""
    if not overrides_csv.is_file():
        return {}
    with open(overrides_csv, encoding="utf-8", newline="") as f:
        return {
            row["row_identifier"]: row["chosen_fdc_id"].strip()
            for row in csv.DictReader(f)
            if row.get("chosen_fdc_id", "").strip()
        }


def load_expected_manifest(manifest_file: Path) -> ManifestSnapshot | None:
    if not manifest_file.is_file():
        return None
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    return ManifestSnapshot(
        source_name=data["source_name"],
        release_version=data["release_version"],
        import_date=date.fromisoformat(data["import_date"]),
        checksum=data["checksum"],
        row_count=data["row_count"],
        importer_version=data["importer_version"],
        notes=data.get("notes"),
    )


def write_manifest(manifest_file: Path, snapshot: ManifestSnapshot) -> None:
    payload = dataclasses.asdict(snapshot)
    payload["import_date"] = snapshot.import_date.isoformat()
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_catalogue_manifest(
    expected: ManifestSnapshot | None, actual: ManifestSnapshot,
) -> None:
    """Raises CatalogueDriftError if a previously-recorded manifest no
    longer matches the live Food table. A missing expected manifest
    (first run) is not an error -- the caller records `actual` as the
    new baseline."""
    if expected is None:
        return
    if expected.importer_version != actual.importer_version:
        raise CatalogueDriftError(
            f"recorded manifest used importer_version={expected.importer_version!r}, "
            f"current code computes {actual.importer_version!r} -- incompatible fingerprints, "
            "cannot compare safely"
        )
    if expected.checksum != actual.checksum:
        raise CatalogueDriftError(
            f"Food catalogue has drifted since this manifest was recorded: expected checksum "
            f"{expected.checksum} ({expected.row_count} rows), got {actual.checksum} "
            f"({actual.row_count} rows). Refusing to resolve against a catalogue the review never saw."
        )


def resolve_mapping_rows(
    db: Session, mapping_rows: list[dict], overrides: dict[str, str], catalogue_checksum: str,
) -> tuple[list[ResolvedRow], list[ExceptionRow]]:
    resolved: list[ResolvedRow] = []
    exceptions: list[ExceptionRow] = []

    for row in sorted(mapping_rows, key=lambda r: r["row_identifier"]):
        rid = row["row_identifier"]
        name = row["approved_fdc_food"]
        data_type = row["candidate_data_type"]

        query = select(Food).where(Food.name == name)
        if data_type:
            query = query.where(Food.data_type == data_type)
        matches = sorted(db.execute(query).scalars().all(), key=lambda f: f.id)

        if len(matches) == 0:
            exceptions.append(ExceptionRow(
                row_identifier=rid, reason="missing", approved_fdc_food=name, data_type=data_type,
                detail=f"no Food row matches name={name!r} data_type={data_type!r}",
            ))
            continue

        if len(matches) > 1:
            override_fdc_id = overrides.get(rid)
            if override_fdc_id is None:
                candidate_list = ", ".join(f"food_id={f.id}:fdc_id={f.fdc_id}" for f in matches)
                exceptions.append(ExceptionRow(
                    row_identifier=rid, reason="duplicate", approved_fdc_food=name, data_type=data_type,
                    detail=f"{len(matches)} Food rows match, no override supplied: {candidate_list}",
                ))
                continue

            by_fdc_id = [f for f in matches if str(f.fdc_id) == override_fdc_id]
            if not by_fdc_id:
                candidate_list = ", ".join(f"food_id={f.id}:fdc_id={f.fdc_id}" for f in matches)
                exceptions.append(ExceptionRow(
                    row_identifier=rid, reason="override_mismatch", approved_fdc_food=name, data_type=data_type,
                    detail=(
                        f"override fdc_id={override_fdc_id} is not among the {len(matches)} candidates "
                        f"for this row: {candidate_list}"
                    ),
                ))
                continue
            food = by_fdc_id[0]
        else:
            food = matches[0]

        if food.fdc_id is None:
            exceptions.append(ExceptionRow(
                row_identifier=rid, reason="stale_no_fdc_id", approved_fdc_food=name, data_type=data_type,
                detail=f"matched Food.id={food.id} but it has no fdc_id (not an FDC-sourced row)",
            ))
            continue

        resolved.append(ResolvedRow(
            row_identifier=rid,
            food_description=row["food_description"],
            compound_fraction=row["compound_fraction"],
            value=row["value"],
            food_id=food.id,
            fdc_id=food.fdc_id,
            approved_fdc_food=name,
            data_type=data_type,
            review_verdict=row["review_verdict"],
            match_scope=row["match_scope"],
            reviewer=row["reviewer"],
            review_date=row["review_date"],
            review_notes=row.get("review_notes", ""),
            catalogue_checksum=catalogue_checksum,
        ))

    return resolved, exceptions


def write_exceptions_csv(path: Path, exceptions: list[ExceptionRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXCEPTIONS_OUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for exc in exceptions:
            writer.writerow(dataclasses.asdict(exc))


def write_mapping_csv(path: Path, resolved: list[ResolvedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MAPPING_OUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in resolved:
            writer.writerow(dataclasses.asdict(row))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mapping-csv", default=str(DEFAULT_MAPPING_CSV))
    parser.add_argument("--manifest-file", default=str(DEFAULT_MANIFEST_FILE))
    parser.add_argument("--overrides-csv", default=str(DEFAULT_OVERRIDES_CSV))
    parser.add_argument("--out-mapping", default=str(DEFAULT_OUT_MAPPING))
    parser.add_argument("--out-exceptions", default=str(DEFAULT_OUT_EXCEPTIONS))
    args = parser.parse_args()

    mapping_csv = Path(args.mapping_csv)
    manifest_file = Path(args.manifest_file)
    overrides_csv = Path(args.overrides_csv)
    out_mapping = Path(args.out_mapping)
    out_exceptions = Path(args.out_exceptions)

    if not mapping_csv.is_file():
        print(f"error: not a file: {mapping_csv}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        actual_manifest = compute_fdc_catalogue_manifest(db)
        expected_manifest = load_expected_manifest(manifest_file)
        try:
            check_catalogue_manifest(expected_manifest, actual_manifest)
        except CatalogueDriftError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        if expected_manifest is None:
            write_manifest(manifest_file, actual_manifest)
            print(f"No recorded catalogue manifest found -- recorded a new baseline at {manifest_file}")
            print(f"  source={actual_manifest.source_name} rows={actual_manifest.row_count} "
                  f"checksum={actual_manifest.checksum} release_version={actual_manifest.release_version}")

        mapping_rows = load_mapping_rows(mapping_csv)
        overrides = load_overrides(overrides_csv)
        resolved, exceptions = resolve_mapping_rows(db, mapping_rows, overrides, actual_manifest.checksum)
    finally:
        db.close()

    write_exceptions_csv(out_exceptions, exceptions)

    reasons = {"missing": 0, "duplicate": 0, "stale_no_fdc_id": 0, "override_mismatch": 0}
    for exc in exceptions:
        reasons[exc.reason] += 1
    override_resolved = sum(1 for r in mapping_rows if r["row_identifier"] in overrides) - reasons["override_mismatch"]

    print(f"total rows: {len(mapping_rows)}")
    print(f"resolved: {len(resolved)}")
    print(f"missing: {reasons['missing']}")
    print(f"duplicate (unresolved, needs override): {reasons['duplicate']}")
    print(f"stale (matched Food row has no fdc_id): {reasons['stale_no_fdc_id']}")
    print(f"override supplied but not among candidates: {reasons['override_mismatch']}")
    print(f"resolved via manual override: {max(override_resolved, 0)}")
    assert len(resolved) + len(exceptions) == len(mapping_rows), "every row must be resolved or blocked"

    if exceptions:
        print(
            f"\n{len(exceptions)} exception(s) written to {out_exceptions} -- "
            f"not writing {out_mapping} until every exception is resolved (add entries to {overrides_csv} "
            "for duplicates, or correct the review file for missing/stale targets).",
            file=sys.stderr,
        )
        sys.exit(1)

    write_mapping_csv(out_mapping, resolved)
    print(f"\nWrote {len(resolved)} resolved stable-ID mappings to {out_mapping}")


if __name__ == "__main__":
    main()
