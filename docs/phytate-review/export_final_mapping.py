#!/usr/bin/env python3
"""Step 7 (sign-off) of phytate-review-protocol.txt.

Consolidates every approve/replace row across the reviewed buckets into
one final approved-mapping list: row_identifier -> approved_fdc_food.
This list, not the raw needs_review files, is what Prompt 2/3's
ingestion should actually import.

Excludes rows explicitly marked superseded (rows that defer to another
file's prior sign-off, per the cross-file consistency check) so each
row_identifier appears at most once. Validates every row itself rather
than trusting the input files are already clean -- refuses to export if
any approve/replace row lacks a reviewer or a match_scope, or if a
row_identifier is approved/replaced in one file while rejected (against
the same candidate) in another and that contradiction isn't flagged as
superseded. check_consistency.py catches the same class of problem, but
this script must not silently emit a wrong "approved" list just because
someone forgot to re-run it.
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
    missing_scope = []
    # every verdicted row (any verdict), so a reject elsewhere is visible
    # when validating an approve/replace -- not just other approve/replace
    # rows, which is the gap that let review_3/review_4's contradictory
    # verdicts on 03020186:PHYTCPP and 03020189:PHYTCPP both get exported
    # as approved.
    all_verdicts: dict[str, list[tuple[str, str, str]]] = {}

    rows_by_file = {}
    for fname in SOURCE_FILES:
        with open(here / fname, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        rows_by_file[fname] = rows
        for row in rows:
            verdict = row["review_verdict"]
            if not verdict:
                continue
            rid = row["row_identifier"]
            all_verdicts.setdefault(rid, []).append((fname, verdict, row["candidate"]))

    for fname in SOURCE_FILES:
        for row in rows_by_file[fname]:
            if row["review_verdict"] not in ("approve", "replace"):
                continue
            superseded_note = "MOVED -- superseded" in row.get("review_notes", "")
            if superseded_note:
                superseded += 1
                continue
            if not row["reviewer"]:
                unreviewed.append((fname, row["row_identifier"]))
                continue
            if not row.get("match_scope", "").strip():
                missing_scope.append((fname, row["row_identifier"]))
                continue

            rid = row["row_identifier"]
            candidate = row["candidate"]
            contradicted_by = [
                f2 for f2, v2, c2 in all_verdicts.get(rid, [])
                if f2 != fname and v2 == "reject" and c2 == candidate
            ]
            if contradicted_by:
                conflicts.append((rid, fname, contradicted_by[0]))
                continue

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

    if missing_scope:
        print(f"ERROR: {len(missing_scope)} approve/replace rows have no match_scope:", file=sys.stderr)
        for fname, rid in missing_scope[:20]:
            print(f"  {fname}: {rid}", file=sys.stderr)
        sys.exit(1)

    if conflicts:
        print(f"ERROR: {len(conflicts)} row_identifier conflicts not flagged as superseded:", file=sys.stderr)
        for rid, f1, f2 in conflicts:
            print(f"  {rid}: appears in both {f1} and {f2} with a contradictory verdict", file=sys.stderr)
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
