""""Suggest recipes" — prompt 7 of the nutrient-gap recommendation
feature (see docs/nutrient-gap-recommendations.md).

Same shape as recommend_ingredients.py (candidate pool -> hard filters ->
real before/after simulation -> recommendation_scoring.score_candidate),
generalised to whole recipes at their own serving size instead of a
single food at a curated gram quantity. Reuses ownership/visibility rules
exactly as routers/diary.py's existing `_rank_recipes_by_nutrient`
already does (own + shared + public, dietary-filtered) — this module
doesn't reinvent recipe visibility, just broadens the ranking from one
nutrient to the full multi-nutrient scoring engine.

Recipes carry no meal-type/category metadata at all (confirmed in the
prompt-1 audit) — `meal_type` filtering is therefore a documented no-op
for recipe suggestions specifically (unlike `recommend_ingredients.py`,
where `candidate_metadata.py` supplies it), stated explicitly rather than
silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .aggregation import (
    WeightedFood,
    aggregate_nutrients,
    compute_protein_quality_with_coverage,
    scale_recipe_ingredients,
)
from .dietary_filter import filter_excluded_recipes, recipes_dietary_status
from .models import Food, FoodNutrient, Recipe, RecipeIngredient, RecipeShare, RobustnessResult, User, Profile
from .nutrient_gap_analysis import NutrientStatus, analyse_nutrient_gaps
from .nutrient_targets import AnalysisPeriod, NutrientTarget, resolve_nutrient_target
from .nutrients import NUTRIENTS
from .recommendation_scoring import PracticalityInput, ScoreBreakdown, ScoringWeights, score_candidate

CANDIDATE_POOL_PER_NUTRIENT = 10
DEFAULT_MAX_SUGGESTIONS = 3
# a recipe's own robustness rating below this is called out in the
# suggestion's note (still shown — never hidden — just flagged, matching
# this app's "explain the caveat, don't withhold the option" convention)
LOW_ROBUSTNESS_THRESHOLD = 3

# prompt 7's named modes -> which nutrients to prioritise. "overall_balance"
# (None) considers every optimisation-eligible nutrient currently short;
# "protein_quality" prioritises protein specifically (protein_quality_benefit
# itself is always considered by the scoring engine whenever DIAAS/PDCAAS
# before/after are supplied, regardless of mode).
GOAL_PRESETS: dict[str, set[str] | None] = {
    "overall_balance": None,
    "protein_quality": {"protein"},
    "fibre": {"fiber_total"},
    "iron_folate": {"iron", "folate"},
    "calcium": {"calcium"},
}


@dataclass(frozen=True)
class RecipeSuggestion:
    recipe_id: int
    recipe_name: str
    suggested_servings: float
    energy_added_kcal: float
    protein_added_g: float
    score: ScoreBreakdown
    nutrients_improved: list[str]
    remaining_shortfalls: list[str]
    new_warnings: list[str]
    is_stock: bool
    source_name: str | None
    match_coverage_lines: float | None
    robustness_rating: int | None
    robustness_note: str | None
    explanation: str


@dataclass(frozen=True)
class RejectedRecipe:
    recipe_name: str
    reason: str


@dataclass(frozen=True)
class RecipeSuggestionResult:
    suggestions: list[RecipeSuggestion]
    rejected: list[RejectedRecipe] = field(default_factory=list)


def visible_recipes(db: Session, current_user: User, profile: Profile) -> list[Recipe]:
    shared_recipe_ids = db.query(RecipeShare.recipe_id).filter(RecipeShare.shared_with_user_id == current_user.id)
    recipes = (
        db.query(Recipe)
        .filter(or_(Recipe.user_id == current_user.id, Recipe.is_public.is_(True), Recipe.id.in_(shared_recipe_ids)))
        .all()
    )
    return filter_excluded_recipes(recipes, db, profile)


def load_recipe_ingredients(db: Session, recipe_ids: list[int]) -> dict[int, list[RecipeIngredient]]:
    by_recipe: dict[int, list[RecipeIngredient]] = {}
    for row in db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id.in_(recipe_ids)).all():
        by_recipe.setdefault(row.recipe_id, []).append(row)
    return by_recipe


def _candidate_pool(
    db: Session, recipes: list[Recipe], ingredients_by_recipe: dict[int, list[RecipeIngredient]],
    foods_by_id: dict[int, Food], nutrients_by_food_id: dict[int, list[FoodNutrient]],
    target_keys: list[str], excluded_recipe_ids: set[int],
) -> list[tuple[Recipe, list[WeightedFood]]]:
    """Recipes carrying the most of any currently-short nutrient per
    serving, paired with their ingredients already expanded to 1 serving
    — same idea as recommend_ingredients._candidate_pool, one nutrient
    ranking per key, unioned, rather than one query across the whole
    catalog (recipes are always a small, already-loaded set, unlike
    foods, so this ranks in Python rather than a second SQL query)."""
    ranked_by_key: dict[str, list[tuple[Recipe, list[WeightedFood], float]]] = {}
    for recipe in recipes:
        if recipe.id in excluded_recipe_ids:
            continue
        ingredients = ingredients_by_recipe.get(recipe.id)
        if not ingredients:
            continue
        items = scale_recipe_ingredients(ingredients, recipe.servings, 1.0, foods_by_id)
        totals = aggregate_nutrients(items, nutrients_by_food_id)
        for key in target_keys:
            amount = totals.get(key, 0.0)
            if amount > 0:
                ranked_by_key.setdefault(key, []).append((recipe, items, amount))

    seen_ids: set[int] = set(excluded_recipe_ids)
    pool: list[tuple[Recipe, list[WeightedFood]]] = []
    for key, ranked in ranked_by_key.items():
        ranked.sort(key=lambda t: t[2], reverse=True)
        for recipe, items, _amount in ranked[:CANDIDATE_POOL_PER_NUTRIENT]:
            if recipe.id not in seen_ids:
                pool.append((recipe, items))
                seen_ids.add(recipe.id)
    return pool


def _primary_ingredient_food_id(items: list[WeightedFood]) -> int | None:
    """The ingredient contributing the most mass — a real, inspectable
    signal (not a fabricated "recipe family") used to deduplicate
    near-identical suggestions (prompt 7's diversity rule)."""
    if not items:
        return None
    return max(items, key=lambda i: i.quantity_g).food.id


def _deduplicate_by_primary_ingredient(suggestions: list[RecipeSuggestion], items_by_recipe_id: dict[int, list[WeightedFood]]) -> list[RecipeSuggestion]:
    """Keeps only the highest-scoring recipe per primary ingredient —
    prompt 7: "avoid returning near-duplicate recipes ... simple diversity
    rule based on ... primary ingredients." Input must already be sorted
    by score descending so "first seen" is "best scoring"."""
    seen_primary: set[int] = set()
    result: list[RecipeSuggestion] = []
    for suggestion in suggestions:
        primary = _primary_ingredient_food_id(items_by_recipe_id.get(suggestion.recipe_id, []))
        if primary is not None and primary in seen_primary:
            continue
        if primary is not None:
            seen_primary.add(primary)
        result.append(suggestion)
    return result


def _robustness_note(recipe: Recipe, rating: int | None) -> str | None:
    if not recipe.is_public and recipe.import_slug is None:
        return None
    if rating is None:
        return "Robustness has not yet been computed for this recipe."
    if rating < LOW_ROBUSTNESS_THRESHOLD:
        return f"This recipe's robustness rating is low ({rating}/5) — its nutrient totals carry more uncertainty than usual."
    return f"Robustness rating: {rating}/5."


def suggest_recipes(
    db: Session,
    profile: Profile,
    current_user: User,
    items: list[WeightedFood],
    nutrients_by_food_id: dict[int, list[FoodNutrient]],
    period: AnalysisPeriod,
    *,
    max_additional_energy: float | None = None,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
    priority_nutrient_keys: set[str] | None = None,
    goal: str | None = None,
    excluded_recipe_ids: set[int] | None = None,
    day_count: int = 1,
    weights: ScoringWeights | None = None,
) -> RecipeSuggestionResult:
    """`items`/`nutrients_by_food_id` are the caller's current
    meal/day/meal-plan-day/multi-day state, same convention as
    `recommend_ingredients.suggest_ingredients`. `goal` looks up
    `GOAL_PRESETS`; an explicit `priority_nutrient_keys` overrides it."""
    excluded_recipe_ids = excluded_recipe_ids or set()
    weights = weights or ScoringWeights()
    if priority_nutrient_keys is None and goal is not None:
        priority_nutrient_keys = GOAL_PRESETS.get(goal)

    before_totals = aggregate_nutrients(items, nutrients_by_food_id)
    target_by_key: dict[str, NutrientTarget] = {}
    for key in NUTRIENTS:
        target = resolve_nutrient_target(key, profile, period, day_count=day_count)
        if target is not None:
            target_by_key[key] = target

    before_gaps = analyse_nutrient_gaps(
        items, nutrients_by_food_id, before_totals, target_by_key, priority_keys=priority_nutrient_keys,
    )
    shortfall_keys = [
        g.key for g in before_gaps
        if g.status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        and (priority_nutrient_keys is None or g.key in priority_nutrient_keys)
    ]
    if not shortfall_keys:
        return RecipeSuggestionResult(suggestions=[])

    visible = visible_recipes(db, current_user, profile)
    if not visible:
        return RecipeSuggestionResult(suggestions=[])

    # "is_stock" (shown to the end user) is defined by the owning
    # account's is_system flag, exactly as routers/recipes.py's own
    # _recipe_out already does — not import_slug, which is only reliable
    # as a signal for "did the stock-recipe pipeline compute match/
    # robustness data for this recipe", a different (if usually
    # correlated) question answered separately below.
    owner_ids = {r.user_id for r in visible}
    is_system_owner = {u.id: u.is_system for u in db.query(User).filter(User.id.in_(owner_ids)).all()}

    ingredients_by_recipe = load_recipe_ingredients(db, [r.id for r in visible])
    all_food_ids = {i.food_id for rows in ingredients_by_recipe.values() for i in rows}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(all_food_ids)).all()}
    working_nutrients_by_food_id = dict(nutrients_by_food_id)
    # only fetch nutrient rows for a food_id not already supplied by the
    # caller — some recipe ingredients may be foods already logged that
    # day/meal too, and re-querying + re-appending those would double
    # their contribution when aggregate_nutrients sums the list
    missing_food_ids = [fid for fid in all_food_ids if fid not in working_nutrients_by_food_id]
    if missing_food_ids:
        for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(missing_food_ids)).all():
            working_nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    pool = _candidate_pool(
        db, visible, ingredients_by_recipe, foods_by_id, working_nutrients_by_food_id, shortfall_keys,
        excluded_recipe_ids,
    )
    if not pool:
        return RecipeSuggestionResult(suggestions=[])

    suitability_by_id = recipes_dietary_status([r for r, _ in pool], db, profile)
    robustness_by_recipe_id = {
        rr.recipe_id: rr
        for rr in db.query(RobustnessResult)
        .filter(RobustnessResult.recipe_id.in_([r.id for r, _ in pool]), RobustnessResult.is_latest.is_(True))
        .all()
    }

    rejected: list[RejectedRecipe] = []
    scored: list[RecipeSuggestion] = []
    items_by_recipe_id: dict[int, list[WeightedFood]] = {}

    protein_quality_before = compute_protein_quality_with_coverage(items, "diaas") if items else None

    for recipe, recipe_items_at_1_serving in pool:
        servings = 1.0
        trial_items = items + recipe_items_at_1_serving
        after_totals = aggregate_nutrients(trial_items, working_nutrients_by_food_id)
        after_gaps = analyse_nutrient_gaps(
            trial_items, working_nutrients_by_food_id, after_totals, target_by_key, priority_keys=priority_nutrient_keys,
        )

        energy_added = after_totals.get("energy", 0.0) - before_totals.get("energy", 0.0)
        if max_additional_energy is not None and energy_added > max_additional_energy:
            rejected.append(RejectedRecipe(recipe.name, f"would add {energy_added:.0f}kcal, above the requested cap"))
            continue

        protein_before_g = before_totals.get("protein", 0.0)
        protein_after_g = after_totals.get("protein", 0.0)
        protein_quality_after = compute_protein_quality_with_coverage(trial_items, "diaas")

        suitability = suitability_by_id.get(recipe.id)
        robustness = robustness_by_recipe_id.get(recipe.id)
        robustness_rating = robustness.overall_rating if robustness else None

        # ingredient-match confidence for a stock recipe (real, imported,
        # measured coverage); a user's own hand-built recipe has no such
        # concept at all — no penalty for something this app never claimed
        # to measure for it
        ingredient_confidence = recipe.match_coverage_lines if recipe.import_slug else None
        candidate_data_coverage = recipe.match_coverage_mass if recipe.import_slug else 1.0
        if robustness_rating is not None and robustness_rating < LOW_ROBUSTNESS_THRESHOLD:
            candidate_data_coverage = min(candidate_data_coverage or 1.0, 0.6)

        score = score_candidate(
            before_gaps, after_gaps, energy_added=energy_added, max_additional_energy=max_additional_energy,
            protein_quality_before=protein_quality_before, protein_quality_after=protein_quality_after,
            dietary_suitability=suitability, ingredient_confidence=ingredient_confidence,
            candidate_data_coverage=candidate_data_coverage,
            practicality=PracticalityInput(is_plausible_serving=True),  # a recipe's own serving size is always "plausible" by definition
            weights=weights,
        )
        if score.total <= 0:
            rejected.append(RejectedRecipe(recipe.name, "did not meaningfully improve the current gaps"))
            continue

        after_by_key = {g.key: g for g in after_gaps}
        remaining = [
            k for k in shortfall_keys
            if after_by_key.get(k) and after_by_key[k].status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        ]
        new_warnings = [g.key for g in after_gaps if g.key in score.nutrients_worsened]

        items_by_recipe_id[recipe.id] = recipe_items_at_1_serving
        scored.append(RecipeSuggestion(
            recipe_id=recipe.id, recipe_name=recipe.name, suggested_servings=servings,
            energy_added_kcal=energy_added, protein_added_g=protein_after_g - protein_before_g,
            score=score, nutrients_improved=score.nutrients_improved, remaining_shortfalls=remaining,
            new_warnings=new_warnings, is_stock=is_system_owner.get(recipe.user_id, False), source_name=recipe.source_name,
            match_coverage_lines=recipe.match_coverage_lines, robustness_rating=robustness_rating,
            robustness_note=_robustness_note(recipe, robustness_rating),
            explanation=_explain(recipe.name, servings, score),
        ))

    scored.sort(key=lambda s: (-s.score.total, s.recipe_name))
    deduplicated = _deduplicate_by_primary_ingredient(scored, items_by_recipe_id)
    return RecipeSuggestionResult(suggestions=deduplicated[:max_suggestions], rejected=rejected)


def _explain(recipe_name: str, servings: float, score: ScoreBreakdown) -> str:
    serving_word = "serving" if servings == 1.0 else "servings"
    if not score.nutrients_improved:
        return f"Adding {servings:g} {serving_word} of {recipe_name}."
    nutrients = ", ".join(NUTRIENTS[k].name for k in score.nutrients_improved if k in NUTRIENTS)
    return f"Adding {servings:g} {serving_word} of {recipe_name} helps close the remaining {nutrients} gap."
