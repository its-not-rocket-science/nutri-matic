from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user, get_owned_profile
from ..candidate_metadata import resolve_candidate_metadata
from ..database import get_db
from ..dietary_filter import Suitability, foods_dietary_status, recipes_dietary_status
from ..models import Profile, User
from ..nutrients import NUTRIENTS
from ..search import FOOD_FILTER_KEYS, RECIPE_FILTER_KEYS
from .diary import _rank_foods_by_nutrient, _rank_recipes_by_nutrient

router = APIRouter(prefix="/api/search", tags=["search"])

# how far to over-fetch _rank_foods_by_nutrient's raw candidates before
# the practicality filter below (Hardening Prompt 4's suitable_for_direct_
# suggestion check, applied here the same way recommend_ingredients.
# _candidate_pool applies it) — a single larger window, not that module's
# paginated refill, since this is a lower-stakes browse feature where an
# honestly-short list beats the extra query cost of guaranteeing `limit`
# results exist.
_FOOD_OVERFETCH_MULTIPLIER = 8

_SCORE_LABELS = {"diaas_score": ("DIAAS score", "%"), "pdcaas_score": ("PDCAAS score", "%")}
_SPECIAL_LABELS = {"protein_g_per_100g": ("Protein", "g")}


def _key_out(key: str) -> schemas.FilterKeyOut:
    if key in _SCORE_LABELS:
        label, unit = _SCORE_LABELS[key]
    elif key in _SPECIAL_LABELS:
        label, unit = _SPECIAL_LABELS[key]
    else:
        label, unit = NUTRIENTS[key].name, NUTRIENTS[key].unit
    return schemas.FilterKeyOut(key=key, label=label, unit=unit)


@router.get("/keys", response_model=dict[str, list[schemas.FilterKeyOut]])
def filter_keys():
    """Available filter keys for /api/foods/search and /api/recipes/search,
    with display labels/units — keeps the frontend from hand-maintaining a
    duplicate list of every nutrient."""
    return {
        "food": sorted((_key_out(k) for k in FOOD_FILTER_KEYS), key=lambda k: k.label),
        "recipe": sorted((_key_out(k) for k in RECIPE_FILTER_KEYS), key=lambda k: k.label),
    }


def _status_out(suitability: Suitability | None) -> schemas.DietaryStatusOut | None:
    if suitability is None:
        return None
    return schemas.DietaryStatusOut(
        status=suitability.status, confidence=suitability.confidence, reasons=suitability.reasons
    )


@router.get("/nutrient-sources", response_model=schemas.NutrientSourcesOut)
def nutrient_sources(
    nutrient_key: str,
    limit: int = Query(10, ge=1, le=25),
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Prompt 6.1: ranked best sources of one nutrient, across both
    ingredients and recipes — reuses diary.py's existing
    _rank_foods_by_nutrient/_rank_recipes_by_nutrient (the same candidate
    ranking gap-suggestions/meal-optimize/plan-optimize already draw from)
    rather than a new ranking implementation. Both already apply
    data-quality (is_implausible) and dietary-constraint filtering for this
    profile; on top of that, food results here also apply Hardening Prompt
    4's practicality filter (branded-product exclusion and
    candidate_metadata.suitable_for_direct_suggestion) — the same one
    recommend_ingredients._candidate_pool applies — so a first-class browse
    feature doesn't resurface "best source of iron" results dominated by
    implausible branded records or things nobody eats standalone (a
    tablespoon of baking powder). Recipes don't need this second pass:
    a recipe is inherently a "whole dish", not a bare raw ingredient, so
    the practicality concern _candidate_pool exists for doesn't apply.

    Foods (per 100g) and recipes (per 1 serving) are returned as two
    separately-ranked lists, not merged into one sorted-by-amount list —
    those two numbers aren't the same basis (a recipe's serving could be
    2kg or 20g), so combining them would let serving size alone move a
    recipe above a genuinely more nutrient-dense food.

    filter_excluded_foods/filter_excluded_recipes (used inside the two
    ranking functions above) only ever drop a hard exclusion — an "avoid"-
    severity constraint is deliberately retained, same distinction
    dietary_filter.py's module docstring describes. Existing food/recipe
    search already surfaces that retained-but-flagged state via
    dietary_status; this reuses the same foods_dietary_status/
    recipes_dietary_status so a best-source result never renders
    indistinguishably from a fully unconstrained one."""
    if nutrient_key not in NUTRIENTS:
        raise HTTPException(status_code=422, detail=f"Unknown nutrient key: {nutrient_key}")
    unit = NUTRIENTS[nutrient_key].unit

    raw_foods = _rank_foods_by_nutrient(db, nutrient_key, limit * _FOOD_OVERFETCH_MULTIPLIER, profile)
    eligible_foods: list[tuple] = []
    for food, amount in raw_foods:
        if food.data_type == "branded_food":
            continue
        if not resolve_candidate_metadata(food).suitable_for_direct_suggestion:
            continue
        eligible_foods.append((food, amount))
        if len(eligible_foods) >= limit:
            break

    food_status_by_id = foods_dietary_status([f for f, _amount in eligible_foods], db, profile)
    food_sources = [
        schemas.NutrientSourceOut(
            kind="food", food_id=food.id, recipe_id=None, name=food.name, amount=amount, unit=unit, per="100g",
            dietary_status=_status_out(food_status_by_id.get(food.id)),
        )
        for food, amount in eligible_foods
    ]

    ranked_recipes = _rank_recipes_by_nutrient(db, nutrient_key, limit, current_user, profile)
    recipe_status_by_id = recipes_dietary_status([r for r, _items, _amount in ranked_recipes], db, profile)
    recipe_sources = [
        schemas.NutrientSourceOut(
            kind="recipe", food_id=None, recipe_id=recipe.id, name=recipe.name, amount=amount, unit=unit,
            per="serving", dietary_status=_status_out(recipe_status_by_id.get(recipe.id)),
        )
        for recipe, _items, amount in ranked_recipes
    ]

    return schemas.NutrientSourcesOut(foods=food_sources, recipes=recipe_sources)
