"""PROMPT 3 of the phytate/mineral-bioavailability extension (see
prompts.txt) — the one canonical reviewed PhyFoodComp ingestion command.
Extends the importer originally built to close the automated pipeline's
needs_review gate (see git history / PR history for the pre-Prompt-2
version of this file) so there is exactly one write path, not two.

Consumes, together, never separately:
  1. the real PhyFoodComp 1.0 workbook (outside git — see
     app.phyfoodcomp_adapter);
  2. the signed review decision set (the seven review_*.csv files);
  3. the stable-ID mapping app.resolve_phytate_stable_ids produced
     (docs/phytate-review/stable_id_mapping.csv), keyed on fdc_id, not
     just a local Food.id;
  4. the verified FDC catalogue manifest (app.catalogue_manifest);
  5. explicit dataset citation/version/access-date metadata, passed on
     the command line, never defaulted.

This module never imports app.stock_recipes.food_matching and never
calls match_ingredient — a reviewed observation's target comes only
from the stable-ID mapping (approve/replace) or is nulled (reject/
unresolved); it is never re-derived from a food name.

Reconciliation is two-phase by design: `reconcile_rows` computes a full,
deterministic report and the complete list of blocking problems (never
stopping at the first one, same convention as validate_and_consolidate)
*before* anything is written. Any blocking problem — an unknown,
missing, or duplicate row_identifier; a workbook value that disagrees
with the signed review record beyond VALUE_TOLERANCE; an approve/
replace row absent from the stable-ID mapping; a stable-ID target whose
Food.id no longer has the fdc_id the mapping recorded — refuses the
*entire* import, not just the offending row: `main()` never opens a
write transaction while `problems` is non-empty, and `apply_plans` is
never called in that case. That is this module's rollback guarantee —
there is no partial-apply path to roll back from in the first place.
"""

import argparse
import csv
import hashlib
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from .catalogue_manifest import compute_fdc_catalogue_manifest
from .database import SessionLocal
from .models import CompoundObservation, Food
from .phyfoodcomp_adapter import load_phyfoodcomp_workbook

COMPOUND = "phytate"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIEW_DIR = REPO_ROOT / "docs" / "phytate-review"
DEFAULT_STABLE_ID_MAPPING = DEFAULT_REVIEW_DIR / "stable_id_mapping.csv"

# All seven review files -- review_2 (entirely "unresolved" verdicts) is
# not in export_final_mapping.py's SOURCE_FILES since that script only
# cares about approve/replace, but this importer must clear/confirm
# needs_review for those rows too.
REVIEW_FILES = [
    "review_1_ambiguous.csv",
    "review_2_no_candidate.csv",
    "review_3_branded_low_confidence.csv",
    "review_4_special_cases.csv",
    "review_5_infant_flour_cluster.csv",
    "review_6_accepted_sample.csv",
    "review_6b_accepted_remainder.csv",
]

CLOSE_ANALOGUE_CONFIDENCE = 0.8
CATEGORY_PROXY_CONFIDENCE = 0.65

# Workbook values and review-record values both ultimately derive from
# the same source cell, but pass through independent float parses (an
# openpyxl read here, a csv.DictReader read for the review record) --
# this tolerance only absorbs float-repr noise from that double
# round-trip, not genuine data disagreement. 1e-6 relative (with a
# 1e-9 floor for values near zero) is far tighter than any plausible
# transcription error.
VALUE_TOLERANCE_RELATIVE = 1e-6
VALUE_TOLERANCE_FLOOR = 1e-9

# The only import scope this command currently permits, per prompts.txt's
# fail-closed licensing rule: FAO has not granted commercial-use
# permission, so every commercial/paid/professional/enterprise surface
# is refused explicitly rather than defaulted into. Not a set the caller
# can extend from the command line -- widening this requires reviewing
# FAO's actual written terms and editing this constant deliberately, not
# passing a new flag value.
ALLOWED_SCOPES = {"noncommercial_free_surface"}
DENIED_SCOPES = {"paid", "professional", "enterprise", "commercial_api"}


@dataclass
class Decision:
    row_identifier: str
    verdict: str  # approve | replace | reject | unresolved
    approved_fdc_food: str
    candidate_data_type: str
    rationale: str
    source_file: str
    # the signed record's own account of what this row measured --
    # cross-checked against the workbook's parsed RawObservation in
    # reconcile_rows, never trusted to still match without checking.
    food_description: str
    compound_fraction: str
    value: float | None


@dataclass(frozen=True)
class StableTarget:
    food_id: int
    fdc_id: int
    catalogue_checksum: str


@dataclass
class RowPlan:
    row_identifier: str
    action: str  # insert | update | unchanged
    fields: dict
    existing_id: int | None = None


def load_review_rows(review_dir: Path) -> dict[str, list[dict]]:
    rows_by_file = {}
    for fname in REVIEW_FILES:
        with open(review_dir / fname, encoding="utf-8", newline="") as f:
            rows_by_file[fname] = list(csv.DictReader(f))
    return rows_by_file


def _parse_value(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def validate_and_consolidate(rows_by_file: dict[str, list[dict]]) -> tuple[dict[str, Decision], list[str]]:
    """Returns (row_identifier -> Decision, blocking errors). If errors is
    non-empty, the caller must not proceed."""
    errors = []

    all_verdicts: dict[str, list[tuple[str, str, str]]] = {}
    for fname, rows in rows_by_file.items():
        for row in rows:
            verdict = row["review_verdict"]
            if not verdict:
                continue
            rid = row["row_identifier"]
            all_verdicts.setdefault(rid, []).append((fname, verdict, row["candidate"]))

    decisions: dict[str, Decision] = {}
    for fname, rows in rows_by_file.items():
        for row in rows:
            rid = row["row_identifier"]
            verdict = row["review_verdict"]
            notes = row.get("review_notes", "")
            superseded = "MOVED -- superseded" in notes

            if not verdict:
                if row.get("sampled_for_review", "YES") == "NO":
                    continue
                if "DEFERRED" not in notes and "MOVED" not in notes:
                    errors.append(f"{fname} {rid}: blank review_verdict with no DEFERRED/MOVED explanation")
                continue

            if verdict in ("approve", "replace"):
                if superseded:
                    continue
                if not row["reviewer"]:
                    errors.append(f"{fname} {rid}: verdict={verdict} but no reviewer sign-off")
                    continue
                if not row.get("match_scope", "").strip():
                    errors.append(f"{fname} {rid}: verdict={verdict} but match_scope is blank")
                    continue
                if not row["approved_fdc_food"].strip():
                    errors.append(f"{fname} {rid}: verdict={verdict} but approved_fdc_food is blank")
                    continue

                contradicted_by = [
                    f2 for f2, v2, c2 in all_verdicts.get(rid, [])
                    if f2 != fname and v2 == "reject" and c2 == row["candidate"]
                ]
                if contradicted_by:
                    errors.append(
                        f"{rid}: {fname}={verdict} contradicted by {contradicted_by[0]}=reject "
                        "for the same candidate, not flagged as superseded"
                    )
                    continue

                if rid in decisions and decisions[rid].verdict in ("approve", "replace"):
                    if decisions[rid].approved_fdc_food != row["approved_fdc_food"]:
                        errors.append(
                            f"{rid}: conflicting approved_fdc_food between "
                            f"{decisions[rid].source_file} and {fname}"
                        )
                    continue

                decisions[rid] = Decision(
                    row_identifier=rid, verdict=verdict, approved_fdc_food=row["approved_fdc_food"],
                    candidate_data_type=row.get("candidate_data_type", ""),
                    rationale=row.get("review_notes") or row.get("rejection_reason") or "",
                    source_file=fname,
                    food_description=row.get("food_description", ""),
                    compound_fraction=row.get("compound_fraction", ""),
                    value=_parse_value(row.get("value", "")),
                )

            elif verdict in ("reject", "unresolved"):
                if superseded:
                    continue
                if rid not in decisions:
                    decisions[rid] = Decision(
                        row_identifier=rid, verdict=verdict, approved_fdc_food="",
                        candidate_data_type="",
                        rationale=row.get("rejection_reason") or row.get("review_notes") or "",
                        source_file=fname,
                        food_description=row.get("food_description", ""),
                        compound_fraction=row.get("compound_fraction", ""),
                        value=_parse_value(row.get("value", "")),
                    )

    return decisions, errors


def load_stable_id_mapping(path: Path) -> dict[str, StableTarget]:
    with open(path, encoding="utf-8", newline="") as f:
        return {
            row["row_identifier"]: StableTarget(
                food_id=int(row["food_id"]), fdc_id=int(row["fdc_id"]),
                catalogue_checksum=row["catalogue_checksum"],
            )
            for row in csv.DictReader(f)
        }


def compute_file_checksum(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_scope(scope: str) -> str | None:
    """Returns an error message if `scope` is not currently permitted,
    None if it is. Never returns None for anything outside
    ALLOWED_SCOPES -- an unrecognised scope fails closed exactly like an
    explicitly denied one, per prompts.txt's fail-closed default."""
    if scope in ALLOWED_SCOPES:
        return None
    reason = "explicitly denied" if scope in DENIED_SCOPES else "not a recognised scope"
    return (
        f"import scope {scope!r} is {reason}. Only {sorted(ALLOWED_SCOPES)} is currently permitted "
        "while FAO commercial-use permission remains unresolved."
    )


def check_apply_confirmation(
    confirm_dataset_version: str | None, dataset_version: str,
    confirm_workbook_checksum: str | None, actual_workbook_checksum: str,
) -> str | None:
    """The second explicit acknowledgement prompts.txt PROMPT 3 requires
    before --apply is allowed to write anything: the operator must repeat
    back the exact dataset version and the workbook's actual sha256, not
    just pass --apply. Returns an error message if either doesn't match,
    None if both do."""
    if confirm_dataset_version != dataset_version:
        return (
            f"--confirm-dataset-version ({confirm_dataset_version!r}) does not match "
            f"--dataset-version ({dataset_version!r}) -- refusing to apply"
        )
    if confirm_workbook_checksum != actual_workbook_checksum:
        return (
            f"--confirm-workbook-checksum ({confirm_workbook_checksum}) does not match the actual "
            f"workbook checksum ({actual_workbook_checksum}) -- refusing to apply"
        )
    return None


def check_catalogue_drift(stable_ids: dict[str, StableTarget], actual_checksum: str) -> str | None:
    """Returns an error message if the stable-ID mapping's recorded
    catalogue checksum(s) no longer match the live Food table, None if
    they're consistent (or there's nothing to compare -- an empty
    mapping has no checksum to drift from)."""
    recorded_checksums = {t.catalogue_checksum for t in stable_ids.values()}
    if recorded_checksums and recorded_checksums != {actual_checksum}:
        return (
            f"the Food catalogue has drifted since the stable-ID mapping was generated (mapping recorded "
            f"{sorted(recorded_checksums)}, current catalogue checksum is {actual_checksum}) -- re-run "
            "app.resolve_phytate_stable_ids against the current catalogue before importing."
        )
    return None


def _values_disagree(workbook_value: float | None, reviewed_value: float | None) -> bool:
    """A censored workbook observation (value=None, Prompt 5) has
    nothing numeric to compare -- never flagged as a disagreement purely
    for being censored; only a genuine numeric mismatch when both sides
    have a number is a problem here."""
    if reviewed_value is None or workbook_value is None:
        return False
    tolerance = max(abs(reviewed_value) * VALUE_TOLERANCE_RELATIVE, VALUE_TOLERANCE_FLOOR)
    return abs(workbook_value - reviewed_value) > tolerance


def reconcile_rows(
    db: Session, rows: list, adapter_stats: dict, decisions: dict[str, Decision],
    stable_ids: dict[str, StableTarget], dataset_name: str, dataset_citation: str,
    dataset_version: str, access_date: date,
) -> tuple[dict, list[str], list[RowPlan]]:
    """Computes the full deterministic reconciliation report plus every
    blocking problem across the whole workbook, without stopping at the
    first one -- see module docstring. Read-only: does not call
    db.add/db.commit."""
    report = {
        "source_observations": adapter_stats["rows_considered"],
        "numeric_observations": adapter_stats["observations_built"],
        "censored_observations": adapter_stats["censored_observations_built"],
        "approved": 0, "replaced": 0, "rejected": 0, "unresolved": 0,
        "inserted": 0, "updated": 0, "unchanged": 0, "blocked": 0, "unexpected": 0,
    }
    problems: list[str] = []
    plans: list[RowPlan] = []
    seen_row_ids: set[str] = set()

    for row in rows:
        rid = row.row_identifier
        if rid is None:
            problems.append("workbook observation with no row_identifier -- cannot reconcile against review records")
            report["blocked"] += 1
            continue
        if rid in seen_row_ids:
            problems.append(f"{rid}: duplicate row_identifier within the workbook itself")
            report["blocked"] += 1
            continue
        seen_row_ids.add(rid)

        decision = decisions.get(rid)
        if decision is None:
            problems.append(f"{rid}: no review verdict covers this row_identifier")
            report["blocked"] += 1
            continue

        if decision.food_description and row.food_description != decision.food_description:
            problems.append(
                f"{rid}: workbook food_description {row.food_description!r} != "
                f"reviewed record {decision.food_description!r}"
            )
            report["blocked"] += 1
            continue
        if decision.compound_fraction and row.compound_fraction != decision.compound_fraction:
            problems.append(
                f"{rid}: workbook compound_fraction {row.compound_fraction!r} != "
                f"reviewed record {decision.compound_fraction!r}"
            )
            report["blocked"] += 1
            continue
        if _values_disagree(row.value, decision.value):
            problems.append(
                f"{rid}: workbook value {row.value} disagrees with reviewed record {decision.value} "
                f"beyond tolerance"
            )
            report["blocked"] += 1
            continue

        if decision.verdict in ("approve", "replace"):
            target = stable_ids.get(rid)
            if target is None:
                problems.append(
                    f"{rid}: verdict={decision.verdict} but not present in the resolved stable-ID mapping "
                    "-- run app.resolve_phytate_stable_ids first"
                )
                report["blocked"] += 1
                continue

            food = db.get(Food, target.food_id)
            if food is None or food.fdc_id != target.fdc_id:
                problems.append(
                    f"{rid}: stable-ID mapping says Food.id={target.food_id} has fdc_id={target.fdc_id}, "
                    f"but the database now has fdc_id={food.fdc_id if food else None} -- mapping is stale, "
                    "re-run the resolver"
                )
                report["blocked"] += 1
                continue

            matched_food_id = food.id
            if decision.verdict == "approve":
                match_relationship, confidence = "close_analogue", CLOSE_ANALOGUE_CONFIDENCE
                report["approved"] += 1
            else:
                match_relationship, confidence = "category_proxy", CATEGORY_PROXY_CONFIDENCE
                report["replaced"] += 1
        elif decision.verdict in ("reject", "unresolved"):
            matched_food_id = None
            match_relationship, confidence = "needs_review", None
            if decision.verdict == "reject":
                report["rejected"] += 1
            else:
                report["unresolved"] += 1
        else:
            problems.append(f"{rid}: decision verdict {decision.verdict!r} is not a recognised verdict")
            report["unexpected"] += 1
            continue

        rationale = f"Human-reviewed ({decision.verdict}): {decision.rationale}"
        fields = dict(
            compound=COMPOUND, compound_fraction=row.compound_fraction, original_value=row.value,
            original_unit=row.unit, original_basis=row.basis,
            original_value_text=row.value_text, value_qualifier=row.value_qualifier,
            detection_limit_value=row.detection_limit_value, detection_limit_unit=row.detection_limit_unit,
            original_value_provenance=None if row.value is None else "source_reported",
            source_food_description=row.food_description,
            source_preparation_state=row.preparation_state, source_dataset_name=dataset_name,
            source_dataset_citation=dataset_citation, source_dataset_version=dataset_version,
            source_access_date=access_date, analytical_method=row.analytical_method,
            source_row_identifier=rid, match_relationship=match_relationship, match_confidence=confidence,
            match_rationale=rationale, matched_food_id=matched_food_id,
        )

        existing = (
            db.query(CompoundObservation)
            .filter(
                CompoundObservation.compound == COMPOUND,
                CompoundObservation.source_dataset_name == dataset_name,
                CompoundObservation.source_dataset_version == dataset_version,
                CompoundObservation.source_row_identifier == rid,
            )
            .one_or_none()
        )

        if existing is None:
            plans.append(RowPlan(row_identifier=rid, action="insert", fields=fields))
            report["inserted"] += 1
        else:
            changed = any(getattr(existing, key) != value for key, value in fields.items())
            if changed:
                plans.append(RowPlan(row_identifier=rid, action="update", fields=fields, existing_id=existing.id))
                report["updated"] += 1
            else:
                plans.append(RowPlan(row_identifier=rid, action="unchanged", fields=fields, existing_id=existing.id))
                report["unchanged"] += 1

    return report, problems, plans


def apply_plans(db: Session, plans: list[RowPlan]) -> None:
    """Writes every non-blocked plan. Caller is responsible for only
    calling this when `problems` from reconcile_rows is empty, and for
    committing/rolling back the surrounding transaction."""
    for plan in plans:
        if plan.action == "insert":
            db.add(CompoundObservation(**plan.fields))
        elif plan.action == "update":
            existing = db.get(CompoundObservation, plan.existing_id)
            for key, value in plan.fields.items():
                setattr(existing, key, value)
        # "unchanged" -- nothing to write


def print_report(report: dict) -> None:
    for key in (
        "source_observations", "numeric_observations", "censored_observations",
        "approved", "replaced", "rejected", "unresolved",
        "inserted", "updated", "unchanged", "blocked", "unexpected",
    ):
        print(f"{key}: {report[key]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xlsx", required=True, help="Path to the real PhyFoodComp_1.0.xlsx (kept outside git)")
    parser.add_argument("--review-dir", default=str(DEFAULT_REVIEW_DIR))
    parser.add_argument("--stable-id-mapping", default=str(DEFAULT_STABLE_ID_MAPPING))
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-citation", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--access-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--scope", required=True,
        help="Import scope. Only 'noncommercial_free_surface' is currently permitted -- see prompts.txt's "
             "fail-closed licensing rule; FAO has not granted commercial-use permission.",
    )
    parser.add_argument("--apply", action="store_true", help="Without this, always a dry run (the default).")
    parser.add_argument(
        "--confirm-dataset-version", default=None,
        help="Required with --apply: must exactly repeat --dataset-version, as an explicit second "
             "acknowledgement of what is about to be imported.",
    )
    parser.add_argument(
        "--confirm-workbook-checksum", default=None,
        help="Required with --apply: must exactly match the sha256 of the --xlsx file being imported.",
    )
    args = parser.parse_args()

    scope_error = validate_scope(args.scope)
    if scope_error:
        print(f"ERROR: {scope_error}", file=sys.stderr)
        sys.exit(1)

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.is_file():
        print(f"error: not a file: {xlsx_path}", file=sys.stderr)
        sys.exit(1)
    review_dir = Path(args.review_dir)
    stable_id_mapping_path = Path(args.stable_id_mapping)
    if not stable_id_mapping_path.is_file():
        print(
            f"error: not a file: {stable_id_mapping_path} -- run app.resolve_phytate_stable_ids first",
            file=sys.stderr,
        )
        sys.exit(1)

    access_date = datetime.strptime(args.access_date, "%Y-%m-%d").date()
    workbook_checksum = compute_file_checksum(xlsx_path)

    rows, adapter_stats = load_phyfoodcomp_workbook(xlsx_path)
    print(
        f"parsed workbook: sheets={adapter_stats['sheets']} rows_considered={adapter_stats['rows_considered']} "
        f"rows_skipped_no_description={adapter_stats['rows_skipped_no_description']} "
        f"censored_observations_built={adapter_stats['censored_observations_built']} "
        f"observations_built={adapter_stats['observations_built']}"
    )

    rows_by_file = load_review_rows(review_dir)
    decisions, errors = validate_and_consolidate(rows_by_file)
    if errors:
        print(f"ERROR: {len(errors)} blocking problem(s) in the review files -- refusing to import:", file=sys.stderr)
        for e in errors[:30]:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    stable_ids = load_stable_id_mapping(stable_id_mapping_path)

    db = SessionLocal()
    try:
        try:
            db.execute(text("SELECT 1 FROM compound_observations LIMIT 1"))
        except Exception:
            print(
                "ERROR: compound_observations table not found -- run the reviewed Alembic migrations "
                "(alembic upgrade head) first. This importer never calls Base.metadata.create_all.",
                file=sys.stderr,
            )
            sys.exit(1)

        actual_manifest = compute_fdc_catalogue_manifest(db)
        drift_error = check_catalogue_drift(stable_ids, actual_manifest.checksum)
        if drift_error:
            print(f"ERROR: {drift_error}", file=sys.stderr)
            sys.exit(1)

        report, problems, plans = reconcile_rows(
            db, rows, adapter_stats, decisions, stable_ids,
            args.dataset_name, args.dataset_citation, args.dataset_version, access_date,
        )
        print_report(report)

        if problems:
            print(f"\n{len(problems)} blocking problem(s) -- refusing to import:", file=sys.stderr)
            for p in problems[:30]:
                print(f"  {p}", file=sys.stderr)
            sys.exit(1)

        if not args.apply:
            print("\n(dry run -- no changes committed; pass --apply plus both --confirm-* flags to write)")
            return

        confirmation_error = check_apply_confirmation(
            args.confirm_dataset_version, args.dataset_version, args.confirm_workbook_checksum, workbook_checksum,
        )
        if confirmation_error:
            print(f"ERROR: {confirmation_error}", file=sys.stderr)
            sys.exit(1)

        try:
            apply_plans(db, plans)
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(f"\nApplied: {report['inserted']} inserted, {report['updated']} updated, "
              f"{report['unchanged']} unchanged.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
