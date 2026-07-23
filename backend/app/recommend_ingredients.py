""""Suggest additional ingredients" — prompt 6 of the nutrient-gap
recommendation feature, the first user-facing recommendation mode (see
docs/nutrient-gap-recommendations.md).

Generates candidates from `candidate_metadata.py`'s curated/safe-default
pool (never "every database row" — prompt 5's whole point), hard-filters
by dietary constraints (`dietary_filter.filter_excluded_foods` — the same
function search/discovery already uses), simulates each one's real
before/after effect through `aggregation.aggregate_nutrients` (never
estimated from raw per-100g content alone, matching `optimizer.py`'s
existing convention), and ranks with `recommendation_scoring.
score_candidate`. A candidate that doesn't clear a positive score is
never suggested — "no safe or useful option" is a real, valid, honestly
empty result, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_nutrients
from .candidate_metadata import is_plausible_serving, resolve_candidate_metadata
from .data_quality import is_implausible
from .dietary_filter import filter_excluded_foods, food_dietary_status
from .models import Food, FoodNutrient, Profile
from .nutrient_gap_analysis import NutrientStatus, analyse_nutrient_gaps
from .nutrient_targets import AnalysisPeriod, NutrientTarget, adjust_target_for_remaining, resolve_nutrient_target
from .nutrients import NUTRIENTS
from .recommendation_scoring import PracticalityInput, ScoreBreakdown, ScoringWeights, score_candidate

# how many top candidates to pull per nutrient the day/meal is currently
# short on, before dietary/metadata filtering and scoring — a shortlist,
# not "every food carrying this nutrient" (same shape as the existing
# _rank_foods_by_nutrient in routers/diary.py, generalised to more than
# one nutrient at once).
CANDIDATE_POOL_PER_NUTRIENT = 12
DEFAULT_MAX_SUGGESTIONS = 2


@dataclass(frozen=True)
class IngredientSuggestion:
    food_id: int
    food_name: str
    quantity_g: float
    candidate_kind: str
    score: ScoreBreakdown
    nutrients_improved: list[str]
    # nutrients still below/near target after adding this candidate — what
    # a caller might suggest addressing next, never framed as a deficiency
    remaining_shortfalls: list[str]
    # nutrients this candidate pushes to above_preferred/above_upper_limit
    new_warnings: list[str]
    extra_energy_kcal: float
    data_coverage: float
    explanation: str


@dataclass(frozen=True)
class RejectedCandidate:
    food_name: str
    reason: str


@dataclass(frozen=True)
class IngredientSuggestionResult:
    suggestions: list[IngredientSuggestion]
    rejected: list[RejectedCandidate] = field(default_factory=list)


def _candidate_pool(db: Session, target_keys: list[str], excluded_food_ids: set[int]) -> list[Food]:
    seen_ids = set(excluded_food_ids)
    candidates: list[Food] = []
    for key in target_keys:
        rows = (
            db.query(FoodNutrient)
            .filter(FoodNutrient.nutrient_key == key)
            .order_by(FoodNutrient.amount_per_100g.desc())
            .limit(CANDIDATE_POOL_PER_NUTRIENT * 5)
            .all()
        )
        rows = [r for r in rows if not is_implausible(r.nutrient_key, r.amount_per_100g)][:CANDIDATE_POOL_PER_NUTRIENT]
        new_food_ids = [r.food_id for r in rows if r.food_id not in seen_ids]
        if not new_food_ids:
            continue
        for food in db.query(Food).filter(Food.id.in_(new_food_ids)).all():
            if food.id not in seen_ids:
                candidates.append(food)
                seen_ids.add(food.id)
    return candidates


def _candidate_data_coverage(food: Food, nutrient_rows: list[FoodNutrient], target_keys: list[str]) -> float:
    if not target_keys:
        return 1.0
    covered_keys = {
        r.nutrient_key for r in nutrient_rows if not is_implausible(r.nutrient_key, r.amount_per_100g)
    }
    return len(covered_keys & set(target_keys)) / len(target_keys)


def suggest_ingredients(
    db: Session,
    profile: Profile,
    items: list[WeightedFood],
    nutrients_by_food_id: dict[int, list[FoodNutrient]],
    period: AnalysisPeriod,
    *,
    max_additional_energy: float | None = None,
    max_suggestions: int = DEFAULT_MAX_SUGGESTIONS,
    priority_nutrient_keys: set[str] | None = None,
    excluded_food_ids: set[int] | None = None,
    meal_type: str | None = None,
    allow_substantial_sides: bool = False,
    day_count: int = 1,
    already_consumed_by_key: dict[str, float] | None = None,
    weights: ScoringWeights | None = None,
) -> IngredientSuggestionResult:
    """`items`/`nutrients_by_food_id` are the caller's already-aggregated
    current state (a meal, a diary day, or a meal-plan day — whichever
    `period` describes; the caller is responsible for loading the right
    entries, e.g. via `aggregation.expand_entries_to_weighted_foods`, same
    as every existing diary/meal-plan endpoint already does). This
    function never queries DiaryEntry/MealPlanEntry itself, so it works
    identically for either source.

    `priority_nutrient_keys`, when given, restricts which nutrients drive
    candidate selection/scoring (prompt 6's "nutrients to prioritise") —
    None considers every optimisation-eligible tracked nutrient currently
    below/near target.
    """
    excluded_food_ids = excluded_food_ids or set()
    weights = weights or ScoringWeights()

    before_totals = aggregate_nutrients(items, nutrients_by_food_id)
    all_keys = list(NUTRIENTS.keys())
    target_by_key: dict[str, NutrientTarget] = {}
    for key in all_keys:
        target = resolve_nutrient_target(key, profile, period, day_count=day_count)
        if target is not None:
            if period == AnalysisPeriod.MEAL and already_consumed_by_key:
                target = adjust_target_for_remaining(target, already_consumed_by_key.get(key, 0.0))
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
        return IngredientSuggestionResult(suggestions=[])

    pool = _candidate_pool(db, shortfall_keys, excluded_food_ids)
    if not pool:
        return IngredientSuggestionResult(suggestions=[])

    pool = filter_excluded_foods(pool, db, profile)

    rejected: list[RejectedCandidate] = []
    scored: list[IngredientSuggestion] = []
    working_nutrients_by_food_id = dict(nutrients_by_food_id)

    for food in pool:
        metadata = resolve_candidate_metadata(food)
        if not metadata.suitable_for_direct_suggestion:
            rejected.append(RejectedCandidate(food.name, "not suitable for a direct standalone suggestion"))
            continue
        if meal_type is not None and metadata.suitable_meal_types and meal_type not in metadata.suitable_meal_types:
            rejected.append(RejectedCandidate(food.name, f"not typically suited to {meal_type}"))
            continue

        trial_quantity = metadata.serving.maximum_g if allow_substantial_sides else metadata.serving.default_g

        if food.id not in working_nutrients_by_food_id:
            working_nutrients_by_food_id[food.id] = (
                db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).all()
            )
        candidate_rows = working_nutrients_by_food_id[food.id]

        trial_items = items + [WeightedFood(food, trial_quantity)]
        after_totals = aggregate_nutrients(trial_items, working_nutrients_by_food_id)
        after_gaps = analyse_nutrient_gaps(
            trial_items, working_nutrients_by_food_id, after_totals, target_by_key, priority_keys=priority_nutrient_keys,
        )

        energy_added = after_totals.get("energy", 0.0) - before_totals.get("energy", 0.0)
        if max_additional_energy is not None and energy_added > max_additional_energy:
            rejected.append(RejectedCandidate(food.name, f"would add {energy_added:.0f}kcal, above the requested cap"))
            continue

        suitability = food_dietary_status(food, db, profile)
        coverage = _candidate_data_coverage(food, candidate_rows, shortfall_keys)
        practicality = PracticalityInput(is_plausible_serving=is_plausible_serving(metadata, trial_quantity))

        score = score_candidate(
            before_gaps, after_gaps, energy_added=energy_added, max_additional_energy=max_additional_energy,
            dietary_suitability=suitability, candidate_data_coverage=coverage, practicality=practicality,
            weights=weights,
        )
        if score.total <= 0:
            rejected.append(RejectedCandidate(food.name, "did not meaningfully improve the current gaps"))
            continue

        after_by_key = {g.key: g for g in after_gaps}
        remaining = [
            k for k in shortfall_keys
            if after_by_key.get(k) and after_by_key[k].status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        ]
        new_warnings = [
            g.key for g in after_gaps
            if g.status in (NutrientStatus.ABOVE_PREFERRED, NutrientStatus.ABOVE_UPPER_LIMIT) and g.key in score.nutrients_worsened
        ]

        scored.append(IngredientSuggestion(
            food_id=food.id, food_name=food.name, quantity_g=trial_quantity, candidate_kind=metadata.kind.value,
            score=score, nutrients_improved=score.nutrients_improved, remaining_shortfalls=remaining,
            new_warnings=new_warnings, extra_energy_kcal=energy_added, data_coverage=coverage,
            explanation=_explain(food.name, trial_quantity, score),
        ))

    # deterministic ordering: score desc, then food name — never left to
    # whatever order the DB/dict iteration happened to return
    scored.sort(key=lambda s: (-s.score.total, s.food_name))
    return IngredientSuggestionResult(suggestions=scored[:max_suggestions], rejected=rejected)


def _explain(food_name: str, quantity_g: float, score: ScoreBreakdown) -> str:
    if not score.nutrients_improved:
        return f"Adding {quantity_g:.0f}g of {food_name}."
    nutrients = ", ".join(NUTRIENTS[k].name for k in score.nutrients_improved if k in NUTRIENTS)
    return f"Adding {quantity_g:.0f}g of {food_name} helps close the remaining {nutrients} gap."
