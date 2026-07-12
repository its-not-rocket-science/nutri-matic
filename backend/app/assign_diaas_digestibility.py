"""Backfill DIAAS digestibility onto ingested foods that don't have it yet,
using the rules in digestibility_reference.py.

Usage:
    python -m app.assign_diaas_digestibility [--dry-run] [--overwrite]

Only touches foods where digestibility_diaas is currently null, unless
--overwrite is passed (re-applies rules to every food, e.g. after editing
digestibility_reference.py).
"""

import argparse

from .database import SessionLocal
from .digestibility_reference import lookup
from .models import Food
from .reference_patterns import AMINO_ACIDS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Re-run rules on every food, not just unset ones")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Food)
        if not args.overwrite:
            query = query.filter(Food.digestibility_diaas.is_(None))
        foods = query.all()

        matched_measured = 0
        matched_estimated = 0
        unmatched = 0

        for i, food in enumerate(foods, start=1):
            result = lookup(food.name)
            if result is None:
                unmatched += 1
                continue

            coefficients, source = result
            if isinstance(coefficients, dict):
                food.digestibility_diaas = {aa: coefficients.get(aa) for aa in AMINO_ACIDS}
            else:
                food.digestibility_diaas = {aa: coefficients for aa in AMINO_ACIDS}
            food.digestibility_diaas_source = source
            if source == "measured":
                matched_measured += 1
            else:
                matched_estimated += 1

            if not args.dry_run and i % 500 == 0:
                db.commit()

        if not args.dry_run:
            db.commit()

        print(f"considered={len(foods)} measured={matched_measured} estimated={matched_estimated} unmatched={unmatched}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
