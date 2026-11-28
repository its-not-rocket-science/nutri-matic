"""Coverage report for the preparation-state classifier (read-only).

    python -m app.preparation_coverage_report [--sample 40] [--no-branded]

Runs `food_preparation.classify_preparation` over every `foods` name in the
database DATABASE_URL points at and prints, per FDC data type:

  * how many rows land in each state;
  * the share whose state the name *states* (anything but `unspecified` or
    `unknown`);
  * for generic (Foundation/SR Legacy) rows, the most common head nouns
    still `unspecified`, and a deterministic sample of them, so a reviewer
    can see what the rules miss;
  * every generic row classified `unknown` (ambiguous name).

`unspecified` is often correct: most processed foods ("Bread, rye",
"Cheese, cheddar") have no preparation state in their name, and the
classifier must not invent one. The report is for spotting cues the rules
miss, not a target to drive to zero.

Every connection is set to `default_transaction_read_only = on`. Only names
are read; nothing is written, and no phytate table is touched.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections import Counter, defaultdict

from .food_preparation import PREPARATION_STATES, UNCLASSIFIED_STATES, classify_preparation

_TYPE_ORDER = ("foundation_food", "sr_legacy_food", "branded_food", None)
_GENERIC = ("foundation_food", "sr_legacy_food")


def _head(name: str) -> str:
    return name.lower().split(",", 1)[0].split("(", 1)[0].strip()


def summarise(rows) -> dict:
    """rows: iterable of (data_type, name). Pure; used by the tests too."""
    counts: dict = defaultdict(Counter)
    unspecified_generic: list[str] = []
    unknown_generic: list[str] = []
    for data_type, name in rows:
        state = classify_preparation(name, data_type)
        counts[data_type][state] += 1
        if data_type in _GENERIC:
            if state == "unspecified":
                unspecified_generic.append(name)
            elif state == "unknown":
                unknown_generic.append(name)
    return {"counts": counts, "unspecified_generic": unspecified_generic, "unknown_generic": unknown_generic}


def _stable_sample(names: list[str], k: int) -> list[str]:
    return sorted(names, key=lambda n: hashlib.md5(n.encode()).hexdigest())[:k]


def render(summary: dict, sample: int) -> str:
    out = []
    counts = summary["counts"]
    out.append("| Data type | Rows | States stated in name | " + " | ".join(PREPARATION_STATES) + " |")
    out.append("|---|--:|--:|" + "--:|" * len(PREPARATION_STATES))
    for data_type in _TYPE_ORDER:
        c = counts.get(data_type)
        if not c:
            continue
        total = sum(c.values())
        stated = total - sum(c[s] for s in UNCLASSIFIED_STATES)
        cells = " | ".join(str(c[s]) for s in PREPARATION_STATES)
        out.append(f"| {data_type or '(none)'} | {total:,} | {stated:,} ({100 * stated / total:.1f}%) | {cells} |")

    heads = Counter(_head(n) for n in summary["unspecified_generic"])
    out.append("")
    out.append(f"Generic rows still `unspecified`: {len(summary['unspecified_generic']):,}. Most common heads:")
    out.append(", ".join(f"{h} ({n})" for h, n in heads.most_common(30)))
    out.append("")
    out.append(f"Sample of {sample} (stable order):")
    out.extend(f"- {n}" for n in _stable_sample(summary["unspecified_generic"], sample))
    out.append("")
    out.append(f"Generic rows `unknown` (ambiguous): {len(summary['unknown_generic'])}")
    out.extend(f"- {n}" for n in sorted(summary["unknown_generic"]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--no-branded", action="store_true", help="Skip the ~1.4M branded rows")
    args = parser.parse_args(argv)

    from sqlalchemy import event, text

    from .database import SessionLocal, engine

    @event.listens_for(engine, "connect")
    def _read_only(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET default_transaction_read_only = on")
        cursor.close()
        dbapi_conn.commit()

    where = "WHERE data_type IS DISTINCT FROM 'branded_food'" if args.no_branded else ""
    start = time.perf_counter()
    db = SessionLocal()
    try:
        rows = db.execute(
            text(f"SELECT data_type, name FROM foods {where}").execution_options(stream_results=True)
        ).yield_per(50_000)
        summary = summarise(rows)
    finally:
        db.close()
    print(render(summary, args.sample))
    print(f"\n({time.perf_counter() - start:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
