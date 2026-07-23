""""Two-item combination optimiser" — prompt 9 of the nutrient-gap
recommendation feature (see docs/nutrient-gap-recommendations.md).

Deliberately NOT unrestricted combinatorial search: a pair is only ever
considered if `candidate_metadata.py`'s own practical metadata already
supports it (one candidate is a condiment/spread — `normally_added_to_
another_meal` — paired with a non-condiment base, e.g. peanut butter on
toast) or the specific pair is named in `CURATED_PAIRS` below (yoghurt +
berries, lentils + spinach — real, common combinations, not inferred from
nutrient math alone). Candidate pool size and total pair evaluations are
both hard-bounded (`MAX_PAIR_EVALUATIONS`) regardless of how large the
underlying shortfall candidate pool is — see `test_recommend_pairs.py`'s
performance test for the actual bound enforced.

The pair is scored as one candidate (`recommendation_scoring.
score_candidate` on the *combined* before/after gaps), not as the sum of
each food's independently-computed score — two foods that individually
look great can still combine badly (same nutrient's excess doubled,
combined energy blowing the cap), and only scoring the actual combined
effect catches that. Each food's own solo contribution is also computed
and returned alongside, for transparency, but never used as the ranking
score itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_nutrients
from .candidate_metadata import curated_key_for, is_plausible_serving, resolve_candidate_metadata
from .data_quality import is_implausible
from .dietary_filter import filter_excluded_foods, food_dietary_status
from .models import Food, FoodNutrient, Profile
from .nutrient_gap_analysis import NutrientStatus, analyse_nutrient_gaps
from .nutrient_targets import AnalysisPeriod, NutrientTarget, adjust_target_for_remaining, resolve_nutrient_target
from .nutrients import NUTRIENTS
from .recommendation_scoring import PracticalityInput, ScoreBreakdown, ScoringWeights, score_candidate

# hard bound on the candidate pool considered for pairing at all (a small
# shortlist, same shape as recommend_ingredients' own pool) — pairs are
# only ever formed *within* this pool, never against the wider catalog
CANDIDATE_POOL_SIZE = 12
# hard bound on how many actual (food, food) combinations get simulated —
# with an allowed-pairing gate this is normally far smaller than
# CANDIDATE_POOL_SIZE choose 2, but this is the real, enforced ceiling
# regardless of pool size or how many curated/condiment pairs match
MAX_PAIR_EVALUATIONS = 40
DEFAULT_MAX_SUGGESTIONS = 2

# real, common combinations — curated the same way CURATED_FOODS itself
# is, not inferred from nutrient content. Order within each pair doesn't
# matter (checked both ways).
CURATED_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"yogurt, greek", "strawberries, raw"}),
    frozenset({"yogurt, greek", "blueberries, raw"}),
    frozenset({"cottage cheese", "strawberries, raw"}),
    frozenset({"lentils", "spinach, raw"}),
    frozenset({"oats", "blueberries, raw"}),
    frozenset({"oats", "walnuts"}),
    frozenset({"oats", "almonds"}),
})


@dataclass(frozen=True)
class PairContribution:
    food_id: int
    food_name: str
    quantity_g: float
    solo_score: float  # this food's own score, added alone (for comparison — never the ranking metric)


@dataclass(frozen=True)
class PairSuggestion:
    first: PairContribution
    second: PairContribution
    combined_energy_kcal: float
    score: ScoreBreakdown  # the COMBINED pair's score — this is what suggestions are ranked by
    nutrients_improved: list[str]
    remaining_shortfalls: list[str]
    new_warnings: list[str]
    explanation: str


@dataclass(frozen=True)
class RejectedPair:
    first_name: str
    second_name: str
    reason: str


@dataclass(frozen=True)
class PairSuggestionResult:
    suggestions: list[PairSuggestion]
    rejected: list[RejectedPair] = field(default_factory=list)
    pairs_evaluated: int = 0


def _pair_allowed(food_a: Food, meta_a, food_b: Food, meta_b) -> bool:
    """Practical-metadata rule (a condiment paired with a non-condiment
    base) or an explicit curated pair — never a nutrient-math-only
    justification for combining two foods nobody would actually eat
    together."""
    if meta_a.normally_added_to_another_meal != meta_b.normally_added_to_another_meal:
        return True  # exactly one is a spread/condiment-style add-on
    key_a, key_b = curated_key_for(food_a), curated_key_for(food_b)
    if key_a is not None and key_b is not None and frozenset({key_a, key_b}) in CURATED_PAIRS:
        return True
    return False


def _candidate_pool(db: Session, target_keys: list[str], excluded_food_ids: set[int]) -> list[Food]:
    seen_ids = set(excluded_food_ids)
    candidates: list[Food] = []
    for key in target_keys:
        rows = (
            db.query(FoodNutrient)
            .filter(FoodNutrient.nutrient_key == key)
            .order_by(FoodNutrient.amount_per_100g.desc())
            .limit(CANDIDATE_POOL_SIZE * 5)
            .all()
        )
        rows = [r for r in rows if not is_implausible(r.nutrient_key, r.amount_per_100g)][:CANDIDATE_POOL_SIZE]
        new_ids = [r.food_id for r in rows if r.food_id not in seen_ids]
        if not new_ids:
            continue
        for food in db.query(Food).filter(Food.id.in_(new_ids)).all():
            if food.id not in seen_ids:
                candidates.append(food)
                seen_ids.add(food.id)
        if len(candidates) >= CANDIDATE_POOL_SIZE:
            break
    return candidates[:CANDIDATE_POOL_SIZE]


def suggest_pairs(
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
    day_count: int = 1,
    already_consumed_by_key: dict[str, float] | None = None,
    weights: ScoringWeights | None = None,
) -> PairSuggestionResult:
    excluded_food_ids = excluded_food_ids or set()
    weights = weights or ScoringWeights()

    before_totals = aggregate_nutrients(items, nutrients_by_food_id)
    target_by_key: dict[str, NutrientTarget] = {}
    for key in NUTRIENTS:
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
        return PairSuggestionResult(suggestions=[])

    pool = _candidate_pool(db, shortfall_keys, excluded_food_ids)
    pool = filter_excluded_foods(pool, db, profile)
    metadata_by_id = {f.id: resolve_candidate_metadata(f) for f in pool}
    pool = [f for f in pool if metadata_by_id[f.id].suitable_for_direct_suggestion]
    if len(pool) < 2:
        return PairSuggestionResult(suggestions=[])

    working_nutrients_by_food_id = dict(nutrients_by_food_id)
    missing_food_ids = [f.id for f in pool if f.id not in working_nutrients_by_food_id]
    if missing_food_ids:
        for row in db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(missing_food_ids)).all():
            working_nutrients_by_food_id.setdefault(row.food_id, []).append(row)

    allowed_pairs = [
        (a, b) for a, b in combinations(pool, 2)
        if _pair_allowed(a, metadata_by_id[a.id], b, metadata_by_id[b.id])
    ][:MAX_PAIR_EVALUATIONS]

    rejected: list[RejectedPair] = []
    scored: list[PairSuggestion] = []
    solo_score_cache: dict[int, float] = {}

    def solo_score(food: Food, quantity_g: float) -> float:
        if food.id in solo_score_cache:
            return solo_score_cache[food.id]
        trial = items + [WeightedFood(food, quantity_g)]
        totals = aggregate_nutrients(trial, working_nutrients_by_food_id)
        gaps = analyse_nutrient_gaps(trial, working_nutrients_by_food_id, totals, target_by_key, priority_keys=priority_nutrient_keys)
        energy_added = totals.get("energy", 0.0) - before_totals.get("energy", 0.0)
        suitability = food_dietary_status(food, db, profile)
        result = score_candidate(
            before_gaps, gaps, energy_added=energy_added, max_additional_energy=max_additional_energy,
            dietary_suitability=suitability, weights=weights,
        ).total
        solo_score_cache[food.id] = result
        return result

    for food_a, food_b in allowed_pairs:
        qty_a = metadata_by_id[food_a.id].serving.default_g
        qty_b = metadata_by_id[food_b.id].serving.default_g
        trial_items = items + [WeightedFood(food_a, qty_a), WeightedFood(food_b, qty_b)]
        after_totals = aggregate_nutrients(trial_items, working_nutrients_by_food_id)
        after_gaps = analyse_nutrient_gaps(
            trial_items, working_nutrients_by_food_id, after_totals, target_by_key, priority_keys=priority_nutrient_keys,
        )

        combined_energy = after_totals.get("energy", 0.0) - before_totals.get("energy", 0.0)
        if max_additional_energy is not None and combined_energy > max_additional_energy:
            rejected.append(RejectedPair(food_a.name, food_b.name, f"combined would add {combined_energy:.0f}kcal, above the requested cap"))
            continue
        if any(
            g.status == NutrientStatus.ABOVE_UPPER_LIMIT
            and next((bg.status for bg in before_gaps if bg.key == g.key), None) != NutrientStatus.ABOVE_UPPER_LIMIT
            for g in after_gaps
        ):
            rejected.append(RejectedPair(food_a.name, food_b.name, "combination would push a nutrient newly above its upper limit"))
            continue

        suitability_a = food_dietary_status(food_a, db, profile)
        suitability_b = food_dietary_status(food_b, db, profile)
        worst_suitability = suitability_a if (suitability_a and suitability_a.status != "ok") else suitability_b

        both_servings_plausible = (
            is_plausible_serving(metadata_by_id[food_a.id], qty_a)
            and is_plausible_serving(metadata_by_id[food_b.id], qty_b)
        )

        score = score_candidate(
            before_gaps, after_gaps, energy_added=combined_energy, max_additional_energy=max_additional_energy,
            dietary_suitability=worst_suitability,
            practicality=PracticalityInput(is_plausible_serving=both_servings_plausible),
            weights=weights,
        )
        if score.total <= 0:
            rejected.append(RejectedPair(food_a.name, food_b.name, "combination did not meaningfully improve the current gaps"))
            continue

        after_by_key = {g.key: g for g in after_gaps}
        remaining = [
            k for k in shortfall_keys
            if after_by_key.get(k) and after_by_key[k].status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        ]
        new_warnings = [g.key for g in after_gaps if g.key in score.nutrients_worsened]

        scored.append(PairSuggestion(
            first=PairContribution(food_a.id, food_a.name, qty_a, solo_score(food_a, qty_a)),
            second=PairContribution(food_b.id, food_b.name, qty_b, solo_score(food_b, qty_b)),
            combined_energy_kcal=combined_energy, score=score, nutrients_improved=score.nutrients_improved,
            remaining_shortfalls=remaining, new_warnings=new_warnings,
            explanation=_explain(food_a.name, food_b.name, score),
        ))

    scored.sort(key=lambda s: (-s.score.total, s.first.food_name, s.second.food_name))
    return PairSuggestionResult(
        suggestions=scored[:max_suggestions], rejected=rejected, pairs_evaluated=len(allowed_pairs),
    )


def _explain(name_a: str, name_b: str, score: ScoreBreakdown) -> str:
    if not score.nutrients_improved:
        return f"Adding {name_a} with {name_b}."
    nutrients = ", ".join(NUTRIENTS[k].name for k in score.nutrients_improved if k in NUTRIENTS)
    return f"Adding {name_a} with {name_b} together helps close the remaining {nutrients} gap."
