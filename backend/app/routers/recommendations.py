"""Nutrient-gap recommendation endpoints — prompt 6 (and, as later prompts
land, 7/8/9) of the feature described in
docs/nutrient-gap-recommendations.md.

Reuses the same entry-loading pattern every existing diary/meal-plan
endpoint already uses (`expand_entries_to_weighted_foods`) rather than
inventing a new way to turn a day's/meal's logged entries into a nutrient
total — see routers/diary.py's `_compute_nutrient_gaps` for the precedent
this mirrors.
"""

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import aggregate_nutrients, expand_entries_to_weighted_foods, scale_recipe_ingredients
from ..auth import get_current_user, get_owned_profile
from ..database import get_db
from ..dietary_filter import filter_excluded_recipes
from ..models import DiaryEntry, Food, FoodNutrient, MealPlanEntry, Profile, Recipe, RecipeIngredient, User
from ..nutrient_targets import AnalysisPeriod
from ..recipe_access import get_visible_recipe
from ..recommendation_params import parse_priority_nutrients, validate_date_range
from ..recommendation_safety import assess_eligibility, recipe_warnings
from ..recommend_ingredients import DEFAULT_MAX_SUGGESTIONS, suggest_ingredients
from ..recommend_recipes import DEFAULT_MAX_SUGGESTIONS as DEFAULT_MAX_RECIPE_SUGGESTIONS
from ..recommend_recipes import GOAL_PRESETS, suggest_recipes
from ..recommend_substitutions import DEFAULT_MAX_SUGGESTIONS as DEFAULT_MAX_SUBSTITUTION_SUGGESTIONS
from ..recommend_substitutions import suggest_substitutions
from ..recommend_pairs import DEFAULT_MAX_SUGGESTIONS as DEFAULT_MAX_PAIR_SUGGESTIONS
from ..recommend_pairs import suggest_pairs
from ..recommendation_provenance import RecipeQualitySummary
from ..recommendation_scoring import ScoreBreakdown

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def _score_breakdown_out(score: ScoreBreakdown) -> schemas.ScoreBreakdownOut:
    """Shared conversion from the engine's internal `ScoreBreakdown`
    dataclass to the public `ScoreBreakdownOut` schema — hardening
    prompt 3. Deliberately excludes `nutrients_improved`/
    `nutrients_worsened` (already exposed as each suggestion's own
    top-level `nutrients_improved`/`new_warnings` fields) so the
    breakdown carries only the numeric terms, never a duplicate/internal
    object."""
    return schemas.ScoreBreakdownOut(
        weighted_gap_reduction=score.weighted_gap_reduction,
        multi_nutrient_bonus=score.multi_nutrient_bonus,
        protein_quality_benefit=score.protein_quality_benefit,
        dietary_fit=score.dietary_fit,
        practicality=score.practicality,
        upper_limit_penalty=score.upper_limit_penalty,
        above_preferred_penalty=score.above_preferred_penalty,
        energy_overshoot_penalty=score.energy_overshoot_penalty,
        uncertainty_penalty=score.uncertainty_penalty,
        implausible_serving_penalty=score.implausible_serving_penalty,
        total=score.total,
        model_version=score.model_version,
    )


def _quality_summary_out(summary: RecipeQualitySummary) -> schemas.RecipeQualitySummaryOut:
    """Shared conversion for `recommendation_provenance.RecipeQualitySummary`
    — hardening prompt 4."""
    return schemas.RecipeQualitySummaryOut(
        ingredient_count=summary.ingredient_count,
        unmapped_count=summary.unmapped_count,
        exact_or_regional_count=summary.exact_or_regional_count,
        analogue_count=summary.analogue_count,
        proxy_or_reviewed_count=summary.proxy_or_reviewed_count,
        fuzzy_unclassified_count=summary.fuzzy_unclassified_count,
        proportion_exact_or_regional=summary.proportion_exact_or_regional,
        proportion_analogue=summary.proportion_analogue,
        proportion_proxy_or_reviewed=summary.proportion_proxy_or_reviewed,
        min_mapping_confidence=summary.min_mapping_confidence,
        weighted_mapping_confidence=summary.weighted_mapping_confidence,
        fallback_resolution_count=summary.fallback_resolution_count,
        unresolved_or_low_confidence_count=summary.unresolved_or_low_confidence_count,
        nutrient_coverage=summary.nutrient_coverage,
    )


def _disabled_reason_code_out(eligibility) -> str | None:
    """Hardening prompt 5's structured reason code, as a plain string for
    the API schema."""
    return eligibility.disabled_reason_code.value if eligibility.disabled_reason_code else None

def _as_utc(dt: datetime) -> datetime:
    """`DiaryEntry.updated_at`/`MealPlanEntry.updated_at` are always set
    Python-side as timezone-aware UTC (see the models' own docstrings),
    but a client-supplied `expected_updated_at` could in principle arrive
    naive (no offset) — treat that as UTC too rather than letting Python
    raise on a naive-vs-aware comparison, which would surface as a 500
    instead of the intended 409."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


Source = Literal["diary", "meal_plan"]
MealParam = Literal["breakfast", "lunch", "dinner", "snack"]

# Hardening prompt 2's own worked suggestions, applied consistently across
# every endpoint below via FastAPI's Query(...) constraints — rejected
# before any database work runs (FastAPI/Pydantic validates path/query
# parameters before the endpoint body executes at all).
MIN_MAX_SUGGESTIONS = 1
MAX_MAX_SUGGESTIONS = 10
MAX_SERVINGS = 20.0
MAX_ADDITIONAL_ENERGY_CAP = 5000.0
MAX_ENERGY_TOLERANCE_CAP = 2000.0


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


def _load_entries_range(db: Session, profile: Profile, start_date: date, end_date: date, source: str) -> list:
    """Multi-day counterpart to `_load_entries` — same shape as
    `routers/meal_plan.py`'s `_entries_in_range`, generalised to diary too
    rather than duplicating a second query builder just for one source."""
    if source == "meal_plan":
        return (
            db.query(MealPlanEntry)
            .filter(
                MealPlanEntry.profile_id == profile.id,
                MealPlanEntry.plan_date >= start_date,
                MealPlanEntry.plan_date <= end_date,
            )
            .all()
        )
    return (
        db.query(DiaryEntry)
        .filter(
            DiaryEntry.profile_id == profile.id,
            DiaryEntry.entry_date >= start_date,
            DiaryEntry.entry_date <= end_date,
        )
        .all()
    )


def _recipe_as_items(db: Session, current_user: User, recipe_id: int, servings: float) -> tuple[Recipe, list]:
    """A recipe's own scaled ingredients, standing in for "the current
    meal" — lets the recipe-detail page ask "what could I add to this
    recipe" through the exact same suggest_ingredients used for a logged
    diary/meal-plan meal, without inventing a second candidate-generation
    path.

    Recipe access is a separate boundary from profile ownership —
    `get_visible_recipe` (owner, shared-with, or public/stock) is the
    same canonical check `routers/recipes.py` uses everywhere else, so a
    private recipe can't be inspected/analysed via recommendations just
    because its numeric id was guessed (hardening prompt 1). 404 for both
    "doesn't exist" and "exists but not yours" — never 403 — matching
    this app's existing anti-enumeration convention."""
    recipe = get_visible_recipe(recipe_id, current_user, db)
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).all()
    if not ingredients:
        return recipe, []
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_([i.food_id for i in ingredients])).all()}
    items = scale_recipe_ingredients(ingredients, recipe.servings, servings, foods_by_id)
    return recipe, items


@router.get("/ingredients", response_model=schemas.IngredientSuggestionsOut)
def get_ingredient_suggestions(
    entry_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    recipe_id: int | None = Query(default=None, gt=0),
    servings: float = Query(default=1.0, gt=0, le=MAX_SERVINGS),
    meal: MealParam | None = None,
    source: Source = "diary",
    max_additional_energy: float | None = Query(default=None, ge=0, le=MAX_ADDITIONAL_ENERGY_CAP),
    max_suggestions: int = Query(default=DEFAULT_MAX_SUGGESTIONS, ge=MIN_MAX_SUGGESTIONS, le=MAX_MAX_SUGGESTIONS),
    priority_nutrients: str | None = None,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Suggests up to `max_suggestions` additional foods to close the
    biggest current nutrient gaps for one meal, diary day, meal-plan day,
    multi-day meal-plan range, or a standalone recipe.

    Exactly one of these scopes must be given:
    - `entry_date` (+ optional `meal`): a diary/meal-plan day, or one meal
      within it, per `source`. `meal`, when given, compares against the
      day's target minus whatever the day's other meals already logged
      (see nutrient_targets.adjust_target_for_remaining) — never the flat
      whole-day target, and never an automatic one-third-of-the-day split.
    - `start_date`+`end_date`: a multi-day meal-plan range (`source` must
      be `meal_plan` — diary trends have their own dedicated page/analysis
      and aren't wired to this multi-day mode).
    - `recipe_id` (+ optional `servings`, default 1): a recipe's own
      ingredients stand in for "the current meal" — the recipe-detail
      page's "Improve this recipe", not tied to any diary/meal-plan entry.

    `source="diary"` (default) reads logged `DiaryEntry` rows;
    `source="meal_plan"` reads planned `MealPlanEntry` rows — same
    analysis, different entry source, exactly like every other endpoint
    that already supports both (see meal_plan.py). `priority_nutrients`
    is a comma-separated list of nutrient keys (e.g. `iron,folate`) to
    prioritise; omit to consider every optimisation-eligible nutrient
    currently short.

    Returns an empty `suggestions` list — never an error — when nothing
    logged has any gap to close, or no safe/useful candidate exists.
    """
    # --- basic shape/semantic validation first, no database work yet ---
    scopes_given = sum([recipe_id is not None, entry_date is not None, start_date is not None or end_date is not None])
    if scopes_given != 1:
        raise HTTPException(
            status_code=422, detail="give exactly one of entry_date, start_date+end_date, or recipe_id",
        )
    if recipe_id is not None and meal is not None:
        raise HTTPException(status_code=422, detail="meal is not compatible with recipe_id")
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise HTTPException(status_code=422, detail="start_date and end_date must both be given")
        if source != "meal_plan":
            raise HTTPException(status_code=422, detail="a multi-day range requires source='meal_plan'")
        if meal is not None:
            raise HTTPException(status_code=422, detail="meal is not compatible with a multi-day range")
        validate_date_range(start_date, end_date)
    priority_keys = parse_priority_nutrients(priority_nutrients)

    # --- only now does any database work start ---
    eligibility = assess_eligibility(profile, db)
    if not eligibility.enabled:
        return schemas.IngredientSuggestionsOut(
            suggestions=[], disabled_reason=eligibility.disabled_reason,
            disabled_reason_code=_disabled_reason_code_out(eligibility), warnings=[w.value for w in eligibility.warnings],
        )

    already_consumed_by_key: dict[str, float] | None = None

    if recipe_id is not None:
        _recipe, items = _recipe_as_items(db, current_user, recipe_id, servings)
        period = AnalysisPeriod.MEAL
        day_count = 1
        nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
        all_food_ids = [item.food.id for item in items]
        for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
            nutrients_by_food_id.setdefault(row.food_id, []).append(row)
    elif start_date is not None or end_date is not None:
        entries = _load_entries_range(db, profile, start_date, end_date, source)
        period = AnalysisPeriod.MULTI_DAY
        day_count = (end_date - start_date).days + 1

        food_ids = {e.food_id for e in entries if e.food_id is not None}
        recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
        foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
        recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
        items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)

        nutrients_by_food_id = {}
        all_food_ids = [item.food.id for item in items]
        for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
            nutrients_by_food_id.setdefault(row.food_id, []).append(row)
    else:
        all_day_entries = _load_entries(db, profile, entry_date, source)
        period = AnalysisPeriod.DAY
        day_count = 1
        entries = all_day_entries
        other_entries = []
        if meal is not None:
            entries = [e for e in all_day_entries if e.meal == meal]
            other_entries = [e for e in all_day_entries if e.meal != meal]
            period = AnalysisPeriod.MEAL

        food_ids = {e.food_id for e in all_day_entries if e.food_id is not None}
        recipe_ids = {e.recipe_id for e in all_day_entries if e.recipe_id is not None}
        foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
        recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
        items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)

        nutrients_by_food_id = {}
        all_food_ids = [item.food.id for item in items]
        for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
            nutrients_by_food_id.setdefault(row.food_id, []).append(row)

        if other_entries:
            other_items = expand_entries_to_weighted_foods(other_entries, foods_by_id, recipes_by_id, db)
            other_food_ids = [item.food.id for item in other_items]
            other_nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
            for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(other_food_ids)).all():
                other_nutrients_by_food_id.setdefault(row.food_id, []).append(row)
            already_consumed_by_key = aggregate_nutrients(other_items, other_nutrients_by_food_id)

    result = suggest_ingredients(
        db, profile, items, nutrients_by_food_id, period,
        max_additional_energy=max_additional_energy, max_suggestions=max_suggestions,
        priority_nutrient_keys=priority_keys, meal_type=meal, day_count=day_count,
        already_consumed_by_key=already_consumed_by_key,
    )

    return schemas.IngredientSuggestionsOut(
        suggestions=[
            schemas.IngredientSuggestionOut(
                food_id=s.food_id, food_name=s.food_name, quantity_g=s.quantity_g, candidate_kind=s.candidate_kind,
                score=s.score.total, score_breakdown=_score_breakdown_out(s.score),
                nutrients_improved=s.nutrients_improved, remaining_shortfalls=s.remaining_shortfalls,
                new_warnings=s.new_warnings, extra_energy_kcal=s.extra_energy_kcal, data_coverage=s.data_coverage,
                fdc_id=s.fdc_id, data_type=s.data_type, candidate_source=s.candidate_source,
                explanation=s.explanation,
            )
            for s in result.suggestions
        ],
        warnings=[w.value for w in eligibility.warnings],
    )


@router.get("/recipes", response_model=schemas.RecipeSuggestionsOut)
def get_recipe_suggestions(
    entry_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Source = "diary",
    max_additional_energy: float | None = Query(default=None, ge=0, le=MAX_ADDITIONAL_ENERGY_CAP),
    max_suggestions: int = Query(
        default=DEFAULT_MAX_RECIPE_SUGGESTIONS, ge=MIN_MAX_SUGGESTIONS, le=MAX_MAX_SUGGESTIONS,
    ),
    priority_nutrients: str | None = None,
    goal: str | None = None,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Suggests up to `max_suggestions` recipes (the user's own, shared
    with them, or public) to close the biggest current nutrient gaps for
    a diary day, meal-plan day, or (via `start_date`+`end_date`, with
    `source='meal_plan'`) a multi-day meal-plan range — "Improve this
    plan" on the multi-day summary page. Exactly one of `entry_date` or
    `start_date`+`end_date` must be given. `goal` is one of
    `recommend_recipes.GOAL_PRESETS`
    (`overall_balance`/`protein_quality`/`fibre`/`iron_folate`/`calcium`);
    an explicit `priority_nutrients` overrides it. Returns an empty
    `suggestions` list — never an error — when nothing logged has a gap,
    or no visible recipe helps."""
    # --- basic shape/semantic validation first, no database work yet ---
    if goal is not None and goal not in GOAL_PRESETS:
        raise HTTPException(status_code=422, detail=f"goal must be one of {sorted(GOAL_PRESETS)}")
    is_range = start_date is not None or end_date is not None
    if is_range == (entry_date is not None):
        raise HTTPException(status_code=422, detail="give exactly one of entry_date or start_date+end_date")
    if is_range:
        if start_date is None or end_date is None:
            raise HTTPException(status_code=422, detail="start_date and end_date must both be given")
        if source != "meal_plan":
            raise HTTPException(status_code=422, detail="a multi-day range requires source='meal_plan'")
        validate_date_range(start_date, end_date)
    priority_keys = parse_priority_nutrients(priority_nutrients)

    # --- only now does any database work start ---
    eligibility = assess_eligibility(profile, db)
    if not eligibility.enabled:
        return schemas.RecipeSuggestionsOut(
            suggestions=[], disabled_reason=eligibility.disabled_reason,
            disabled_reason_code=_disabled_reason_code_out(eligibility), warnings=[w.value for w in eligibility.warnings],
        )

    if is_range:
        entries = _load_entries_range(db, profile, start_date, end_date, source)
        period = AnalysisPeriod.MULTI_DAY
        day_count = (end_date - start_date).days + 1
    else:
        entries = _load_entries(db, profile, entry_date, source)
        period = AnalysisPeriod.DAY
        day_count = 1

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}
    items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)

    all_food_ids = [item.food.id for item in items]
    nutrients_by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all():
        nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    result = suggest_recipes(
        db, profile, current_user, items, nutrients_by_food_id, period,
        max_additional_energy=max_additional_energy, max_suggestions=max_suggestions,
        priority_nutrient_keys=priority_keys, goal=goal,
        excluded_recipe_ids=recipe_ids, day_count=day_count,
    )

    return schemas.RecipeSuggestionsOut(
        suggestions=[
            schemas.RecipeSuggestionOut(
                recipe_id=s.recipe_id, recipe_name=s.recipe_name, suggested_servings=s.suggested_servings,
                energy_added_kcal=s.energy_added_kcal, protein_added_g=s.protein_added_g, score=s.score.total,
                score_breakdown=_score_breakdown_out(s.score),
                nutrients_improved=s.nutrients_improved, remaining_shortfalls=s.remaining_shortfalls,
                new_warnings=s.new_warnings, is_stock=s.is_stock, source_name=s.source_name,
                match_coverage_lines=s.match_coverage_lines, robustness_rating=s.robustness_rating,
                robustness_model_version=s.robustness_model_version,
                quality_summary=_quality_summary_out(s.quality_summary),
                robustness_note=s.robustness_note, explanation=s.explanation,
            )
            for s in result.suggestions
        ],
        warnings=[w.value for w in recipe_warnings(eligibility.warnings)],
    )


@router.get("/substitutions", response_model=schemas.SubstitutionSuggestionsOut)
def get_substitution_suggestions(
    entry_id: int = Query(gt=0),
    source: Source = "diary",
    max_suggestions: int = Query(
        default=DEFAULT_MAX_SUBSTITUTION_SUGGESTIONS, ge=MIN_MAX_SUGGESTIONS, le=MAX_MAX_SUGGESTIONS,
    ),
    priority_nutrients: str | None = None,
    energy_tolerance_kcal: float = Query(default=150.0, ge=0, le=MAX_ENERGY_TOLERANCE_CAP),
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
    priority_keys = parse_priority_nutrients(priority_nutrients)

    model = MealPlanEntry if source == "meal_plan" else DiaryEntry
    entry = db.query(model).filter(model.id == entry_id, model.profile_id == profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.recipe_id is None:
        raise HTTPException(status_code=422, detail="Entry has no recipe to substitute — it's a plain food entry")

    # entry.recipe_id came from the caller's own already-profile-scoped
    # entry, not a directly attacker-suppliable parameter, but this still
    # goes through the canonical resolver rather than db.get() directly —
    # consistent policy, and it degrades to a clean 404 (rather than
    # exposing a recipe the user no longer has rights to) if the recipe
    # was deleted or made private after being logged.
    current_recipe = get_visible_recipe(entry.recipe_id, current_user, db)

    eligibility = assess_eligibility(profile, db)
    if not eligibility.enabled:
        return schemas.SubstitutionSuggestionsOut(
            current_recipe_id=current_recipe.id, current_recipe_name=current_recipe.name,
            current_entry_updated_at=entry.updated_at,
            suggestions=[], disabled_reason=eligibility.disabled_reason,
            disabled_reason_code=_disabled_reason_code_out(eligibility), warnings=[w.value for w in eligibility.warnings],
        )

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

    result = suggest_substitutions(
        db, profile, current_user, other_items, current_recipe, entry.quantity_servings, nutrients_by_food_id,
        AnalysisPeriod.DAY, max_suggestions=max_suggestions, priority_nutrient_keys=priority_keys,
        energy_tolerance_kcal=energy_tolerance_kcal,
    )

    return schemas.SubstitutionSuggestionsOut(
        current_recipe_id=result.current_recipe_id, current_recipe_name=result.current_recipe_name,
        current_entry_updated_at=entry.updated_at,
        suggestions=[
            schemas.SubstitutionSuggestionOut(
                current_recipe_id=s.current_recipe_id, current_recipe_name=s.current_recipe_name,
                current_servings=s.current_servings, current_entry_updated_at=entry.updated_at,
                replacement_recipe_id=s.replacement_recipe_id,
                replacement_recipe_name=s.replacement_recipe_name, replacement_servings=s.replacement_servings,
                energy_difference_kcal=s.energy_difference_kcal, protein_difference_g=s.protein_difference_g,
                fiber_difference_g=s.fiber_difference_g, saturated_fat_difference_g=s.saturated_fat_difference_g,
                sodium_difference_mg=s.sodium_difference_mg, key_nutrient_differences=s.key_nutrient_differences,
                protein_quality_before=s.protein_quality_before, protein_quality_after=s.protein_quality_after,
                score=s.score.total, score_breakdown=_score_breakdown_out(s.score),
                remaining_shortfalls=s.remaining_shortfalls, new_warnings=s.new_warnings,
                is_stock=s.is_stock, match_coverage_lines=s.match_coverage_lines,
                robustness_rating=s.robustness_rating, robustness_model_version=s.robustness_model_version,
                quality_summary=_quality_summary_out(s.quality_summary),
                provenance_note=s.provenance_note, explanation=s.explanation,
            )
            for s in result.suggestions
        ],
        warnings=[w.value for w in recipe_warnings(eligibility.warnings)],
    )


@router.post("/substitutions/apply", response_model=schemas.SubstitutionApplyOut)
def apply_substitution(
    body: schemas.SubstitutionApplyIn,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    """Applies a previously-shown substitution suggestion — hardening
    prompt 6, extended by prompt 8's follow-up review. Replaces the
    two-call delete-then-recreate pattern the frontend used to do itself
    (a real data-loss risk: if the second call failed after the first
    succeeded, the entry was just gone) with a single in-place mutation
    of the target entry's `recipe_id`/`quantity_servings`, committed
    once. That single UPDATE is what makes this atomic — there's no
    window where the entry doesn't exist.

    Two independent staleness checks, both against the entry, not the
    request: `expected_current_recipe_id` must match the entry's current
    recipe, and `expected_updated_at` must match its current mutation
    timestamp. Either mismatch means the entry moved on since the
    suggestion was generated (edited some other way, already
    substituted, or replayed) — rejected with 409 rather than silently
    overwriting whatever is there now. The recipe_id check alone also
    catches a duplicate/replayed apply (the second request no longer
    matches after the first one already swapped the recipe); the
    timestamp check is the broader "full entry-version" companion, since
    a hypothetical future edit that left recipe_id unchanged but touched
    some other field would still bump updated_at.

    The entry is looked up scoped to the caller's own profile (never a
    bare `db.get`), so this can't touch another user's diary/meal-plan
    entry. The replacement recipe is re-resolved through
    `get_visible_recipe` at apply time, not trusted from whatever the
    suggestion said earlier, so a recipe that was deleted or made
    private between suggestion and apply can't be logged. It's also
    re-checked against the profile's current hard dietary exclusions
    (`filter_excluded_recipes`) — a constraint added *after* the
    suggestion was generated must still block the apply, the same
    "revalidate at apply time" principle already applied to visibility
    and eligibility below. Recommendation generation itself stays
    read-only; this is the one write path, and it's the only one."""
    model = MealPlanEntry if body.source == "meal_plan" else DiaryEntry
    entry = db.query(model).filter(model.id == body.entry_id, model.profile_id == profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.recipe_id is None:
        raise HTTPException(status_code=422, detail="Entry has no recipe to substitute — it's a plain food entry")
    if entry.recipe_id != body.expected_current_recipe_id:
        raise HTTPException(
            status_code=409,
            detail="Entry's current recipe has changed since this suggestion was generated",
        )
    if _as_utc(entry.updated_at) != _as_utc(body.expected_updated_at):
        raise HTTPException(
            status_code=409,
            detail="Entry has changed since this suggestion was generated",
        )

    replacement = get_visible_recipe(body.replacement_recipe_id, current_user, db)
    if not filter_excluded_recipes([replacement], db, profile):
        raise HTTPException(
            status_code=422,
            detail="Replacement recipe conflicts with a dietary exclusion for this profile",
        )

    eligibility = assess_eligibility(profile, db)
    if not eligibility.enabled:
        raise HTTPException(status_code=422, detail="Recommendations are currently disabled for this profile")

    entry.recipe_id = replacement.id
    entry.quantity_servings = body.replacement_servings
    db.commit()

    return schemas.SubstitutionApplyOut(
        entry_id=entry.id, source=body.source, recipe_id=replacement.id,
        recipe_name=replacement.name, quantity_servings=entry.quantity_servings,
    )


@router.get("/pairs", response_model=schemas.PairSuggestionsOut)
def get_pair_suggestions(
    entry_date: date,
    source: Source = "diary",
    max_additional_energy: float | None = Query(default=None, ge=0, le=MAX_ADDITIONAL_ENERGY_CAP),
    max_suggestions: int = Query(default=DEFAULT_MAX_PAIR_SUGGESTIONS, ge=MIN_MAX_SUGGESTIONS, le=MAX_MAX_SUGGESTIONS),
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
    priority_keys = parse_priority_nutrients(priority_nutrients)

    eligibility = assess_eligibility(profile, db)
    if not eligibility.enabled:
        return schemas.PairSuggestionsOut(
            suggestions=[], disabled_reason=eligibility.disabled_reason,
            disabled_reason_code=_disabled_reason_code_out(eligibility), warnings=[w.value for w in eligibility.warnings],
        )

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

    result = suggest_pairs(
        db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        max_additional_energy=max_additional_energy, max_suggestions=max_suggestions,
        priority_nutrient_keys=priority_keys,
    )

    return schemas.PairSuggestionsOut(
        suggestions=[
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
                score_breakdown=_score_breakdown_out(s.score),
                nutrients_improved=s.nutrients_improved, remaining_shortfalls=s.remaining_shortfalls,
                new_warnings=s.new_warnings, explanation=s.explanation,
            )
            for s in result.suggestions
        ],
        warnings=[w.value for w in eligibility.warnings],
    )
