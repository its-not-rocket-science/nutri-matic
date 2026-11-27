"""Golden report for en-GB food search (read-only).

Runs the 34 golden queries (tests/fixtures/search_golden_en_gb.json, the
queries from docs/plans/canonical-foods-plan.md section 1.2) through the
real `search_foods_by_name_hits` against whatever database DATABASE_URL
points at, and prints the plan's 1.2 table: top 5 per query, a verdict for
the top result, and timings.

    python -m app.search_golden_report [--golden PATH] [--limit 15]

Every transaction is read-only (`SET default_transaction_read_only = on`
on each connection), so it is safe against a production copy. The golden
SQLite tests (tests/test_search_golden.py) use the same `judge()` so the
CI fixture and the full-catalogue run grade results the same way.

Verdicts: ok = the top result is a sensible generic answer; branded = it
is the right food but a branded/US product where a generic exists (or
none exists); wrong = the wrong food.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

DEFAULT_GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "search_golden_en_gb.json"
_TYPE_CODES = {"foundation_food": "F", "sr_legacy_food": "SR", "branded_food": "B"}


def load_golden(path: Path = DEFAULT_GOLDEN) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_generic(data_type: str | None) -> bool:
    return data_type in ("foundation_food", "sr_legacy_food")


def top1_ok(entry: dict, fdc_id: int | None, name: str, data_type: str | None) -> bool:
    spec = entry.get("top1")
    if not spec:
        return False
    if fdc_id is not None and fdc_id in spec.get("fdc_ids", []):
        return True
    pattern = spec.get("name_regex")
    if pattern and re.search(pattern, name, re.IGNORECASE):
        return is_generic(data_type) or not spec.get("generic", False)
    return False


def judge(entry: dict, top: list[tuple[int | None, str, str | None]]) -> str:
    """Verdict for a result list of (fdc_id, name, data_type)."""
    if not top:
        return "wrong"
    fdc_id, name, data_type = top[0]
    if top1_ok(entry, fdc_id, name, data_type):
        return "ok"
    if re.search(entry["right_food"], name, re.IGNORECASE):
        return "branded"
    return "wrong"


def must_not_violations(entry: dict, names: list[str]) -> list[str]:
    return [
        f"{pattern!r} matched {name!r}"
        for pattern in entry.get("must_not_in_top5", [])
        for name in names[:5]
        if re.search(pattern, name, re.IGNORECASE)
    ]


_SYMBOL = {"ok": "✓", "branded": "~", "wrong": "✗"}


def _run(golden_path: Path, limit: int) -> int:
    from sqlalchemy import event

    from .database import SessionLocal, engine
    from .search import search_foods_by_name_hits

    @event.listens_for(engine, "connect")
    def _read_only(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET default_transaction_read_only = on")
        cursor.close()
        dbapi_conn.commit()

    golden = load_golden(golden_path)
    db = SessionLocal()
    timings, counts, rows = [], {"ok": 0, "branded": 0, "wrong": 0}, []
    try:
        for entry in golden["queries"]:
            start = time.perf_counter()
            hits = search_foods_by_name_hits(db, entry["query"], limit=limit, locale=golden["locale"])
            elapsed = time.perf_counter() - start
            db.rollback()
            timings.append(elapsed)
            top = [(h.food.fdc_id, h.food.name, h.food.data_type) for h in hits]
            verdict = judge(entry, top)
            counts[verdict] += 1
            cells = []
            for hit in hits[:5]:
                code = _TYPE_CODES.get(hit.food.data_type, "?")
                badge = f" [{hit.preparation_label}]" if hit.preparation_label else ""
                note = f" ({hit.note})" if hit.note else ""
                cells.append(f"{code}: {hit.food.name[:60]}{badge}{note}")
            violations = must_not_violations(entry, [h.food.name for h in hits])
            flag = f" — must-not: {'; '.join(violations)}" if violations else ""
            rows.append(
                f"| {entry['n']} | {entry['query']} | {' · '.join(cells)} | "
                f"{_SYMBOL[entry['before']]} → {_SYMBOL[verdict]}{flag} | {elapsed * 1000:.0f} ms |"
            )
    finally:
        db.close()

    print("| # | Query | Top 5 (type: name [preparation] (note)) | Before → after | Time |")
    print("|---|---|---|:-:|--:|")
    for row in rows:
        print(row)
    before = {k: sum(1 for e in golden["queries"] if e["before"] == k) for k in counts}
    print()
    print(f"Before (plan 1.2): {before['ok']} ✓, {before['branded']} ~, {before['wrong']} ✗")
    print(f"After:             {counts['ok']} ✓, {counts['branded']} ~, {counts['wrong']} ✗")
    print(f"Latency: p50 {statistics.median(timings) * 1000:.0f} ms, max {max(timings) * 1000:.0f} ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--limit", type=int, default=15, help="Result limit per query (the frontend uses 15)")
    args = parser.parse_args(argv)
    return _run(args.golden, args.limit)


if __name__ == "__main__":
    sys.exit(main())
