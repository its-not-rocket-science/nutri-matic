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
from ..recommend_substitutions import DEFAULT_MAX_SUGGESTIONS as DEFAULT_MAX_SUBSTITUTION_SUGGESTIONS
from ..recommend_substitutions import suggest_substitutions
from ..recommend_pairs import DEFAULT_MAX_SUGGESTIONS as DEFAULT_MAX_PAIR_SUGGESTIONS
from ..recommend_pairs import suggest_pairs

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


@router.get("/substitutions", response_model=schemas.SubstitutionSuggestionsOut)
def get_substitution_suggestions(
    entry_id: int,
    source: str = "diary",
    max_suggestions: int = DEFAULT_MAX_SUBSTITUTION_SUGGESTIONS,
    priority_nutrients: str | None = None,
    energy_tolerance_kcal: float = 150.0,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Proposes recipes to replace an already-logged `entry_id` (a
    `DiaryEntry` or `MealPlanEntry` that has a `recipe_id` — a plain food
    entry can't be "substituted" in this sense, only removed/re-added
    directly). Never modifies the entry itself: applying a suggestion is
    the caller's job, via the existing delete-then-recreate endpoints
    (see recommend_substitutions.py's module docstring)."""
    if source not in ("diary", "meal_plan"):
        raise HTTPException(status_code=422, detail="source must be 'diary' or 'meal_plan'")

    model = MealPlanEntry if source == "meal_plan" else DiaryEntry
    entry = db.query(model).filter(model.id == entry_id, model.profile_id == profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.recipe_id is None:
        raise HTTPException(status_code=422, detail="Entry has no recipe to substitute — it's a plain food entry")

    current_recipe = db.get(Recipe, entry.recipe_id)
    if current_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    entry_date = entry.plan_date if source == "meal_plan" else entry.entry_date
    all_entries = _load_entries(db, profile, entry_date, source)
    other_entries = [e for e in all_entries if e.id != entry.id]

    food_ids = {e.food_id for e in other_entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in other_entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
    other_items = expand_entries_to_weighted_foods(other_entries, foods_by_id, recipes_by_id, db)

    all_food_ids = [item.food.id for item in other_items]
    nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
        nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    priority_keys = set(priority_nutrients.split(",")) if priority_nutrients else None

    result = suggest_substitutions(
        db, profile, current_user, other_items, current_recipe, entry.quantity_servings, nutrients_by_food_id,
        AnalysisPeriod.DAY, max_suggestions=max_suggestions, priority_nutrient_keys=priority_keys,
        energy_tolerance_kcal=energy_tolerance_kcal,
    )

    return schemas.SubstitutionSuggestionsOut(
        current_recipe_id=result.current_recipe_id, current_recipe_name=result.current_recipe_name,
        suggestions=[
            schemas.SubstitutionSuggestionOut(
                current_recipe_id=s.current_recipe_id, current_recipe_name=s.current_recipe_name,
                current_servings=s.current_servings, replacement_recipe_id=s.replacement_recipe_id,
                replacement_recipe_name=s.replacement_recipe_name, replacement_servings=s.replacement_servings,
                energy_difference_kcal=s.energy_difference_kcal, protein_difference_g=s.protein_difference_g,
                fiber_difference_g=s.fiber_difference_g, saturated_fat_difference_g=s.saturated_fat_difference_g,
                sodium_difference_mg=s.sodium_difference_mg, key_nutrient_differences=s.key_nutrient_differences,
                protein_quality_before=s.protein_quality_before, protein_quality_after=s.protein_quality_after,
                score=s.score.total, remaining_shortfalls=s.remaining_shortfalls, new_warnings=s.new_warnings,
                is_stock=s.is_stock, match_coverage_lines=s.match_coverage_lines,
                robustness_rating=s.robustness_rating, provenance_note=s.provenance_note, explanation=s.explanation,
            )
            for s in result.suggestions
        ],
    )


@router.get("/pairs", response_model=schemas.PairSuggestionsOut)
def get_pair_suggestions(
    entry_date: date,
    source: str = "diary",
    max_additional_energy: float | None = None,
    max_suggestions: int = DEFAULT_MAX_PAIR_SUGGESTIONS,
    priority_nutrients: str | None = None,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Optional two-item combination mode (prompt 9) — e.g. yoghurt +
    berries, wholemeal toast + peanut butter. Only ever forms a pair
    `candidate_metadata.py`'s practical metadata or `recommend_pairs.
    CURATED_PAIRS` actually supports; scores the pair's real *combined*
    effect, not the sum of each food's own score. Bounded search
    (`recommend_pairs.MAX_PAIR_EVALUATIONS`) regardless of catalog size."""
    if source not in ("diary", "meal_plan"):
        raise HTTPException(status_code=422, detail="source must be 'diary' or 'meal_plan'")

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

    result = suggest_pairs(
        db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        max_additional_energy=max_additional_energy, max_suggestions=max_suggestions,
        priority_nutrient_keys=priority_keys,
    )

    return schemas.PairSuggestionsOut(suggestions=[
        schemas.PairSuggestionOut(
            first=schemas.PairContributionOut(
                food_id=s.first.food_id, food_name=s.first.food_name, quantity_g=s.first.quantity_g,
                solo_score=s.first.solo_score,
            ),
            second=schemas.PairContributionOut(
                food_id=s.second.food_id, food_name=s.second.food_name, quantity_g=s.second.quantity_g,
                solo_score=s.second.solo_score,
            ),
            combined_energy_kcal=s.combined_energy_kcal, score=s.score.total,
            nutrients_improved=s.nutrients_improved, remaining_shortfalls=s.remaining_shortfalls,
            new_warnings=s.new_warnings, explanation=s.explanation,
        )
        for s in result.suggestions
    ])
