"""Ingest USDA FoodData Central Foundation Foods / SR Legacy CSV exports.

Usage:
    python -m app.ingest_fdc --dir path/to/FoodData_Central_foundation_food_csv_2025-04-24 \
                              --dir path/to/FoodData_Central_sr_legacy_food_csv_2018-04

Each --dir is a directory unzipped from a USDA FDC "Download Datasets" CSV
export (https://fdc.nal.usda.gov/download-datasets.html) — Foundation Foods
and/or SR Legacy. It must contain food.csv, nutrient.csv, food_nutrient.csv.

Only foods with data_type "foundation_food" or "sr_legacy_food" are
considered. Foods without a usable protein value are skipped (amino acid
content can't be expressed per gram protein without it). Individual amino
acids missing from the source data are left null — see
IncompleteAminoAcidProfile in scoring.py for how that's handled at score
time.

FDC does not publish digestibility coefficients, so digestibility_diaas and
digestibility_pdcaas are always left null by this script.

Vitamin/mineral amounts (per 100g) are pulled for every nutrient listed in
micronutrients.NUTRIENTS and stored as FoodNutrient rows — a food simply
has no row for a nutrient FDC didn't report, rather than a null placeholder.
"""

import argparse
import csv
import sys
from pathlib import Path

from .database import Base, SessionLocal, engine
from .micronutrients import NUTRIENTS
from .models import Food, FoodNutrient

WANTED_DATA_TYPES = {"foundation_food", "sr_legacy_food"}

# USDA nutrient numbers (stable across FDC releases, unlike the internal
# nutrient `id`), mapped to our field names. Amino acid / protein fields
# below feed build_amino_acid_profile(); micronutrient fields (from
# micronutrients.NUTRIENTS) map straight through to FoodNutrient rows.
NUTRIENT_NBR_TO_FIELD = {
    "203": "protein",
    "501": "tryptophan",
    "502": "threonine",
    "503": "isoleucine",
    "504": "leucine",
    "505": "lysine",
    "506": "methionine",
    "507": "cystine",
    "508": "phenylalanine",
    "509": "tyrosine",
    "510": "valine",
    "512": "histidine",
    **{d.fdc_nutrient_nbr: key for key, d in NUTRIENTS.items()},
}


def load_nutrient_id_to_nbr(nutrient_csv: Path) -> dict[str, str]:
    with open(nutrient_csv, newline="", encoding="utf-8") as f:
        return {row["id"]: row["nutrient_nbr"].strip() for row in csv.DictReader(f)}


def load_foods(food_csv: Path) -> dict[str, dict]:
    with open(food_csv, newline="", encoding="utf-8") as f:
        return {
            row["fdc_id"]: {"name": row["description"], "data_type": row["data_type"]}
            for row in csv.DictReader(f)
            if row["data_type"] in WANTED_DATA_TYPES
        }


def load_nutrient_amounts(
    food_nutrient_csv: Path, nutrient_id_to_nbr: dict[str, str], wanted_fdc_ids: set[str]
) -> dict[str, dict[str, float]]:
    amounts: dict[str, dict[str, float]] = {}
    with open(food_nutrient_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fdc_id = row["fdc_id"]
            if fdc_id not in wanted_fdc_ids:
                continue
            nbr = nutrient_id_to_nbr.get(row["nutrient_id"])
            field = NUTRIENT_NBR_TO_FIELD.get(nbr)
            if field is None:
                continue
            try:
                amount = float(row["amount"])
            except (ValueError, KeyError):
                continue
            amounts.setdefault(fdc_id, {})[field] = amount
    return amounts


def build_amino_acid_profile(nutrients: dict[str, float]) -> dict[str, float | None] | None:
    protein = nutrients.get("protein")
    if not protein or protein <= 0:
        return None

    def per_g_protein(*fields: str) -> float | None:
        values = [nutrients[f] for f in fields if f in nutrients]
        if len(values) != len(fields):
            return None
        return sum(values) * 1000 / protein

    return {
        "histidine": per_g_protein("histidine"),
        "isoleucine": per_g_protein("isoleucine"),
        "leucine": per_g_protein("leucine"),
        "lysine": per_g_protein("lysine"),
        "met_cys": per_g_protein("methionine", "cystine"),
        "phe_tyr": per_g_protein("phenylalanine", "tyrosine"),
        "threonine": per_g_protein("threonine"),
        "tryptophan": per_g_protein("tryptophan"),
        "valine": per_g_protein("valine"),
    }


def ingest_dir(dir_path: Path, dry_run: bool) -> dict[str, int]:
    stats = {
        "considered": 0, "skipped_no_protein": 0, "inserted": 0, "updated": 0, "complete": 0,
        "nutrient_rows": 0,
    }

    foods = load_foods(dir_path / "food.csv")
    nutrient_id_to_nbr = load_nutrient_id_to_nbr(dir_path / "nutrient.csv")
    amounts = load_nutrient_amounts(dir_path / "food_nutrient.csv", nutrient_id_to_nbr, set(foods))

    db = SessionLocal()
    try:
        for i, (fdc_id, food_info) in enumerate(foods.items(), start=1):
            stats["considered"] += 1
            nutrients = amounts.get(fdc_id, {})
            protein = nutrients.get("protein")
            profile = build_amino_acid_profile(nutrients)
            if profile is None:
                stats["skipped_no_protein"] += 1
                continue
            if all(v is not None for v in profile.values()):
                stats["complete"] += 1

            if dry_run:
                continue

            existing = db.query(Food).filter(Food.fdc_id == int(fdc_id)).one_or_none()
            if existing is None:
                food = Food(
                    name=food_info["name"],
                    protein_g_per_100g=protein,
                    amino_acids=profile,
                    fdc_id=int(fdc_id),
                    data_type=food_info["data_type"],
                )
                db.add(food)
                db.flush()
                stats["inserted"] += 1
            else:
                food = existing
                food.name = food_info["name"]
                food.protein_g_per_100g = protein
                food.amino_acids = profile
                food.data_type = food_info["data_type"]
                db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).delete()
                stats["updated"] += 1

            for key in NUTRIENTS:
                amount = nutrients.get(key)
                if amount is not None:
                    db.add(FoodNutrient(food_id=food.id, nutrient_key=key, amount_per_100g=amount))
                    stats["nutrient_rows"] += 1

            if i % 500 == 0:
                db.commit()

        if not dry_run:
            db.commit()
    finally:
        db.close()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dir", dest="dirs", action="append", required=True,
        help="Path to an unzipped FDC CSV export directory. Repeatable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and report counts without writing to the DB")
    args = parser.parse_args()

    if not args.dry_run:
        Base.metadata.create_all(bind=engine)

    totals = {
        "considered": 0, "skipped_no_protein": 0, "inserted": 0, "updated": 0, "complete": 0,
        "nutrient_rows": 0,
    }
    for dir_arg in args.dirs:
        dir_path = Path(dir_arg)
        if not dir_path.is_dir():
            print(f"error: not a directory: {dir_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Ingesting {dir_path}...")
        stats = ingest_dir(dir_path, args.dry_run)
        for k, v in stats.items():
            totals[k] += v
        print(f"  considered={stats['considered']} skipped_no_protein={stats['skipped_no_protein']} "
              f"inserted={stats['inserted']} updated={stats['updated']} complete_profile={stats['complete']} "
              f"nutrient_rows={stats['nutrient_rows']}")

    print(f"Total: considered={totals['considered']} skipped_no_protein={totals['skipped_no_protein']} "
          f"inserted={totals['inserted']} updated={totals['updated']} complete_profile={totals['complete']} "
          f"nutrient_rows={totals['nutrient_rows']}")


if __name__ == "__main__":
    main()
