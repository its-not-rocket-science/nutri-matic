"""Backfill DIAAS and PDCAAS digestibility onto ingested foods that don't
have them yet, using the rules in digestibility_reference.py.

Usage:
    python -m app.assign_digestibility [--dry-run] [--overwrite]

Only touches fields that are currently null, unless --overwrite is passed
(re-applies rules to every food, e.g. after editing digestibility_reference.py).
DIAAS and PDCAAS are backfilled independently — a food can pick up one
without the other if only one has a matching rule.
"""

import argparse

from sqlalchemy import or_

from .database import SessionLocal
from .digestibility_reference import lookup_diaas, lookup_pdcaas
from .models import Food
from .reference_patterns import AMINO_ACIDS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Re-run rules on every food, not just unset fields")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Food)
        if not args.overwrite:
            query = query.filter(
                or_(Food.digestibility_diaas.is_(None), Food.digestibility_pdcaas.is_(None))
            )
        foods = query.all()

        stats = {
            "diaas_measured": 0, "diaas_estimated": 0, "diaas_unmatched": 0,
            "pdcaas_measured": 0, "pdcaas_estimated": 0, "pdcaas_unmatched": 0,
        }

        for i, food in enumerate(foods, start=1):
            if args.overwrite or food.digestibility_diaas is None:
                result = lookup_diaas(food.name)
                if result is None:
                    stats["diaas_unmatched"] += 1
                else:
                    coefficients, source = result
                    if isinstance(coefficients, dict):
                        food.digestibility_diaas = {aa: coefficients.get(aa) for aa in AMINO_ACIDS}
                    else:
                        food.digestibility_diaas = {aa: coefficients for aa in AMINO_ACIDS}
                    food.digestibility_diaas_source = source
                    stats[f"diaas_{source}"] += 1

            if args.overwrite or food.digestibility_pdcaas is None:
                result = lookup_pdcaas(food.name)
                if result is None:
                    stats["pdcaas_unmatched"] += 1
                else:
                    coefficient, source = result
                    food.digestibility_pdcaas = coefficient
                    food.digestibility_pdcaas_source = source
                    stats[f"pdcaas_{source}"] += 1

            if not args.dry_run and i % 500 == 0:
                db.commit()

        if not args.dry_run:
            db.commit()

        print(f"considered={len(foods)}")
        print(
            f"diaas: measured={stats['diaas_measured']} estimated={stats['diaas_estimated']} "
            f"unmatched={stats['diaas_unmatched']}"
        )
        print(
            f"pdcaas: measured={stats['pdcaas_measured']} estimated={stats['pdcaas_estimated']} "
            f"unmatched={stats['pdcaas_unmatched']}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
