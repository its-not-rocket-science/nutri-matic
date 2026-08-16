#!/usr/bin/env python3
"""export_needs_review.py — regenerates review_1/2/3/5 from the live
compound_observations table after a phytate ingestion run (PROMPT 3B's
"regenerate the needs_review output" step).

Reads directly from what app.ingest_phytate already computed and stored
per observation (match_rationale, match_confidence, matched_food_id) —
no re-matching happens here, this is a pure export/bucketing pass.

review_4_special_cases.csv is NOT touched by this script: it already has
39/72 rows with real human verdicts and wasn't invalidated by PROMPT 3B's
fixes (see prompts.txt STATUS section) — regenerating it is a separate,
human-in-the-loop step.

Bucketing (mechanical, based on the stored rationale text — see
app.ingest_phytate.classify_match/_ambiguous_candidates for exactly when
each rationale shape is produced):
  - review_1_ambiguous.csv   — rationale starts "top two name-search candidates"
  - review_2_no_candidate.csv — rationale starts "no FDC candidate found"
  - review_3_branded_low_confidence.csv — rationale starts "match confidence"
    AND the candidate is a branded_food (this is the only data_type that
    ever falls under NEEDS_REVIEW_CONFIDENCE_THRESHOLD via the fuzzy tier
    — see dietary_tags.match_confidence). A fixed-seed sample of up to
    120 rows is flagged sampled_for_review=YES, same size as the original
    review's sampling target, for the same reason (a full hand-review of
    a large low-confidence-branded bucket isn't a good use of reviewer
    time — see phytate-review-protocol.txt step 4).
  - review_5_infant_flour_cluster.csv — food_description matches
    /infant/i and /flour/i, cutting across whichever of the three buckets
    above it also falls into (source_bucket column) — this is the
    PROMPT 3B bug 2 cluster; after the fix most of these should no longer
    even be needs_review, so this file is expected to be small or empty.

Does NOT reproduce the original review_1's "794 shortlist vs 1462
spot-sampled-only pool" split — that description-level dedup was never
committed as code (see PROMPT 3B PR discussion), so it isn't
recoverable. Every needs_review OBSERVATION (not deduped by
food_description) gets its own row here, matching what PROMPT 3C's
row_identifier-keyed import expects.

Usage:
    python export_needs_review.py --database-url "$DATABASE_URL" --out-dir .
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import CompoundObservation, Food

REVIEW_COLUMNS = [
    # no match_method column: CompoundObservation doesn't persist
    # MatchResult.method (only relationship/confidence/rationale) — no
    # fabricated value is written for a column this export can't back
    # with real data.
    "row_identifier", "food_description", "compound_fraction", "value",
    "candidate", "candidate_data_type", "match_confidence", "rationale",
    "review_verdict", "approved_fdc_food", "rejection_reason", "match_scope",
    "reviewer", "review_date", "review_notes",
]

# Reproducible sample of review_3's low-confidence-branded bucket — same
# rationale as phytate-review-protocol.txt step 4 (a fixed-size sample
# gives a bounded error-rate margin without hand-reviewing the whole
# bucket). Seed is arbitrary but fixed so re-running this export against
# the same data reproduces the same sample.
BRANDED_SAMPLE_SEED = 20260809
BRANDED_SAMPLE_SIZE = 120


def _row_dict(obs: CompoundObservation, candidate: Food | None) -> dict:
    return {
        "row_identifier": obs.source_row_identifier,
        "food_description": obs.source_food_description,
        "compound_fraction": obs.compound_fraction,
        "value": obs.original_value,
        "candidate": candidate.name if candidate is not None else None,
        "candidate_data_type": candidate.data_type if candidate is not None else None,
        "match_confidence": obs.match_confidence,
        "rationale": obs.match_rationale,
        "review_verdict": "", "approved_fdc_food": "", "rejection_reason": "",
        "match_scope": "", "reviewer": "", "review_date": "", "review_notes": "",
    }


def _write_csv(path: Path, rows: list[dict], extra_columns: list[str] | None = None) -> None:
    import csv as csv_module

    columns = list(REVIEW_COLUMNS)
    if extra_columns:
        # insert extras right before the review_verdict block, same
        # position the original review files used (bucket/context columns
        # first, verdict columns last).
        insert_at = columns.index("review_verdict")
        columns = columns[:insert_at] + extra_columns + columns[insert_at:]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--out-dir", default=".", help="Directory to write review_*.csv into")
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    observations = (
        db.query(CompoundObservation)
        .filter(CompoundObservation.compound == "phytate", CompoundObservation.match_relationship == "needs_review")
        .order_by(CompoundObservation.source_row_identifier)
        .all()
    )
    food_ids = {o.matched_food_id for o in observations if o.matched_food_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()} if food_ids else {}

    ambiguous, no_candidate, branded_low_confidence, infant_flour = [], [], [], []

    for obs in observations:
        candidate = foods_by_id.get(obs.matched_food_id) if obs.matched_food_id is not None else None
        rationale = obs.match_rationale or ""
        row = _row_dict(obs, candidate)

        description_lower = obs.source_food_description.lower()
        is_infant_flour = "infant" in description_lower and "flour" in description_lower

        if rationale.startswith("no FDC candidate found"):
            no_candidate.append(row)
            source_bucket = "no_candidate"
        elif rationale.startswith("top two name-search candidates"):
            ambiguous.append(row)
            source_bucket = "ambiguous"
        elif rationale.startswith("match confidence") and candidate is not None and candidate.data_type == "branded_food":
            branded_low_confidence.append(row)
            source_bucket = "branded_low_confidence"
        else:
            source_bucket = "other"

        if is_infant_flour:
            infant_row = dict(row)
            infant_row["source_bucket"] = source_bucket
            infant_flour.append(infant_row)

    rng = random.Random(BRANDED_SAMPLE_SEED)
    sample_size = min(BRANDED_SAMPLE_SIZE, len(branded_low_confidence))
    sampled_indices = set(rng.sample(range(len(branded_low_confidence)), sample_size))
    for i, row in enumerate(branded_low_confidence):
        row["sampled_for_review"] = "YES" if i in sampled_indices else "NO"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(out_dir / "review_1_ambiguous.csv", ambiguous)
    _write_csv(out_dir / "review_2_no_candidate.csv", no_candidate)
    _write_csv(out_dir / "review_3_branded_low_confidence.csv", branded_low_confidence, extra_columns=["sampled_for_review"])
    _write_csv(out_dir / "review_5_infant_flour_cluster.csv", infant_flour, extra_columns=["source_bucket"])

    other_count = sum(
        1 for o in observations
        if not (o.match_rationale or "").startswith(("no FDC candidate found", "top two name-search candidates"))
        and not (
            (o.match_rationale or "").startswith("match confidence")
            and foods_by_id.get(o.matched_food_id) is not None
            and foods_by_id[o.matched_food_id].data_type == "branded_food"
        )
    )

    print(f"total needs_review observations: {len(observations)}")
    print(f"  review_1 (ambiguous): {len(ambiguous)}")
    print(f"  review_2 (no_candidate): {len(no_candidate)}")
    print(f"  review_3 (branded_low_confidence): {len(branded_low_confidence)} ({sample_size} sampled)")
    print(f"  review_5 (infant_flour_cluster, cross-cutting): {len(infant_flour)}")
    print(f"  uncategorised (needs_review but none of the three rationale patterns above): {other_count}")

    db.close()


if __name__ == "__main__":
    main()
