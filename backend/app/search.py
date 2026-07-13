"""Filter foods or a user's recipes by nutrient thresholds and computed
protein-quality scores.

Filters are ANDed together. A filter's key is either a nutrients.NUTRIENTS
key (compared against per-100g for a food, per-serving for a recipe),
"protein_g_per_100g" (foods only — a recipe has no single protein-per-100g
figure), or one of the two computed scores "diaas_score" / "pdcaas_score"
(using the child_3y_adult reference pattern, same default the rest of the
app uses). A food/recipe that can't be scored (missing digestibility data)
simply doesn't match a score filter, rather than raising — search isn't
the place to surprise a caller with a 422 for an unrelated food.

Food search runs stored-nutrient filters as SQL (a subquery per nutrient
key, intersected via Food.id.in_()) so it scales to the full catalog;
score filters are evaluated in Python afterward since compute_diaas/
compute_pdcaas aren't SQL-expressible — fine because they only run against
whatever the SQL filters already narrowed down (or the whole catalog, in
the low-thousands, which is still cheap pure-Python arithmetic).

Recipe search skips the SQL step entirely and just evaluates every one of
the user's own recipes in Python — there are typically only a handful.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from .models import Food, FoodNutrient, Recipe, RecipeIngredient
from .nutrients import NUTRIENTS
from .reference_patterns import DEFAULT_PATTERN
from .scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas, compute_pdcaas

Op = Literal["gte", "lte", "eq"]

SCORE_KEYS = {"diaas_score", "pdcaas_score"}
FOOD_FILTER_KEYS = set(NUTRIENTS) | SCORE_KEYS | {"protein_g_per_100g"}
RECIPE_FILTER_KEYS = set(NUTRIENTS) | SCORE_KEYS


@dataclass
class NutrientFilter:
    key: str
    op: Op
    value: float


class UnknownFilterKey(ValueError):
    pass


def _compare(actual: float, op: Op, value: float) -> bool:
    if op == "gte":
        return actual >= value
    if op == "lte":
        return actual <= value
    return actual == value


def _score(amino_acids: dict, digestibility_diaas: dict | None, digestibility_pdcaas: float | None, score_key: str) -> float | None:
    try:
        if score_key == "diaas_score":
            if digestibility_diaas is None:
                return None
            return compute_diaas(amino_acids, digestibility_diaas, DEFAULT_PATTERN).score
        if score_key == "pdcaas_score":
            if digestibility_pdcaas is None:
                return None
            return compute_pdcaas(amino_acids, digestibility_pdcaas, DEFAULT_PATTERN).score
    except (IncompleteAminoAcidProfile, UnknownReferencePattern):
        return None
    return None


def search_foods(db: Session, filters: list[NutrientFilter], limit: int = 100) -> list[Food]:
    unknown = {f.key for f in filters} - FOOD_FILTER_KEYS
    if unknown:
        raise UnknownFilterKey(f"Unknown filter key(s): {sorted(unknown)}")

    query = db.query(Food)
    score_filters = []

    for f in filters:
        if f.key in SCORE_KEYS:
            score_filters.append(f)
        elif f.key == "protein_g_per_100g":
            query = query.filter(_op_clause(Food.protein_g_per_100g, f.op, f.value))
        else:
            subquery = db.query(FoodNutrient.food_id).filter(
                FoodNutrient.nutrient_key == f.key,
                _op_clause(FoodNutrient.amount_per_100g, f.op, f.value),
            )
            query = query.filter(Food.id.in_(subquery))

    candidates = query.order_by(Food.name).all()

    if not score_filters:
        return candidates[:limit]

    matches = [
        food
        for food in candidates
        if all(
            (score := _score(food.amino_acids, food.digestibility_diaas, food.digestibility_pdcaas, f.key))
            is not None
            and _compare(score, f.op, f.value)
            for f in score_filters
        )
    ]
    return matches[:limit]


def search_recipes(db: Session, user_id: int, filters: list[NutrientFilter]) -> list[Recipe]:
    unknown = {f.key for f in filters} - RECIPE_FILTER_KEYS
    if unknown:
        raise UnknownFilterKey(f"Unknown filter key(s): {sorted(unknown)}")

    recipes = db.query(Recipe).filter(Recipe.user_id == user_id).order_by(Recipe.name).all()
    matches = []

    for recipe in recipes:
        ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
        if not ingredients:
            continue
        food_ids = [i.food_id for i in ingredients]
        foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
        items = [WeightedFood(foods_by_id[i.food_id], i.quantity_g) for i in ingredients]

        nutrient_rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(food_ids)).all()
        by_food_id: dict[int, list[FoodNutrient]] = {}
        for row in nutrient_rows:
            by_food_id.setdefault(row.food_id, []).append(row)
        per_serving = aggregate_nutrients(items, by_food_id, divide_by=recipe.servings)
        aa_aggregate = aggregate_amino_acids(items)

        if _recipe_matches(per_serving, aa_aggregate, filters):
            matches.append(recipe)

    return matches


def _recipe_matches(per_serving: dict[str, float], aa_aggregate, filters: list[NutrientFilter]) -> bool:
    for f in filters:
        if f.key in SCORE_KEYS:
            score = _score(
                aa_aggregate.amino_acids, aa_aggregate.digestibility_diaas, aa_aggregate.digestibility_pdcaas, f.key
            )
            if score is None or not _compare(score, f.op, f.value):
                return False
        else:
            actual = per_serving.get(f.key)
            if actual is None or not _compare(actual, f.op, f.value):
                return False
    return True


def _op_clause(column, op: Op, value: float):
    if op == "gte":
        return column >= value
    if op == "lte":
        return column <= value
    return column == value
