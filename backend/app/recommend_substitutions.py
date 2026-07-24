""""Substitutions" — prompt 8 of the nutrient-gap recommendation feature
(see docs/nutrient-gap-recommendations.md).

Replaces an existing logged recipe (a diary meal or a meal-plan item)
rather than only adding food. The mechanics: take the day's other
entries as a fixed baseline, remove the target recipe hypothetically,
analyse what gap that leaves, then rank real replacement recipes at a
servings count chosen to keep energy similar to what's being removed
(prompt 8's "prefer similar energy") — never estimated, always
`aggregate_nutrients` on the actual candidate ingredients at that
servings count, same convention as every other `recommend_*` module.

This module only ever proposes — it has no apply/write path of its own.
Prompt 8 originally had a substitution applied through the *existing*
meal-plan/diary update endpoints (delete the old entry, log the new
one), reasoning that a bespoke "commit this swap" endpoint would be a
second, redundant way to mutate a diary/meal-plan entry. Hardening
prompt 6 revisited that: the two-call delete-then-recreate the frontend
did to imitate "replace" was not atomic — a failure between the two
calls silently lost the entry — so `POST /api/recommendations/
substitutions/apply` (routers/recommendations.py) now does the mutation
itself, as a single in-place UPDATE of the target entry. It's still the
only write path for a substitution; this module remains read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .aggregation import (
    WeightedFood,
    aggregate_nutrients,
    compute_protein_quality_with_coverage,
    scale_recipe_ingredients,
)
from .dietary_filter import recipes_dietary_status
from .models import Food, FoodNutrient, Profile, Recipe, RobustnessResult, User
from .nutrient_gap_analysis import NutrientStatus, analyse_nutrient_gaps
from .nutrient_targets import AnalysisPeriod, NutrientTarget, resolve_nutrient_target
from .nutrients import NUTRIENTS
from .recommend_recipes import LOW_ROBUSTNESS_THRESHOLD, load_recipe_ingredients, visible_recipes
from .recommendation_provenance import RecipeQualitySummary, compute_recipe_quality_summary
from .recommendation_scoring import PracticalityInput, ScoreBreakdown, ScoringWeights, score_candidate

DEFAULT_MAX_SUGGESTIONS = 3
# how close a replacement's energy must land to the recipe being replaced
# to count as "similar energy" (prompt 8) without being rejected outright
# — a soft preference expressed as a scoring penalty (see
# recommendation_scoring's own energy_overshoot machinery), not a hard cutoff
DEFAULT_ENERGY_TOLERANCE_KCAL = 150.0
# a replacement is tried at servings scaled to approximately match the
# original's energy contribution, clamped to a sane range — never asked
# to serve 0.02 or 40 servings just to hit an exact energy number
MIN_REPLACEMENT_SERVINGS = 0.5
MAX_REPLACEMENT_SERVINGS = 3.0

# nutrients whose before/after difference is always reported, regardless
# of whether they're in the caller's priority set — prompt 8's named list
# ("protein, fibre, key micronutrient changes, saturated fat, sodium")
_ALWAYS_REPORTED_DIFFERENCES = ("protein", "fiber_total", "saturated_fat", "sodium", "iron", "calcium", "folate")


@dataclass(frozen=True)
class SubstitutionSuggestion:
    current_recipe_id: int
    current_recipe_name: str
    current_servings: float
    replacement_recipe_id: int
    replacement_recipe_name: str
    replacement_servings: float
    energy_difference_kcal: float
    protein_difference_g: float
    fiber_difference_g: float
    saturated_fat_difference_g: float
    sodium_difference_mg: float
    key_nutrient_differences: dict[str, float]
    protein_quality_before: float | None
    protein_quality_after: float | None
    score: ScoreBreakdown
    remaining_shortfalls: list[str]
    new_warnings: list[str]
    is_stock: bool
    match_coverage_lines: float | None
    robustness_rating: int | None
    robustness_model_version: str | None
    quality_summary: RecipeQualitySummary
    provenance_note: str | None
    explanation: str


@dataclass(frozen=True)
class RejectedSubstitution:
    recipe_name: str
    reason: str


@dataclass(frozen=True)
class SubstitutionResult:
    current_recipe_id: int
    current_recipe_name: str
    suggestions: list[SubstitutionSuggestion]
    rejected: list[RejectedSubstitution]


def _choose_replacement_servings(
    original_energy_kcal: float, replacement_per_serving_energy: float,
) -> float:
    if replacement_per_serving_energy <= 0 or original_energy_kcal <= 0:
        return 1.0
    raw = original_energy_kcal / replacement_per_serving_energy
    clamped = max(MIN_REPLACEMENT_SERVINGS, min(raw, MAX_REPLACEMENT_SERVINGS))
    return round(clamped * 2) / 2  # nearest half-serving — a real, orderable quantity


def suggest_substitutions(
    db: Session,
    profile: Profile,
    current_user: User,
    other_items: list[WeightedFood],
    current_recipe: Recipe,
    current_servings: float,
    nutrients_by_food_id: dict[int, list[FoodNutrient]],
    period: AnalysisPeriod,
    *,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
    priority_nutrient_keys: set[str] | None = None,
    energy_tolerance_kcal: float = DEFAULT_ENERGY_TOLERANCE_KCAL,
    max_upper_limit_breach: bool = False,
    day_count: int = 1,
    weights: ScoringWeights | None = None,
) -> SubstitutionResult:
    """`other_items` is the day's/plan's entries EXCLUDING the one being
    replaced — the fixed baseline `current_recipe` is hypothetically
    removed from and replacement recipes are hypothetically added to.
    `current_servings` is how the target was actually logged (matches
    `MealPlanEntry`/`DiaryEntry.quantity_servings`).

    `max_upper_limit_breach`, when False (default), rejects any
    replacement that would newly cross a nutrient's upper limit —
    prompt 8's implicit "don't recommend a swap that creates a new
    safety-relevant excess" alongside the softer energy-similarity
    preference.
    """
    weights = weights or ScoringWeights()

    working_nutrients_by_food_id = dict(nutrients_by_food_id)

    ingredients_by_recipe = load_recipe_ingredients(db, [current_recipe.id])
    foods_by_id: dict[int, Food] = {}
    current_ingredients = ingredients_by_recipe.get(current_recipe.id, [])
    if current_ingredients:
        food_ids = [i.food_id for i in current_ingredients]
        foods_by_id.update({f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()})
        # defensively fetch nutrient data for the recipe being replaced,
        # regardless of what the caller happened to already supply — the
        # caller is expected to have loaded the whole day's/plan's foods
        # (which includes this recipe), but this function must give a
        # correct `current_energy`/`with_current_totals` even if it didn't
        missing_current_food_ids = [fid for fid in food_ids if fid not in working_nutrients_by_food_id]
        if missing_current_food_ids:
            for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(missing_current_food_ids)).all():
                working_nutrients_by_food_id.setdefault(row.food_id, []).append(row)
    current_items = scale_recipe_ingredients(current_ingredients, current_recipe.servings, current_servings, foods_by_id)

    target_by_key: dict[str, NutrientTarget] = {}
    for key in NUTRIENTS:
        target = resolve_nutrient_target(key, profile, period, day_count=day_count)
        if target is not None:
            target_by_key[key] = target

    with_current_items = other_items + current_items
    with_current_totals = aggregate_nutrients(with_current_items, working_nutrients_by_food_id)
    without_totals = aggregate_nutrients(other_items, working_nutrients_by_food_id)
    without_gaps = analyse_nutrient_gaps(
        other_items, working_nutrients_by_food_id, without_totals, target_by_key, priority_keys=priority_nutrient_keys,
    )

    current_energy = with_current_totals.get("energy", 0.0) - without_totals.get("energy", 0.0)

    shortfall_keys = [
        g.key for g in without_gaps
        if g.status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        and (priority_nutrient_keys is None or g.key in priority_nutrient_keys)
    ] or list(_ALWAYS_REPORTED_DIFFERENCES)

    visible = visible_recipes(db, current_user, profile)
    visible = [r for r in visible if r.id != current_recipe.id]
    if not visible:
        return SubstitutionResult(current_recipe.id, current_recipe.name, [], [])

    ingredients_by_recipe = load_recipe_ingredients(db, [r.id for r in visible])
    all_food_ids = {i.food_id for rows in ingredients_by_recipe.values() for i in rows}
    foods_by_id.update({f.id: f for f in db.query(Food).filter(Food.id.in_(all_food_ids)).all()})
    missing_food_ids = [fid for fid in all_food_ids if fid not in working_nutrients_by_food_id]
    if missing_food_ids:
        for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(missing_food_ids)).all():
            working_nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    suitability_by_id = recipes_dietary_status(visible, db, profile)
    robustness_by_recipe_id = {
        rr.recipe_id: rr
        for rr in db.query(RobustnessResult)
        .filter(RobustnessResult.recipe_id.in_([r.id for r in visible]), RobustnessResult.is_latest.is_(True))
        .all()
    }
    is_system_owner = {
        u.id: u.is_system for u in db.query(User).filter(User.id.in_({r.user_id for r in visible})).all()
    }

    protein_quality_before = compute_protein_quality_with_coverage(with_current_items, "diaas")

    rejected: list[RejectedSubstitution] = []
    scored: list[SubstitutionSuggestion] = []

    for recipe in visible:
        ingredients = ingredients_by_recipe.get(recipe.id)
        if not ingredients:
            continue
        per_serving_items = scale_recipe_ingredients(ingredients, recipe.servings, 1.0, foods_by_id)
        per_serving_totals = aggregate_nutrients(per_serving_items, working_nutrients_by_food_id)
        per_serving_energy = per_serving_totals.get("energy", 0.0)
        if per_serving_energy <= 0:
            continue

        replacement_servings = _choose_replacement_servings(current_energy, per_serving_energy)
        replacement_items = scale_recipe_ingredients(ingredients, recipe.servings, replacement_servings, foods_by_id)
        trial_items = other_items + replacement_items
        after_totals = aggregate_nutrients(trial_items, working_nutrients_by_food_id)
        after_gaps = analyse_nutrient_gaps(
            trial_items, working_nutrients_by_food_id, after_totals, target_by_key, priority_keys=priority_nutrient_keys,
        )

        energy_difference = after_totals.get("energy", 0.0) - current_energy
        if not max_upper_limit_breach and any(
            g.status == NutrientStatus.ABOVE_UPPER_LIMIT
            and next((wg.status for wg in without_gaps if wg.key == g.key), None) != NutrientStatus.ABOVE_UPPER_LIMIT
            for g in after_gaps
        ):
            rejected.append(RejectedSubstitution(recipe.name, "would push a nutrient newly above its upper limit"))
            continue

        suitability = suitability_by_id.get(recipe.id)
        robustness = robustness_by_recipe_id.get(recipe.id)
        robustness_rating = robustness.overall_rating if robustness else None
        ingredient_confidence = recipe.match_coverage_lines if recipe.import_slug else None
        candidate_data_coverage = recipe.match_coverage_mass if recipe.import_slug else 1.0
        if robustness_rating is not None and robustness_rating < LOW_ROBUSTNESS_THRESHOLD:
            candidate_data_coverage = min(candidate_data_coverage or 1.0, 0.6)

        protein_quality_after = compute_protein_quality_with_coverage(trial_items, "diaas")

        score = score_candidate(
            without_gaps, after_gaps, energy_added=energy_difference,
            max_additional_energy=energy_tolerance_kcal if energy_difference > 0 else None,
            protein_quality_before=protein_quality_before, protein_quality_after=protein_quality_after,
            dietary_suitability=suitability, ingredient_confidence=ingredient_confidence,
            candidate_data_coverage=candidate_data_coverage,
            practicality=PracticalityInput(is_plausible_serving=True), weights=weights,
        )
        if score.total <= 0:
            rejected.append(RejectedSubstitution(recipe.name, "did not represent a net improvement"))
            continue

        after_by_key = {g.key: g for g in after_gaps}
        remaining = [
            k for k in shortfall_keys
            if after_by_key.get(k) and after_by_key[k].status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        ]
        new_warnings = [g.key for g in after_gaps if g.key in score.nutrients_worsened]

        # replacement's own contribution minus the original's own
        # contribution, for each reported nutrient — not the day totals
        # themselves, so this is honestly "what changes because of the
        # swap" regardless of what else that day/plan contains
        key_diffs = {
            key: (after_totals.get(key, 0.0) - without_totals.get(key, 0.0))
            - (with_current_totals.get(key, 0.0) - without_totals.get(key, 0.0))
            for key in _ALWAYS_REPORTED_DIFFERENCES
            if key in NUTRIENTS
        }

        provenance_note = None
        if (ingredient_confidence or 1.0) < 0.9 or (candidate_data_coverage or 1.0) < 0.9:
            provenance_note = "This replacement's own ingredient-match/data confidence is lower than the recipe it would replace may have."

        quality_summary = compute_recipe_quality_summary(db, recipe, ingredients)
        scored.append(SubstitutionSuggestion(
            current_recipe_id=current_recipe.id, current_recipe_name=current_recipe.name,
            current_servings=current_servings, replacement_recipe_id=recipe.id, replacement_recipe_name=recipe.name,
            replacement_servings=replacement_servings, energy_difference_kcal=energy_difference,
            protein_difference_g=key_diffs.get("protein", 0.0), fiber_difference_g=key_diffs.get("fiber_total", 0.0),
            saturated_fat_difference_g=key_diffs.get("saturated_fat", 0.0), sodium_difference_mg=key_diffs.get("sodium", 0.0),
            key_nutrient_differences=key_diffs, protein_quality_before=protein_quality_before.score.score if protein_quality_before and protein_quality_before.score else None,
            protein_quality_after=protein_quality_after.score.score if protein_quality_after and protein_quality_after.score else None,
            score=score, remaining_shortfalls=remaining, new_warnings=new_warnings,
            is_stock=is_system_owner.get(recipe.user_id, False), match_coverage_lines=recipe.match_coverage_lines,
            robustness_rating=robustness_rating, robustness_model_version=robustness.model_version if robustness else None,
            quality_summary=quality_summary, provenance_note=provenance_note,
            explanation=_explain(current_recipe.name, recipe.name, energy_difference, score),
        ))

    scored.sort(key=lambda s: (-s.score.total, s.replacement_recipe_name))
    return SubstitutionResult(
        current_recipe_id=current_recipe.id, current_recipe_name=current_recipe.name,
        suggestions=scored[:max_suggestions], rejected=rejected,
    )


def _explain(current_name: str, replacement_name: str, energy_difference: float, score: ScoreBreakdown) -> str:
    energy_note = (
        f"about the same energy" if abs(energy_difference) < 20
        else f"{abs(energy_difference):.0f}kcal {'more' if energy_difference > 0 else 'less'}"
    )
    if not score.nutrients_improved:
        return f"Replacing {current_name} with {replacement_name} ({energy_note})."
    nutrients = ", ".join(NUTRIENTS[k].name for k in score.nutrients_improved if k in NUTRIENTS)
    return f"Replacing {current_name} with {replacement_name} ({energy_note}) helps close the remaining {nutrients} gap."
