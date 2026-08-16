#!/usr/bin/env python3
"""export_accepted.py — exports the phytate ingestion's ACCEPTED matches
(match_relationship != "needs_review") for human review, per
phytate-review-protocol.txt step 5. Complements export_needs_review.py,
which only ever covered the needs_review rows — nothing in this repo
exported the accepted side before this script, and per the protocol
that's "the single most important gap across every review so far: ...
these [accepted rows] already can [reach production]" while nothing has
looked at them.

Sampling (protocol step 5b): ALL rows whose source description contains
a cultivar/variety/processing/coagulant qualifier (the details a
"confident" auto-match is most likely to have silently discarded) are
included outright, plus a fixed-seed plain random sample of the
remainder for a general error-rate estimate — same statistical logic as
review_3's 120-of-748 branded sample.

Usage:
    python export_accepted.py --database-url "$DATABASE_URL" --out-dir .
"""

import argparse
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import CompoundObservation, Food

REVIEW_COLUMNS = [
    "row_identifier", "food_description", "compound_fraction", "value",
    "candidate", "candidate_data_type", "match_relationship", "match_confidence",
    "rationale", "sample_stratum",
    "review_verdict", "approved_fdc_food", "rejection_reason", "match_scope",
    "reviewer", "review_date", "review_notes",
]

# Same statistical target as review_3's 120-of-748 sample (protocol step 4);
# applied here to the *remainder* after all high-risk rows are taken outright.
RANDOM_SAMPLE_SEED = 20260815
RANDOM_SAMPLE_SIZE = 125

# Qualifiers a "confident" auto-match is most likely to have silently
# discarded — protocol step 5b's exact list, plus common coagulant names.
_HIGH_RISK_RE = re.compile(
    r"\b("
    r"cultivar|variety|var\.|fermented|germinated|soaked|milled|roasted|"
    r"irradiated|"
    r"CaCl2|MgCl2|CaSO4|nigari"
    r")\b",
    re.IGNORECASE,
)


def _row_dict(obs: CompoundObservation, candidate: Food | None) -> dict:
    return {
        "row_identifier": obs.source_row_identifier,
        "food_description": obs.source_food_description,
        "compound_fraction": obs.compound_fraction,
        "value": obs.original_value,
        "candidate": candidate.name if candidate is not None else None,
        "candidate_data_type": candidate.data_type if candidate is not None else None,
        "match_relationship": obs.match_relationship,
        "match_confidence": obs.match_confidence,
        "rationale": obs.match_rationale,
        "sample_stratum": "",
        "review_verdict": "", "approved_fdc_food": "", "rejection_reason": "",
        "match_scope": "", "reviewer": "", "review_date": "", "review_notes": "",
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    import csv as csv_module

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in REVIEW_COLUMNS})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--out-dir", default=".", help="Directory to write review_6_accepted_sample.csv into")
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    observations = (
        db.query(CompoundObservation)
        .filter(CompoundObservation.compound == "phytate", CompoundObservation.match_relationship != "needs_review")
        .order_by(CompoundObservation.source_row_identifier)
        .all()
    )
    food_ids = {o.matched_food_id for o in observations if o.matched_food_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()} if food_ids else {}

    high_risk, remainder = [], []
    for obs in observations:
        candidate = foods_by_id.get(obs.matched_food_id) if obs.matched_food_id is not None else None
        row = _row_dict(obs, candidate)
        if _HIGH_RISK_RE.search(obs.source_food_description):
            row["sample_stratum"] = "high_risk_keyword"
            high_risk.append(row)
        else:
            remainder.append(row)

    rng = random.Random(RANDOM_SAMPLE_SEED)
    sample_size = min(RANDOM_SAMPLE_SIZE, len(remainder))
    sampled_indices = set(rng.sample(range(len(remainder)), sample_size))
    random_sample = []
    for i, row in enumerate(remainder):
        if i in sampled_indices:
            row["sample_stratum"] = "random_sample"
            random_sample.append(row)

    combined = high_risk + random_sample

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "review_6_accepted_sample.csv", combined)

    print(f"total accepted observations (match_relationship != needs_review): {len(observations)}")
    print(f"  high_risk_keyword (all included): {len(high_risk)}")
    print(f"  remainder: {len(remainder)} -> random_sample: {len(random_sample)}")
    print(f"  written to review_6_accepted_sample.csv: {len(combined)} rows")

    db.close()


if __name__ == "__main__":
    main()
