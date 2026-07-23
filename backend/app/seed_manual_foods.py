"""Seed a handful of foods that ingest_fdc.py can never carry.

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

COMPOSITE_FOODS (prompt section 7) is a different kind of manual entry: a
food built by weighting together *other, real* Food rows already in this
database, rather than typed-in macro figures. "Generic muesli" is the
motivating case — there's no single FDC entry for it, and the alias table
used to stand in with homemade granola (a different, if adjacent, cereal —
see ingredient_aliases.py's history), a coarser approximation than
necessary once you accept that muesli is, itself, just rolled oats + dried
fruit + nuts + seeds in roughly known proportions. Reusing this app's own
aggregate_nutrients/aggregate_amino_acids (the same functions a recipe's
own ingredients are combined through) to build the composite means its
amino acid profile is a real, protein-weighted blend of real ingredient
data, not a fabricated approximation, and it stays reproducible: rerun this
script after a fresh FDC ingest and it's recomputed from whatever the
component foods' current data says, not implicitly stale.

Usage:
    python -m app.seed_manual_foods
"""

from dataclasses import dataclass

from sqlalchemy import case
from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
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


@dataclass
class CompositeComponent:
    # a few space-separated words, ANDed against Food.name (see
    # _find_component) — the same style ingredient_aliases.py's
    # ALIASES search phrases use, not a USDA-punctuated exact name.
    search_phrase: str
    mass_fraction: float  # of the composite's total 100g basis; must sum to 1.0 across a composite's components


@dataclass
class CompositeFoodSpec:
    name: str
    components: list[CompositeComponent]
    rationale: str  # the human-readable "why these proportions" note, echoed in ingredient_aliases.py's alias entry


COMPOSITE_FOODS: list[CompositeFoodSpec] = [
    CompositeFoodSpec(
        name="Muesli, generic composite (Nutri-Matic estimate)",
        components=[
            CompositeComponent("oats", 0.50),
            CompositeComponent("raisins seedless", 0.20),
            CompositeComponent("nuts mixed", 0.20),
            CompositeComponent("seeds sunflower", 0.10),
        ],
        rationale=(
            "A generic muesli is approximated here as 50% rolled oats, 20% dried fruit "
            "(raisins), 20% mixed nuts, and 10% seeds (sunflower) by mass — a typical "
            "generic composition, not any specific product's actual recipe. Nutrients "
            "and amino acids are computed by weighting each component's own database "
            "entry by that mass fraction, through this app's own aggregate_nutrients/ "
            "aggregate_amino_acids — the same math a recipe's ingredients are combined "
            "through elsewhere, not independently fabricated figures."
        ),
    ),
]


def _find_component(db: Session, search_phrase: str) -> Food | None:
    """Same shape as stock_recipes/food_matching.py's _word_and_search
    (every word of `search_phrase` must appear in Food.name; prefer a
    non-branded entry, then one with a complete amino acid profile, then
    the shortest/most generic name) — reimplemented locally in a few lines
    rather than importing that module's private helper, since this is a
    one-off admin script, not part of the live matching pipeline."""
    words = search_phrase.split()
    query = db.query(Food)
    for word in words:
        query = query.filter(Food.name.ilike(f"%{word}%"))
    branded_last = case((Food.data_type == "branded_food", 1), else_=0)
    candidates = query.order_by(branded_last, Food.name).limit(50).all()
    if not candidates:
        return None

    def lacks_amino_acids(food: Food) -> bool:
        return any(food.amino_acids.get(aa) is None for aa in AMINO_ACIDS)

    candidates.sort(key=lambda f: (f.data_type == "branded_food", lacks_amino_acids(f), len(f.name)))
    return candidates[0]


def _build_composite(db: Session, spec: CompositeFoodSpec) -> tuple[Food, list[FoodNutrient]] | None:
    resolved: list[tuple[CompositeComponent, Food]] = []
    for component in spec.components:
        food = _find_component(db, component.search_phrase)
        if food is None:
            print(f"skip composite {spec.name!r}: no component found for {component.search_phrase!r}")
            return None
        resolved.append((component, food))

    items = [WeightedFood(food, component.mass_fraction * 100) for component, food in resolved]
    aggregate = aggregate_amino_acids(items)

    food_ids = [food.id for _, food in resolved]
    nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
    for fn in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(food_ids)).all():
        nutrients_by_food_id.setdefault(fn.food_id, []).append(fn)
    totals = aggregate_nutrients(items, nutrients_by_food_id, divide_by=1.0)

    food = Food(
        name=spec.name,
        protein_g_per_100g=aggregate.total_protein_g,
        amino_acids=aggregate.amino_acids,
        digestibility_diaas=aggregate.digestibility_diaas,
        digestibility_diaas_source=aggregate.digestibility_diaas_source,
        digestibility_pdcaas=aggregate.digestibility_pdcaas,
        digestibility_pdcaas_source=aggregate.digestibility_pdcaas_source,
    )
    nutrients = [FoodNutrient(nutrient_key=key, amount_per_100g=amount) for key, amount in totals.items()]
    return food, nutrients


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

    for spec in COMPOSITE_FOODS:
        existing = db.query(Food).filter(Food.name == spec.name).one_or_none()
        if existing is not None:
            print(f"skip (already exists): {spec.name}")
            continue

        built = _build_composite(db, spec)
        if built is None:
            continue
        food, nutrients = built
        db.add(food)
        db.flush()
        for fn in nutrients:
            fn.food_id = food.id
            db.add(fn)
        print(f"inserted composite: {spec.name} (id={food.id})")

    db.commit()


if __name__ == "__main__":
    main()
