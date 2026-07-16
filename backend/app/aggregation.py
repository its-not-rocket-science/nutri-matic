"""Combines a weighted list of (Food, quantity_g) into a single nutrient
profile — shared by the recipe builder (ingredients -> per-serving) and the
diary (a day's logged entries -> daily total).

Amino acid / digestibility combination follows FAO's approach for mixed
protein sources: each ingredient's contribution is weighted by the *protein*
it contributes (not its mass), since DIAAS/PDCAAS are inherently
per-gram-protein measures. If any protein-contributing ingredient is
missing an amino acid or digestibility value, the mixture's value for that
amino acid is left null rather than silently understating it — the
existing compute_diaas/compute_pdcaas machinery already refuses to score
an incomplete profile, and that's the right behavior here too: a wrong
DIAAS number is worse than an honest "can't be scored."

Vitamin/mineral/fibre/fat totals are handled differently and more
permissively: a missing FoodNutrient row for an ingredient just
contributes zero for that nutrient, rather than making the whole mixture
"unscorable." Diet-level totals are inherently an approximation (matches
how any food diary app works) — unlike DIAAS, there's no single "wrong
number" risk from a partial sum, so failing loud here would just make the
feature unusable for the very common case of one ingredient lacking full
micronutrient data.
"""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from .data_quality import is_implausible
from .models import Food, FoodNutrient, Recipe, RecipeIngredient
from .reference_patterns import AMINO_ACIDS


@dataclass
class WeightedFood:
    food: Food
    quantity_g: float


def scale_recipe_ingredients(
    ingredients: list[RecipeIngredient],
    recipe_servings: float,
    servings_eaten: float,
    foods_by_id: dict[int, Food],
) -> list[WeightedFood]:
    """Expands 'N servings of a recipe' into its scaled ingredient
    quantities, so a diary entry logged as servings can be folded into the
    same per-gram aggregation as directly-logged foods."""
    scale = servings_eaten / recipe_servings
    return [WeightedFood(foods_by_id[ing.food_id], ing.quantity_g * scale) for ing in ingredients]


class QuantifiedEntry(Protocol):
    """Anything shaped like a DiaryEntry/MealPlanEntry — exactly one of
    (food_id, quantity_g) or (recipe_id, quantity_servings) set."""

    food_id: int | None
    quantity_g: float | None
    recipe_id: int | None
    quantity_servings: float | None


def expand_entries_to_weighted_foods(
    entries: list[QuantifiedEntry],
    foods_by_id: dict[int, Food],
    recipes_by_id: dict[int, Recipe],
    db: Session,
) -> list[WeightedFood]:
    """A food entry becomes one WeightedFood; a recipe entry expands into
    its ingredients, each scaled by quantity_servings / recipe.servings.
    Shared by the diary and meal plan, whose entries have the same shape
    but different lifecycles (actual vs. planned) — this is the part
    that's identical between them.

    foods_by_id is mutated in place with any recipe-ingredient foods not
    already present, so callers that need the full food set afterward
    (e.g. to look up FoodNutrient rows) see it reflected there too.
    """
    items: list[WeightedFood] = []
    recipe_ingredient_cache: dict[int, list[RecipeIngredient]] = {}

    for entry in entries:
        if entry.food_id is not None:
            items.append(WeightedFood(foods_by_id[entry.food_id], entry.quantity_g))
        else:
            recipe = recipes_by_id[entry.recipe_id]
            if recipe.id not in recipe_ingredient_cache:
                recipe_ingredient_cache[recipe.id] = (
                    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
                )
            ingredients = recipe_ingredient_cache[recipe.id]
            missing_ids = {i.food_id for i in ingredients} - foods_by_id.keys()
            if missing_ids:
                for food in db.query(Food).filter(Food.id.in_(missing_ids)).all():
                    foods_by_id[food.id] = food
            items.extend(
                scale_recipe_ingredients(ingredients, recipe.servings, entry.quantity_servings, foods_by_id)
            )

    return items


def aggregate_food_grams(items: list[WeightedFood]) -> dict[int, float]:
    """Sums quantity_g per food_id across items — the shopping-list shape
    (how much of each actual food is needed), as opposed to
    aggregate_nutrients' per-nutrient totals."""
    totals: dict[int, float] = {}
    for item in items:
        totals[item.food.id] = totals.get(item.food.id, 0.0) + item.quantity_g
    return totals


@dataclass
class AminoAcidAggregate:
    amino_acids: dict[str, float | None]
    digestibility_diaas: dict[str, float | None] | None
    digestibility_pdcaas: float | None
    total_protein_g: float
    # weakest-link confidence tag across every protein-contributing
    # ingredient: "measured" only if every one of them had food-specific
    # (not category-fallback) digestibility data for this method; None if
    # no ingredient contributed digestibility data for it at all. This is
    # what lets a recipe/diary score report real provenance instead of the
    # blend just going unlabelled.
    digestibility_diaas_source: str | None = None
    digestibility_pdcaas_source: str | None = None


def aggregate_amino_acids(items: list[WeightedFood]) -> AminoAcidAggregate:
    total_protein = 0.0
    aa_numerators = dict.fromkeys(AMINO_ACIDS, 0.0)
    diaas_numerators = dict.fromkeys(AMINO_ACIDS, 0.0)
    aa_complete = dict.fromkeys(AMINO_ACIDS, True)
    diaas_complete = dict.fromkeys(AMINO_ACIDS, True)
    pdcaas_numerator = 0.0
    pdcaas_complete = True

    any_diaas_contributor = False
    diaas_all_measured = True
    any_pdcaas_contributor = False
    pdcaas_all_measured = True

    for item in items:
        protein_g = item.food.protein_g_per_100g * item.quantity_g / 100
        if protein_g <= 0:
            continue
        total_protein += protein_g

        for aa in AMINO_ACIDS:
            aa_value = item.food.amino_acids.get(aa)
            if aa_value is None:
                aa_complete[aa] = False
                diaas_complete[aa] = False
                continue
            aa_mg = aa_value * protein_g
            aa_numerators[aa] += aa_mg

            if item.food.digestibility_diaas is None:
                diaas_complete[aa] = False
                continue
            diaas_coefficient = item.food.digestibility_diaas.get(aa)
            if diaas_coefficient is None:
                diaas_complete[aa] = False
                continue
            diaas_numerators[aa] += aa_mg * diaas_coefficient

        if item.food.digestibility_diaas is not None:
            any_diaas_contributor = True
            if item.food.digestibility_diaas_source != "measured":
                diaas_all_measured = False

        if item.food.digestibility_pdcaas is None:
            pdcaas_complete = False
        else:
            pdcaas_numerator += protein_g * item.food.digestibility_pdcaas
            any_pdcaas_contributor = True
            if item.food.digestibility_pdcaas_source != "measured":
                pdcaas_all_measured = False

    if total_protein <= 0:
        return AminoAcidAggregate(
            amino_acids=dict.fromkeys(AMINO_ACIDS),
            digestibility_diaas=None,
            digestibility_pdcaas=None,
            total_protein_g=0.0,
        )

    amino_acids = {
        aa: (aa_numerators[aa] / total_protein) if aa_complete[aa] else None for aa in AMINO_ACIDS
    }
    digestibility_diaas = {
        aa: (diaas_numerators[aa] / aa_numerators[aa]) if diaas_complete[aa] and aa_numerators[aa] > 0 else None
        for aa in AMINO_ACIDS
    }
    digestibility_pdcaas = (pdcaas_numerator / total_protein) if pdcaas_complete else None

    return AminoAcidAggregate(
        amino_acids=amino_acids,
        digestibility_diaas=digestibility_diaas,
        digestibility_pdcaas=digestibility_pdcaas,
        total_protein_g=total_protein,
        digestibility_diaas_source=(
            ("measured" if diaas_all_measured else "estimated") if any_diaas_contributor else None
        ),
        digestibility_pdcaas_source=(
            ("measured" if pdcaas_all_measured else "estimated") if any_pdcaas_contributor else None
        ),
    )


def aggregate_nutrients(
    items: list[WeightedFood], food_nutrients_by_food_id: dict[int, list[FoodNutrient]], divide_by: float = 1.0
) -> dict[str, float]:
    """Sums amount_per_100g * quantity_g / 100 across items for each
    nutrient key, then divides by `divide_by` (servings, for a recipe;
    1 for a diary day's raw total).

    Skips any FoodNutrient row flagged by data_quality.is_implausible —
    a source data error (see data_quality.py) would otherwise blow out
    the whole day's/recipe's total for that nutrient. The raw value is
    still visible on the food's own provenance page; it's just not
    trustworthy as an input to a sum."""
    totals: dict[str, float] = {}
    for item in items:
        for fn in food_nutrients_by_food_id.get(item.food.id, []):
            if is_implausible(fn.nutrient_key, fn.amount_per_100g):
                continue
            contribution = fn.amount_per_100g * item.quantity_g / 100
            totals[fn.nutrient_key] = totals.get(fn.nutrient_key, 0.0) + contribution
    if divide_by and divide_by != 1.0:
        totals = {k: v / divide_by for k, v in totals.items()}
    return totals
