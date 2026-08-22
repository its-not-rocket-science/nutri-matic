"""PROMPT 3C of the phytate/mineral-bioavailability extension (see
prompts.txt) — applies the human-reviewed verdicts in
docs/phytate-review/review_*.csv to the CompoundObservation rows
ingest_phytate.py already created, closing Prompt 3's needs-review gate
for the rows those files cover.

Reads all seven review files directly (not just
docs/phytate-review/final_approved_mapping.csv, which only carries the
approve/replace subset — this script also needs every reject/unresolved
verdict, to clear a wrong auto-match rather than leave it standing) and
applies the same validation export_final_mapping.py does: refuses to run
if any row has a blank verdict with no DEFERRED/MOVED/sampled_for_review
explanation, if a row_identifier's verdict contradicts another file's
verdict for the same candidate without being marked superseded, or if an
approve/replace row is missing approved_fdc_food, match_scope, or a
reviewer.

match_relationship mapping (see stock_recipes/ingredient_aliases.py's
AliasRelationship docstring for what each value means in that shared
vocabulary; CompoundObservation's CheckConstraint permits a subset of
it — exact/regional_equivalent/close_analogue/category_proxy/
needs_review, no reviewed_substitution):

  - approve: the pipeline's own suggested candidate, confirmed correct
    by a human. Every approve row in the reviewed files carries
    match_scope="category_estimate" (no row in this review claimed
    literal, source-verified identity), so "exact" would overclaim what
    was actually checked. Mapped to close_analogue (0.8) — "the closest
    nutritional match available", now human-confirmed rather than only
    algorithmically suggested.
  - replace: the pipeline's own suggestion was wrong; a human found a
    different candidate by hand, generally because no closer FDC entry
    exists for the food's specific grain/species/form (see
    review_5/6/6b's recurring "no dedicated FDC entry, fell back to the
    generic" pattern). Mapped to category_proxy (0.65) — "a broad
    stand-in for a whole category the database has no entry for at
    all" — deliberately weaker than approve's close_analogue, since a
    replace means the automated pipeline found nothing usable at all
    and a human had to substitute a coarser stand-in.
  - reject/unresolved: matched_food_id cleared to NULL (never left
    standing on a match a human rejected) and match_relationship set to
    needs_review, so a wrong auto-match can't silently keep counting as
    a real match anywhere downstream.

Idempotent by construction: this script only ever UPDATEs existing
CompoundObservation rows found by their (compound, source_dataset_name,
source_dataset_version, source_row_identifier) unique key — it never
inserts, so re-running with the same review files and the same DB state
reproduces the same end state.
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import CompoundObservation, Food

COMPOUND = "phytate"

# All seven review files -- review_2 (entirely "unresolved" verdicts) is
# not in export_final_mapping.py's SOURCE_FILES since that script only
# cares about approve/replace, but this script must clear/confirm
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


@dataclass
class Decision:
    row_identifier: str
    verdict: str  # approve | replace | reject | unresolved
    approved_fdc_food: str
    candidate_data_type: str
    rationale: str
    source_file: str


def load_review_rows(review_dir: Path) -> dict[str, list[dict]]:
    rows_by_file = {}
    for fname in REVIEW_FILES:
        with open(review_dir / fname, encoding="utf-8", newline="") as f:
            rows_by_file[fname] = list(csv.DictReader(f))
    return rows_by_file


def validate_and_consolidate(rows_by_file: dict[str, list[dict]]) -> tuple[dict[str, Decision], list[str]]:
    """Returns (row_identifier -> Decision, blocking errors). If errors is
    non-empty, the caller must not proceed -- see module docstring and
    prompts.txt PROMPT 3C requirement 4."""
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
                    )

    return decisions, errors


def apply_reviewed_mappings(
    db: Session, decisions: dict[str, Decision], dataset_name: str, dataset_version: str, dry_run: bool,
) -> dict:
    stats = {"approved": 0, "replaced": 0, "rejected": 0, "not_found": 0, "food_not_found": 0}

    for rid, decision in decisions.items():
        obs = (
            db.query(CompoundObservation)
            .filter(
                CompoundObservation.compound == COMPOUND,
                CompoundObservation.source_dataset_name == dataset_name,
                CompoundObservation.source_dataset_version == dataset_version,
                CompoundObservation.source_row_identifier == rid,
            )
            .one_or_none()
        )
        if obs is None:
            stats["not_found"] += 1
            continue

        if decision.verdict == "approve":
            obs.match_relationship = "close_analogue"
            obs.match_confidence = CLOSE_ANALOGUE_CONFIDENCE
            obs.match_rationale = f"Human-reviewed (approved pipeline's own match): {decision.rationale}"
            stats["approved"] += 1

        elif decision.verdict == "replace":
            query = db.query(Food).filter(Food.name == decision.approved_fdc_food)
            if decision.candidate_data_type:
                query = query.filter(Food.data_type == decision.candidate_data_type)
            food = query.one_or_none()
            if food is None:
                stats["food_not_found"] += 1
                continue
            obs.matched_food_id = food.id
            obs.match_relationship = "category_proxy"
            obs.match_confidence = CATEGORY_PROXY_CONFIDENCE
            obs.match_rationale = f"Human-reviewed (replaced with a manually found candidate): {decision.rationale}"
            stats["replaced"] += 1

        else:  # reject, unresolved
            obs.matched_food_id = None
            obs.match_relationship = "needs_review"
            obs.match_confidence = None
            obs.match_rationale = f"Human-reviewed ({decision.verdict}): {decision.rationale}"
            stats["rejected"] += 1

    if not dry_run:
        db.commit()

    stats["still_needs_review"] = (
        db.query(CompoundObservation)
        .filter(CompoundObservation.compound == COMPOUND, CompoundObservation.match_relationship == "needs_review")
        .count()
    )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--review-dir", default=str(Path(__file__).resolve().parents[2] / "docs" / "phytate-review"),
        help="Directory containing the review_*.csv files (default: docs/phytate-review relative to the repo root)",
    )
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows_by_file = load_review_rows(Path(args.review_dir))
    decisions, errors = validate_and_consolidate(rows_by_file)

    if errors:
        print(f"ERROR: {len(errors)} blocking problem(s) in the review files -- refusing to import:", file=sys.stderr)
        for e in errors[:30]:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        stats = apply_reviewed_mappings(db, decisions, args.dataset_name, args.dataset_version, args.dry_run)
    finally:
        db.close()

    print(f"approved: {stats['approved']}")
    print(f"replaced: {stats['replaced']}")
    print(f"rejected/unresolved: {stats['rejected']}")
    print(f"not found in database: {stats['not_found']}")
    print(f"replace target food not found: {stats['food_not_found']}")
    print(f"observations still needs_review after import: {stats['still_needs_review']}")
    if args.dry_run:
        print("(dry run -- no changes committed)")


if __name__ == "__main__":
    main()
