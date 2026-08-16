#!/usr/bin/env python3
"""check_consistency.py — structural/cross-file audit of the phytate
review_*.csv files, run before trusting or signing off on any of them.

Catches the two classes of error that actually happened during this
review (not hypothetical): a positional-index transcription bug (notes
landing on the wrong row after a batch edit -- caught once by luck via a
spot-check, not by any tooling) and cross-file duplication (a row
reviewed independently in two files with no way to tell they disagree).
This script is the tooling that should have caught both automatically.

Checks:
  1. review_verdict is one of the allowed values.
  2. Verdict/field consistency: approve|replace rows must have
     approved_fdc_food set and rejection_reason blank; reject rows the
     reverse; every non-blank verdict must have match_scope set (except
     reject, which may leave it blank or "unusable").
  3. Every blank-verdict row must carry a DEFERRED/MOVED note explaining
     why it has no verdict here -- a blank verdict with no explanation is
     a real gap, not an intentional deferral.
  4. Cross-file: no row_identifier should carry a real (non-blank)
     verdict in more than one file -- that would mean the same row was
     independently reviewed twice, possibly with different answers, with
     nothing to flag the disagreement.
  5. Cross-file: every DEFERRED/MOVED row_identifier in one file should
     actually exist with a real verdict in the file its note points to
     -- catches a broken or stale cross-reference.

Usage:
    python check_consistency.py [--dir .]
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ALLOWED_VERDICTS = {"", "approve", "reject", "replace", "unresolved"}

# The canonical review files this review actually produced and tracks.
# review_2_no_candidate_enriched.csv is deliberately excluded: it's a
# scratch/working file from search_no_candidate.py, not a review file
# with its own review_verdict column that matters for sign-off.
CANONICAL_FILES = [
    "review_1_ambiguous.csv",
    "review_2_no_candidate.csv",
    "review_3_branded_low_confidence.csv",
    "review_4_special_cases.csv",
    "review_5_infant_flour_cluster.csv",
    "review_6_accepted_sample.csv",
    "review_6b_accepted_remainder.csv",
]

_FILENAME_RE = re.compile(r"(review_\w+\.csv)")


def load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_row_fields(path_name: str, rows: list[dict]) -> list[str]:
    problems = []
    for r in rows:
        rid = r.get("row_identifier", "<no id>")
        verdict = r.get("review_verdict", "")
        approved = r.get("approved_fdc_food", "")
        reason = r.get("rejection_reason", "")
        scope = r.get("match_scope", "")
        notes = r.get("review_notes", "")

        if verdict not in ALLOWED_VERDICTS:
            problems.append(f"{path_name} {rid}: unrecognised review_verdict {verdict!r}")
            continue

        if verdict in ("approve", "replace"):
            if not approved.strip():
                problems.append(f"{path_name} {rid}: verdict={verdict} but approved_fdc_food is blank")
            if reason.strip():
                problems.append(f"{path_name} {rid}: verdict={verdict} but rejection_reason is set ({reason[:60]!r})")
            if not scope.strip():
                problems.append(f"{path_name} {rid}: verdict={verdict} but match_scope is blank")
        elif verdict == "reject":
            if approved.strip():
                problems.append(f"{path_name} {rid}: verdict=reject but approved_fdc_food is set ({approved[:60]!r})")
            if not reason.strip():
                problems.append(f"{path_name} {rid}: verdict=reject but rejection_reason is blank")
            if scope.strip() not in ("", "unusable"):
                problems.append(f"{path_name} {rid}: verdict=reject but match_scope={scope!r} (expected blank or 'unusable')")
        elif verdict == "unresolved":
            if approved.strip():
                problems.append(f"{path_name} {rid}: verdict=unresolved but approved_fdc_food is set")
        elif verdict == "":
            # review_3's sampled_for_review column marks ~628 rows as
            # intentionally out of scope (only the YES-sampled 120 were
            # meant to be reviewed) -- a blank verdict there is by design,
            # not a gap, so skip those rather than flagging every one.
            if r.get("sampled_for_review", "YES") == "NO":
                continue
            if "DEFERRED" not in notes and "MOVED" not in notes:
                problems.append(f"{path_name} {rid}: blank verdict with no DEFERRED/MOVED explanation -- looks like an unreviewed gap, not an intentional deferral")

    return problems


def check_cross_file(all_rows: dict[str, list[dict]]) -> tuple[list[str], list[str]]:
    """Returns (hard_problems, informational_notes). A row_identifier
    reviewed independently in >1 file is only a hard problem when the
    candidate is the SAME and the verdict DIFFERS -- a genuine
    disagreement between two independent judgments (including against an
    existing human sign-off, which is the more serious version of this).
    Same row_identifier + same candidate + same verdict is a harmless
    duplicate (redundant work, not a correctness issue). Same
    row_identifier + DIFFERENT candidate means the two files were built
    from different ingestion runs (e.g. review_4 predates the Prompt 3B
    regeneration -- see export_needs_review.py's own docstring) and
    aren't reviewing the same match at all, so it's not a disagreement
    either -- just flagged for awareness."""
    hard_problems = []
    info = []

    # row_identifier -> list of (file, verdict, candidate) for every non-blank verdict
    verdict_locations: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for fname, rows in all_rows.items():
        for r in rows:
            rid = r.get("row_identifier", "")
            verdict = r.get("review_verdict", "")
            if rid and verdict:
                verdict_locations[rid].append((fname, verdict, r.get("candidate", "")))

    for rid, locations in verdict_locations.items():
        files_involved = {f for f, _, _ in locations}
        if len(files_involved) <= 1:
            continue
        candidates = {c for _, _, c in locations}
        verdicts = {v for _, v, _ in locations}
        detail = ", ".join(f"{f}={v}" for f, v, _ in locations)
        if len(candidates) == 1 and len(verdicts) > 1:
            hard_problems.append(f"REAL CONFLICT: {rid} reviewed against the SAME candidate in {len(files_involved)} files with DIFFERENT verdicts -- {detail} -- resolve by hand, one of these is wrong")
        elif len(candidates) > 1:
            info.append(f"stale/different candidate (not a live conflict): {rid} -- {detail} -- these files were built from different ingestion runs, not disagreeing about the same match")
        else:
            info.append(f"harmless duplicate (same verdict both times, just redundant work): {rid} -- {detail}")

    # every DEFERRED/MOVED note should name a file that actually has this row_identifier verdicted
    ids_by_file: dict[str, set[str]] = {
        fname: {r.get("row_identifier", "") for r in rows if r.get("review_verdict")}
        for fname, rows in all_rows.items()
    }
    for fname, rows in all_rows.items():
        for r in rows:
            notes = r.get("review_notes", "")
            if "DEFERRED" not in notes and "MOVED" not in notes:
                continue
            rid = r.get("row_identifier", "")
            targets = set(_FILENAME_RE.findall(notes))
            if not targets:
                hard_problems.append(f"{fname} {rid}: DEFERRED/MOVED note doesn't name a target file -- can't verify the cross-reference")
                continue
            for target in targets:
                if target == fname:
                    continue
                if target not in ids_by_file:
                    hard_problems.append(f"{fname} {rid}: note points to {target}, which isn't one of the canonical review files")
                elif rid not in ids_by_file[target]:
                    hard_problems.append(f"{fname} {rid}: note points to {target}, but that file has no verdicted row with this row_identifier -- broken or stale cross-reference")

    return hard_problems, info

    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=".", help="Directory containing the review_*.csv files")
    args = parser.parse_args()

    base = Path(args.dir)
    all_rows: dict[str, list[dict]] = {}
    missing = []
    for fname in CANONICAL_FILES:
        path = base / fname
        if not path.is_file():
            missing.append(fname)
            continue
        all_rows[fname] = load(path)

    if missing:
        print("WARNING: expected files not found (skipped): " + ", ".join(missing))

    all_problems = []
    for fname, rows in all_rows.items():
        all_problems.extend(check_row_fields(fname, rows))
    cross_problems, cross_info = check_cross_file(all_rows)
    all_problems.extend(cross_problems)

    total_rows = sum(len(rows) for rows in all_rows.values())
    print(f"checked {len(all_rows)} files, {total_rows} rows total")
    print(f"problems found: {len(all_problems)}")
    print()
    for p in all_problems:
        print(" -", p)

    if cross_info:
        print()
        print(f"informational (not blocking, {len(cross_info)} items) -- cross-file duplicates that aren't a live conflict:")
        for i in cross_info:
            print(" -", i)

    if all_problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
