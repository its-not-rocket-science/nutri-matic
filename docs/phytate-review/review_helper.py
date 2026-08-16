#!/usr/bin/env python3
"""
review_helper.py — automates the mechanical parts of the phytate match
review: finding bug-1 instances (selected candidate scored lower than
an available alternative), cross-referencing against already-decided
rows, and (optionally) enriching remaining open rows with live-database
context so a human doesn't have to hand-type a psql query for each one.

This script NEVER sets review_verdict itself for a match-quality
judgment call. It only surfaces evidence faster. The distinction matters
and is deliberate — see this repo's phytate-review-protocol.txt and the
"infrastructure enables representing confidence, it does not itself
validate a match" principle established during this review.

The one exception: --mode crossref will mark a row's suggested_action
as "ALREADY DECIDED — see <file>" when it's found with a filled-in
review_verdict elsewhere. That's bookkeeping, not a new judgment.

USAGE
-----
Stage 1 (no database needed, run anywhere):
    python review_helper.py crossref \
        --needs-review needs_review_full.csv \
        --decided-files review_4_special_cases.csv review_5_infant_flour_cluster.csv \
        --out bug1_open_prioritized.csv

Stage 2 (needs a live DB connection — run on the server, or anywhere
with DATABASE_URL pointed at a reachable Postgres):
    python review_helper.py enrich \
        --in bug1_open_prioritized.csv \
        --out bug1_open_enriched.csv \
        --database-url "$DATABASE_URL"

Re-run crossref any time you've filled in more verdicts elsewhere —
it's cheap and always recomputes from scratch rather than assuming
anything about prior runs.
"""

import argparse
import csv
import re
import sys


# ---------------------------------------------------------------------
# Stage 1: crossref
# ---------------------------------------------------------------------

SIMILARITY_PAIR_RE = re.compile(r"\(([\d.]+)\s+vs\s+([\d.]+)\s+similarity\)")


def load_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def find_bug1_instances(needs_review_rows):
    """Every row where the selected candidate's rationale-quoted score is
    lower than an unselected alternative's score — the exact pattern
    confirmed as Prompt 3B bug 1."""
    instances = []
    for r in needs_review_rows:
        m = SIMILARITY_PAIR_RE.search(r.get("rationale", ""))
        if not m:
            continue
        selected_score, other_score = float(m.group(1)), float(m.group(2))
        if other_score > selected_score:
            row = dict(r)
            row["selected_score"] = selected_score
            row["unselected_alternative_score"] = other_score
            row["score_gap"] = round(other_score - selected_score, 3)
            instances.append(row)
    instances.sort(key=lambda r: -r["score_gap"])
    return instances


def load_decided_row_ids(decided_files):
    """row_identifier -> (source_file, verdict) for every row across the
    given files that already has a non-blank review_verdict."""
    decided = {}
    for path in decided_files:
        rows = load_csv(path)
        for r in rows:
            verdict = r.get("review_verdict", "").strip()
            if verdict:
                decided[r["row_identifier"]] = (path, verdict)
    return decided


def cmd_crossref(args):
    needs_review = load_csv(args.needs_review)
    bug1 = find_bug1_instances(needs_review)
    decided = load_decided_row_ids(args.decided_files) if args.decided_files else {}

    open_count = 0
    already_count = 0
    for row in bug1:
        rid = row["row_identifier"]
        if rid in decided:
            src, verdict = decided[rid]
            row["suggested_action"] = f"ALREADY DECIDED ({verdict}) — see {src}"
            already_count += 1
        else:
            row["suggested_action"] = "OPEN — needs review"
            open_count += 1

    fieldnames = list(bug1[0].keys()) if bug1 else []
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(bug1)

    print(f"Total bug-1 instances found: {len(bug1)}")
    print(f"  Already decided elsewhere: {already_count}")
    print(f"  Still open: {open_count}")
    print(f"Written to {args.out}, sorted by score_gap descending "
          f"(biggest, most-likely-clean fixes first).")


# ---------------------------------------------------------------------
# Stage 2: enrich (needs a live DB connection)
# ---------------------------------------------------------------------

def get_db_connection(database_url):
    try:
        import psycopg2
    except ImportError:
        sys.exit(
            "psycopg2 is required for --mode enrich. Run this inside the "
            "backend container (it's already installed there) via:\n"
            "  docker compose exec backend python review_helper.py enrich ...\n"
            "or `pip install psycopg2-binary` in whatever environment you're "
            "running this from directly."
        )
    return psycopg2.connect(database_url)


def first_significant_word(description):
    """Crude but effective: the food's genus/primary noun is usually the
    first word before a comma, e.g. 'Sesbania, blanched' -> 'Sesbania'."""
    return description.split(",")[0].strip()


def enrich_row(cur, row):
    genus = first_significant_word(row["food_description"])
    genus_prefix = f"{genus}%"
    genus_anywhere = f"%{genus}%"

    # 1. Does a non-branded generic entry exist for this genus at all?
    # Prioritize names that START WITH the genus word (e.g. "Potato, russet, raw")
    # over ones that merely CONTAIN it anywhere (e.g. "Babyfood, corn and sweet
    # potatoes") — plain alphabetical ordering let irrelevant matches crowd out
    # the relevant ones for common genus words. Shorter names next, as a proxy
    # for "plainer/more generic" over compound multi-ingredient products.
    cur.execute(
        """
        SELECT name, data_type FROM foods
        WHERE name ILIKE %s AND data_type != 'branded_food'
        ORDER BY
            CASE WHEN name ILIKE %s THEN 0 ELSE 1 END,
            length(name) ASC,
            name ASC
        LIMIT 20
        """,
        (genus_anywhere, genus_prefix),
    )
    generic_matches = cur.fetchall()
    row["generic_candidates_found"] = len(generic_matches)
    row["generic_candidates_sample"] = " | ".join(f"{n} ({dt})" for n, dt in generic_matches[:5])

    # 2. Full prep-state inventory for this genus, same prioritization.
    cur.execute(
        """
        SELECT name FROM foods
        WHERE name ILIKE %s
        ORDER BY
            CASE WHEN name ILIKE %s THEN 0 ELSE 1 END,
            length(name) ASC,
            name ASC
        LIMIT 30
        """,
        (genus_anywhere, genus_prefix),
    )
    all_matches = [n for (n,) in cur.fetchall()]
    row["all_candidates_for_genus_count"] = len(all_matches)
    row["all_candidates_for_genus_sample"] = " | ".join(all_matches[:8])

    # 3. Cheap heuristic flag: does the unselected alternative candidate
    #    text itself share the genus word? (doesn't replace human judgment,
    #    just flags "this one's worth checking first")
    alt_hint = ""
    rationale = row.get("rationale", "")
    if genus.lower() in rationale.lower():
        alt_hint = "genus word appears in rationale text — worth checking the unselected alternative directly"
    row["quick_hint"] = alt_hint

    return row


def cmd_enrich(args):
    rows = load_csv(args.in_path)
    open_rows = [r for r in rows if r.get("suggested_action", "").startswith("OPEN")]
    print(f"Enriching {len(open_rows)} open rows (skipping {len(rows) - len(open_rows)} already-decided rows)...")

    conn = get_db_connection(args.database_url)
    cur = conn.cursor()

    for i, row in enumerate(open_rows, 1):
        enrich_row(cur, row)
        if i % 50 == 0:
            print(f"  ...{i}/{len(open_rows)}")

    cur.close()
    conn.close()

    extra_fields = [
        "generic_candidates_found", "generic_candidates_sample",
        "all_candidates_for_genus_count", "all_candidates_for_genus_sample",
        "quick_hint",
    ]
    fieldnames = list(rows[0].keys())
    for f in extra_fields:
        if f not in fieldnames:
            fieldnames.append(f)
    # non-open rows won't have the new fields populated; fill blanks so the CSV is well-formed
    for r in rows:
        for f in extra_fields:
            r.setdefault(f, "")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Written to {args.out}")


# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser("crossref", help="Find bug-1 instances and cross-reference against already-decided rows")
    p1.add_argument("--needs-review", required=True, help="Path to needs_review_full.csv")
    p1.add_argument("--decided-files", nargs="*", default=[], help="Paths to review_*.csv files that may have filled-in verdicts")
    p1.add_argument("--out", required=True, help="Output path")
    p1.set_defaults(func=cmd_crossref)

    p2 = sub.add_parser("enrich", help="Add live-database context to open rows (requires DB access)")
    p2.add_argument("--in", dest="in_path", required=True, help="Output of the crossref stage")
    p2.add_argument("--out", required=True, help="Output path")
    p2.add_argument("--database-url", required=True, help="Postgres connection string, e.g. $DATABASE_URL")
    p2.set_defaults(func=cmd_enrich)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
