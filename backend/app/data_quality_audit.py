"""Data-quality audit report (public-launch hardening prompt 3, item 6):
lists every ingested `FoodNutrient` row `data_quality.assess_plausibility`
flags as "review" or "excluded", grouped by nutrient and by source
(`Food.data_type`) so a maintainer can see where implausible/unusual
values actually come from — is it one nutrient, one source, or spread
evenly? — rather than only ever seeing them one at a time on an
individual food's own page.

Read-only: never modifies anything, purely reads FoodNutrient/Food and
reports. Safe to run against production directly (no write access
needed at all).

Usage:
    python -m app.data_quality_audit                  # full report to stdout
    python -m app.data_quality_audit --disposition excluded   # excluded rows only
"""

import argparse
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .data_quality import assess_plausibility
from .database import SessionLocal
from .models import Food, FoodNutrient


@dataclass(frozen=True)
class AuditRow:
    food_id: int
    food_name: str
    data_type: str | None
    nutrient_key: str
    amount_per_100g: float
    multiple: float | None
    disposition: str  # "review" | "excluded" — "ok" rows are never included
    reason: str


def run_audit(db: Session, *, dispositions: set[str] | None = None) -> list[AuditRow]:
    """Every FoodNutrient row whose disposition is in `dispositions`
    (default: both "review" and "excluded" — everything worth a look).
    Never includes "ok" rows regardless of what's passed."""
    wanted = (dispositions or {"review", "excluded"}) - {"ok"}

    foods_by_id = {f.id: f for f in db.query(Food).all()}
    rows: list[AuditRow] = []
    for fn in db.query(FoodNutrient).all():
        assessment = assess_plausibility(fn.nutrient_key, fn.amount_per_100g)
        if assessment.disposition not in wanted:
            continue
        food = foods_by_id.get(fn.food_id)
        rows.append(
            AuditRow(
                food_id=fn.food_id,
                food_name=food.name if food else "(unknown food)",
                data_type=food.data_type if food else None,
                nutrient_key=fn.nutrient_key,
                amount_per_100g=fn.amount_per_100g,
                multiple=assessment.multiple,
                disposition=assessment.disposition,
                reason=assessment.reason or "",
            )
        )
    rows.sort(key=lambda r: (r.multiple is None, -(r.multiple or 0)))
    return rows


def _print_report(rows: list[AuditRow]) -> None:
    print(f"{len(rows)} flagged row(s)\n")

    by_nutrient = Counter((r.nutrient_key, r.disposition) for r in rows)
    print("By nutrient:")
    for (key, disposition), count in sorted(by_nutrient.items()):
        print(f"  {key:20s} {disposition:10s} {count}")

    by_source = Counter((r.data_type or "(unknown)", r.disposition) for r in rows)
    print("\nBy source/data type:")
    for (data_type, disposition), count in sorted(by_source.items()):
        print(f"  {data_type:20s} {disposition:10s} {count}")

    print("\nRows (highest multiple first):")
    for r in rows:
        multiple_str = f"{r.multiple:,.0f}x" if r.multiple is not None else "n/a"
        print(
            f"  food_id={r.food_id} [{r.data_type or 'unknown'}] {r.food_name!r} "
            f"{r.nutrient_key}={r.amount_per_100g:g} ({multiple_str}) -> {r.disposition}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--disposition", choices=["review", "excluded"], action="append",
        help="Restrict to one disposition. Repeatable. Default: both.",
    )
    args = parser.parse_args(argv)
    dispositions = set(args.disposition) if args.disposition else None

    db = SessionLocal()
    try:
        rows = run_audit(db, dispositions=dispositions)
        _print_report(rows)
    finally:
        db.close()


if __name__ == "__main__":
    main()
