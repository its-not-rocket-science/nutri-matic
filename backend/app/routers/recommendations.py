"""Nutrient-gap recommendation endpoints — prompt 6 (and, as later prompts
land, 7/8/9) of the feature described in
docs/nutrient-gap-recommendations.md.

Reuses the same entry-loading pattern every existing diary/meal-plan
endpoint already uses (`expand_entries_to_weighted_foods`) rather than
inventing a new way to turn a day's/meal's logged entries into a nutrient
total — see routers/diary.py's `_compute_nutrient_gaps` for the precedent
this mirrors.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import expand_entries_to_weighted_foods
from ..auth import get_current_user, get_owned_profile
from ..database import get_db
from ..models import DiaryEntry, Food, FoodNutrient, MealPlanEntry, Profile, Recipe, User
from ..nutrient_targets import AnalysisPeriod
from ..recommend_ingredients import DEFAULT_MAX_SUGGESTIONS, suggest_ingredients
from ..recommend_recipes import DEFAULT_MAX_SUGGESTIONS as DEFAULT_MAX_RECIPE_SUGGESTIONS
from ..recommend_recipes import GOAL_PRESETS, suggest_recipes

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])

_MEALS = ("breakfast", "lunch", "dinner", "snack")


def _load_entries(db: Session, profile: Profile, entry_date: date, source: str) -> list:
    if source == "meal_plan":
        return (
            db.query(MealPlanEntry)
            .filter(MealPlanEntry.profile_id == profile.id, MealPlanEntry.plan_date == entry_date)
            .all()
        )
    return (
        db.query(DiaryEntry)
        .filter(DiaryEntry.profile_id == profile.id, DiaryEntry.entry_date == entry_date)
        .all()
    )


@router.get("/ingredients", response_model=schemas.IngredientSuggestionsOut)
def get_ingredient_suggestions(
    entry_date: date,
    meal: str | None = None,
    source: str = "diary",
    max_additional_energy: float | None = None,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
    priority_nutrients: str | None = None,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Suggests up to `max_suggestions` additional foods to close the
    biggest current nutrient gaps for one meal, diary day, or meal-plan
    day. `source="diary"` (default) reads logged `DiaryEntry` rows;
    `source="meal_plan"` reads planned `MealPlanEntry` rows for the same
    date — same analysis, different entry source, exactly like every
    other endpoint that already supports both (see meal_plan.py).
    `meal`, when given, scopes to just that meal (still compared against
    the day's target — see nutrient_targets.resolve_meal_comparison_target
    for why a meal is never automatically one-third of the day).
    `priority_nutrients` is a comma-separated list of nutrient keys
    (e.g. `iron,folate`) to prioritise; omit to consider every
    optimisation-eligible nutrient currently short.

    Returns an empty `suggestions` list — never an error — when nothing
    logged has any gap to close, or no safe/useful candidate exists.
    """
    if source not in ("diary", "meal_plan"):
        raise HTTPException(status_code=422, detail="source must be 'diary' or 'meal_plan'")
    if meal is not None and meal not in _MEALS:
        raise HTTPException(status_code=422, detail=f"meal must be one of {_MEALS}")

    entries = _load_entries(db, profile, entry_date, source)
    period = AnalysisPeriod.DAY
    if meal is not None:
        entries = [e for e in entries if e.meal == meal]
        period = AnalysisPeriod.MEAL

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
    items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)

    all_food_ids = [item.food.id for item in items]
    nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
        nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    priority_keys = set(priority_nutrients.split(",")) if priority_nutrients else None

    result = suggest_ingredients(
        db, profile, items, nutrients_by_food_id, period,
        max_additional_energy=max_additional_energy, max_suggestions=max_suggestions,
        priority_nutrient_keys=priority_keys, meal_type=meal,
    )

    return schemas.IngredientSuggestionsOut(suggestions=[
        schemas.IngredientSuggestionOut(
            food_id=s.food_id, food_name=s.food_name, quantity_g=s.quantity_g, candidate_kind=s.candidate_kind,
            score=s.score.total, nutrients_improved=s.nutrients_improved, remaining_shortfalls=s.remaining_shortfalls,
            new_warnings=s.new_warnings, extra_energy_kcal=s.extra_energy_kcal, data_coverage=s.data_coverage,
            explanation=s.explanation,
        )
        for s in result.suggestions
    ])


@router.get("/recipes", response_model=schemas.RecipeSuggestionsOut)
def get_recipe_suggestions(
    entry_date: date,
    source: str = "diary",
    max_additional_energy: float | None = None,
    max_suggestions: int = DEFAULT_MAX_RECIPE_SUGGESTIONS,
    priority_nutrients: str | None = None,
    goal: str | None = None,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Suggests up to `max_suggestions` recipes (the user's own, shared
    with them, or public) to close the biggest current nutrient gaps for
    a diary day or meal-plan day. `goal` is one of
    `recommend_recipes.GOAL_PRESETS`
    (`overall_balance`/`protein_quality`/`fibre`/`iron_folate`/`calcium`);
    an explicit `priority_nutrients` overrides it. Returns an empty
    `suggestions` list — never an error — when nothing logged has a gap,
    or no visible recipe helps."""
    if source not in ("diary", "meal_plan"):
        raise HTTPException(status_code=422, detail="source must be 'diary' or 'meal_plan'")
    if goal is not None and goal not in GOAL_PRESETS:
        raise HTTPException(status_code=422, detail=f"goal must be one of {sorted(GOAL_PRESETS)}")

    entries = _load_entries(db, profile, entry_date, source)

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
    items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)

    all_food_ids = [item.food.id for item in items]
    nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
        nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    priority_keys = set(priority_nutrients.split(",")) if priority_nutrients else None

    result = suggest_recipes(
        db, profile, current_user, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        max_additional_energy=max_additional_energy, max_suggestions=max_suggestions,
        priority_nutrient_keys=priority_keys, goal=goal,
        excluded_recipe_ids=recipe_ids,
    )

    return schemas.RecipeSuggestionsOut(suggestions=[
        schemas.RecipeSuggestionOut(
            recipe_id=s.recipe_id, recipe_name=s.recipe_name, suggested_servings=s.suggested_servings,
            energy_added_kcal=s.energy_added_kcal, protein_added_g=s.protein_added_g, score=s.score.total,
            nutrients_improved=s.nutrients_improved, remaining_shortfalls=s.remaining_shortfalls,
            new_warnings=s.new_warnings, is_stock=s.is_stock, source_name=s.source_name,
            match_coverage_lines=s.match_coverage_lines, robustness_rating=s.robustness_rating,
            robustness_note=s.robustness_note, explanation=s.explanation,
        )
        for s in result.suggestions
    ])
