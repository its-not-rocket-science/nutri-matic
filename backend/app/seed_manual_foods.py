"""Seed a handful of pure-fat foods that ingest_fdc.py can never carry.

ingest_fdc.py skips any FDC row without a usable protein value (see its
module docstring) — correct for the amino-acid-profile pipeline, but it
means plain cooking oils/ghee have no Food row at all, so a recipe using
them silently drops that ingredient and undercounts its calories/fat.

These rows are hand-entered (not FDC-derived: fdc_id stays null) with
protein_g_per_100g=0.0 and an all-null amino acid profile — aggregation.py
already skips any zero-protein ingredient before it ever looks at amino
acids/digestibility (see aggregate_amino_acids), so these can never block
a recipe's DIAAS/PDCAAS score. Values are standard published macronutrient
figures for each food (commonly reproduced across nutrition references),
not from a specific FDC entry.

Usage:
    python -m app.seed_manual_foods
"""

from .database import SessionLocal
from .models import Food, FoodNutrient
from .reference_patterns import AMINO_ACIDS

NULL_AMINO_ACIDS = dict.fromkeys(AMINO_ACIDS)

MANUAL_FOODS = [
    {
        "name": "Oil, olive",
        "nutrients": {
            "energy": 884,
            "fat_total": 100.0,
            "saturated_fat": 13.8,
            "monounsaturated_fat": 72.96,
            "polyunsaturated_fat": 10.52,
            "la": 9.76,
            "ala": 0.76,
            "vitamin_e": 14.35,
            "vitamin_k1": 60.2,
        },
    },
    {
        "name": "Oil, canola (rapeseed)",
        "nutrients": {
            "energy": 884,
            "fat_total": 100.0,
            "saturated_fat": 7.37,
            "monounsaturated_fat": 63.28,
            "polyunsaturated_fat": 28.14,
            "la": 18.64,
            "ala": 9.14,
            "vitamin_e": 17.46,
            "vitamin_k1": 71.3,
        },
    },
    {
        "name": "Ghee",
        "nutrients": {
            "energy": 900,
            "fat_total": 99.48,
            "saturated_fat": 61.92,
            "monounsaturated_fat": 28.73,
            "polyunsaturated_fat": 3.69,
        },
    },
]


def main() -> None:
    db = SessionLocal()
    for spec in MANUAL_FOODS:
        existing = db.query(Food).filter(Food.name == spec["name"]).one_or_none()
        if existing is not None:
            print(f"skip (already exists): {spec['name']}")
            continue

        food = Food(name=spec["name"], protein_g_per_100g=0.0, amino_acids=dict(NULL_AMINO_ACIDS))
        db.add(food)
        db.flush()
        for nutrient_key, amount in spec["nutrients"].items():
            db.add(FoodNutrient(food_id=food.id, nutrient_key=nutrient_key, amount_per_100g=amount))
        print(f"inserted: {spec['name']} (id={food.id})")

    db.commit()


if __name__ == "__main__":
    main()
