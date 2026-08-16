#!/usr/bin/env python3
"""Step 7 (sign-off) of phytate-review-protocol.txt.

Consolidates every approve/replace row across the reviewed buckets into
one final approved-mapping list: row_identifier -> approved_fdc_food.
This list, not the raw needs_review files, is what Prompt 2/3's
ingestion should actually import.

Excludes rows explicitly marked superseded (the review_1 rows that defer
to review_4's prior sign-off, per the cross-file consistency check) so
each row_identifier appears at most once. Any remaining true conflict
(same row_identifier approved differently in two files, not flagged as
superseded) is reported and must be resolved by hand before ingestion.
"""

import csv
import sys
from pathlib import Path

SOURCE_FILES = [
    "review_1_ambiguous.csv",
    "review_3_branded_low_confidence.csv",
    "review_4_special_cases.csv",
    "review_5_infant_flour_cluster.csv",
    "review_6_accepted_sample.csv",
    "review_6b_accepted_remainder.csv",
]

OUTPUT_FILE = "final_approved_mapping.csv"

OUTPUT_COLUMNS = [
    "row_identifier",
    "food_description",
    "compound_fraction",
    "value",
    "approved_fdc_food",
    "candidate_data_type",
    "match_scope",
    "review_verdict",
    "source_review_file",
    "reviewer",
    "review_date",
    "review_notes",
]


def main():
    here = Path(__file__).resolve().parent
    accepted = {}
    superseded = 0
    conflicts = []
    unreviewed = []

    for fname in SOURCE_FILES:
        path = here / fname
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row["review_verdict"] not in ("approve", "replace"):
                    continue
                if "MOVED -- superseded" in row.get("review_notes", ""):
                    superseded += 1
                    continue
                if not row["reviewer"]:
                    unreviewed.append((fname, row["row_identifier"]))
                    continue

                rid = row["row_identifier"]
                out_row = {
                    "row_identifier": rid,
                    "food_description": row["food_description"],
                    "compound_fraction": row["compound_fraction"],
                    "value": row["value"],
                    "approved_fdc_food": row["approved_fdc_food"],
                    "candidate_data_type": row.get("candidate_data_type", ""),
                    "match_scope": row.get("match_scope", ""),
                    "review_verdict": row["review_verdict"],
                    "source_review_file": fname,
                    "reviewer": row["reviewer"],
                    "review_date": row["review_date"],
                    "review_notes": row.get("review_notes", ""),
                }

                if rid in accepted:
                    prev = accepted[rid]
                    if prev["approved_fdc_food"] != out_row["approved_fdc_food"]:
                        conflicts.append((rid, prev["source_review_file"], fname))
                    continue

                accepted[rid] = out_row

    if unreviewed:
        print(f"ERROR: {len(unreviewed)} approve/replace rows have no reviewer sign-off yet:", file=sys.stderr)
        for fname, rid in unreviewed[:20]:
            print(f"  {fname}: {rid}", file=sys.stderr)
        sys.exit(1)

    if conflicts:
        print(f"ERROR: {len(conflicts)} row_identifier conflicts not flagged as superseded:", file=sys.stderr)
        for rid, f1, f2 in conflicts:
            print(f"  {rid}: appears in both {f1} and {f2} with different approved_fdc_food", file=sys.stderr)
        sys.exit(1)

    out_path = here / OUTPUT_FILE
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for rid in sorted(accepted):
            writer.writerow(accepted[rid])

    print(f"Wrote {len(accepted)} approved mappings to {OUTPUT_FILE}")
    print(f"({superseded} rows excluded as superseded by a later sign-off)")


if __name__ == "__main__":
    main()
