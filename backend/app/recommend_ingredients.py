""""Suggest additional ingredients" — prompt 6 of the nutrient-gap
recommendation feature, the first user-facing recommendation mode (see
docs/nutrient-gap-recommendations.md).

Generates candidates from `candidate_metadata.py`'s curated/safe-default
pool (never "every database row" — prompt 5's whole point), hard-filters
by dietary constraints (`dietary_filter`'s `load_constraint_tags`/
`is_hard_excluded` — the same logic `filter_excluded_foods` uses
elsewhere), simulates each one's real before/after effect through
`aggregation.aggregate_nutrients` (never estimated from raw per-100g
content alone, matching `optimizer.py`'s existing convention), and ranks
with `recommendation_scoring.score_candidate`. A candidate that doesn't
clear a positive score is never suggested — "no safe or useful option"
is a real, valid, honestly empty result, not an error.

Public-launch hardening prompt 4: candidate generation used to rank by
raw per-100g nutrient density FIRST and only check practicality
(`candidate_metadata.resolve_candidate_metadata`) and dietary exclusions
AFTER truncating to the top `CANDIDATE_POOL_PER_NUTRIENT`. Since
`resolve_candidate_metadata` is a small curated allowlist (~40 foods) —
everything else, including every branded product, defaults to
`suitable_for_direct_suggestion=False` — the top-N *by raw value* for
almost any nutrient is dominated by exotic/branded/extreme rows that
never had a chance of surviving that later check, while genuinely
useful ordinary candidates (lentils, chickpeas, spinach — moderate,
practical values, rarely the single highest per-100g figure for
anything) never made it into the pool at all. "No safe or useful
addition found" could fire even when practical candidates existed
further down the ranked list. `_candidate_pool` below now applies every
hard-eligibility filter — source (non-branded), data-quality
(`is_implausible`), dietary exclusion, and direct-suggestion
practicality — to an over-fetched window BEFORE truncating to the final
pool size, so the top N kept are the top N *eligible* ones, not the top
N *overall* with eligibility checked too late to matter. See
docs/recommendation-candidates.md for the full documented filter order
and the query-count/performance bound this keeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_nutrients
from .candidate_metadata import is_plausible_serving, resolve_candidate_metadata
from .carbon_footprint import carbon_tier_for_food
from .data_quality import is_implausible
from .dietary_filter import food_dietary_status, is_hard_excluded, load_constraint_tags
from .glycaemic_load import GlycaemicClassification, glycaemic_classification_for_food
from .goals import goal_keys_of, goal_priority_weight
from .models import Food, FoodNutrient, Profile
from .nutrient_gap_analysis import NutrientStatus, analyse_nutrient_gaps
from .nutrient_targets import AnalysisPeriod, NutrientTarget, adjust_target_for_remaining, resolve_nutrient_target
from .nutrients import NUTRIENTS
from .recommendation_scoring import PracticalityInput, ScoreBreakdown, ScoringWeights, score_candidate

# How many eligible candidates to keep per shortfall nutrient — a
# shortlist, not "every food carrying this nutrient" (same shape as the
# existing _rank_foods_by_nutrient in routers/diary.py, generalised to
# more than one nutrient at once).
CANDIDATE_POOL_PER_NUTRIENT = 12
# How many rows to over-fetch (by raw amount_per_100g, descending) before
# narrowing to eligible ones — a fixed multiple of CANDIDATE_POOL_PER_
# NUTRIENT, not a fraction of the catalogue, so query cost stays bounded
# regardless of how large the ingested FDC catalogue grows. Generous
# enough that a shortfall nutrient with real, practical whole-food
# sources almost always yields a full pool even though most of the
# window is filtered out (branded/exotic/implausible rows are common
# among the highest raw values for many nutrients).
CANDIDATE_FETCH_MULTIPLIER = 25
# How many CANDIDATE_FETCH_MULTIPLIER-sized pages to page through, at
# most, before giving up on a shortfall nutrient — real "over-fetch/
# refill" (prompt 4 item 1's own wording) rather than one fixed-size
# window: a page that's still short after every filter tries the next
# page, up to this cap, instead of accepting "not enough eligible rows
# in the first window" as final. Still a small constant number of
# queries per nutrient (bounded, independent of catalogue size), just a
# constant greater than one.
CANDIDATE_FETCH_MAX_PAGES = 4
DEFAULT_MAX_SUGGESTIONS = 2
# Caught by PR review: with no priority_nutrient_keys given, an empty day
# (see treat_empty_day_as_zero on analyse_nutrient_gaps) now registers
# every optimisation-eligible nutrient — dozens of them — as a shortfall
# at once, where before an empty day short-circuited to no shortfalls at
# all. Each one costs _candidate_pool up to CANDIDATE_FETCH_MAX_PAGES
# real paginated queries; unbounded, a brand-new user's very first
# request (the single most common way to hit an empty day) could issue
# well over a hundred large SQL queries. Ranked by optimisation_weight
# (real, not arbitrary — the same signal _candidate_pool's own candidates
# are later scored against) and capped here, before pooling, rather than
# discovered too late to matter.
MAX_SHORTFALL_KEYS_FOR_POOLING = 10


class NoSuggestionReason(str, Enum):
    """Public-launch hardening prompt 4 item 6: a stable reason code for why suggestions came
    back empty, distinct from the human-readable text — same split this
    codebase already uses for recommendation_safety's disabled_reason/
    disabled_reason_code."""

    # nothing tracked is below/near target — there's no gap to close
    NO_SHORTFALL = "no_shortfall"
    # every shortfall nutrient's candidate window (after over-fetching)
    # had no food that was simultaneously non-branded, plausible,
    # dietarily eligible, and practical as a direct suggestion
    NO_ELIGIBLE_CANDIDATES = "no_eligible_candidates"
    # every eligible candidate would have exceeded max_additional_energy
    ENERGY_LIMIT = "energy_limit"
    # eligible, energy-permitted candidates existed but none scored above
    # zero (covers low data coverage, meal-type mismatch, and candidates
    # that just didn't move the needle enough to be worth suggesting)
    NO_MEANINGFUL_IMPROVEMENT = "no_meaningful_improvement"


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
    # USDA FoodData Central id, None for a manually-entered food — a
    # stable cross-reference identifier, not this app's own nutritional
    # truth (hardening prompt 4)
    fdc_id: int | None
    # "sr_legacy_food" | "foundation_food" | "branded_food" | None — same
    # raw provenance tag Food.data_type already carries
    data_type: str | None
    # candidate_metadata.CandidateMetadata.source — "curated" or
    # "category_default" (never "unknown_excluded": those never reach a
    # suggestion at all). This module's own analogue of a "mapping
    # relationship": a direct food suggestion involves no ingredient-
    # alias matching at all (that system is stock-recipe-ingredient-
    # specific, see recommendation_provenance.py), so "how confidently
    # was this candidate identified as a sensible standalone suggestion"
    # is answered by candidate_metadata's curation tier instead.
    candidate_source: str
    explanation: str


@dataclass(frozen=True)
class RejectedCandidate:
    food_name: str
    reason: str
    reason_code: str | None = None


@dataclass(frozen=True)
class IngredientSuggestionResult:
    suggestions: list[IngredientSuggestion]
    rejected: list[RejectedCandidate] = field(default_factory=list)
    no_suggestion_reason: NoSuggestionReason | None = None


def _candidate_pool(
    db: Session, target_keys: list[str], excluded_food_ids: set[int], profile: Profile,
    meal_type: str | None = None,
) -> tuple[list[Food], list[RejectedCandidate]]:
    """Documented filter order (public-launch hardening prompt 4 item 2), applied to an
    over-fetched window BEFORE truncating to CANDIDATE_POOL_PER_NUTRIENT,
    not after — see this module's docstring for why applying these too
    late let impractical rows starve out practical ones:

    1. visibility/source eligibility — non-branded only, pushed into the
       SQL filter itself (resolve_candidate_metadata excludes every
       branded product unconditionally regardless of name, so there's no
       reason to even fetch one).
    2. data-quality eligibility — data_quality.is_implausible.
    3. dietary exclusions — the same is_hard_excluded logic
       filter_excluded_foods uses, with constraint tags loaded once per
       call rather than once per nutrient key (bounded query count).
    4. direct-suggestion practicality — candidate_metadata.
       resolve_candidate_metadata(...).suitable_for_direct_suggestion.

    "Nutrient relevance" (item 2's 5th stage) falls out of the SQL
    ordering itself: rows are fetched highest-amount_per_100g-first, and
    the first CANDIDATE_POOL_PER_NUTRIENT to pass every filter above are
    kept — the top N *eligible* candidates, in nutrient-density order,
    not the top N overall with eligibility checked too late to matter.
    Scoring/tie-breaking (item 2's last stage) happens in the caller,
    same as before.

    "Over-fetches/refills until a sufficient number of practical
    candidates survive" (item 1's own wording): a single fixed-size
    over-fetch isn't actually that — if every row in that one window is
    ineligible, the pool still comes up short even though eligible rows
    exist further down. Paginates in bounded pages instead (up to
    CANDIDATE_FETCH_MAX_PAGES), stopping as soon as
    CANDIDATE_POOL_PER_NUTRIENT eligible candidates are found or a page
    comes back short (nothing further to fetch for this nutrient) —
    still a small constant number of queries per shortfall key, not
    unbounded, but a real refill rather than one fixed-size guess.

    A food rejected for an implausible/dietary/impractical/meal-type
    reason on one nutrient's row is only added to `seen_ids` — and so
    excluded from every later nutrient's consideration — when the
    reason is a property of the FOOD itself (dietary exclusion,
    practicality, meal-type: all invariant across which nutrient
    triggered the check). An implausible VALUE is specific to that one
    (food, nutrient) row (`is_implausible` takes both) — a food with a
    corrupted zinc measurement can still have perfectly good, useful
    iron data, and must still be considered when iron is the shortfall
    being evaluated.

    Bounded query count/runtime (item 4): at most CANDIDATE_FETCH_MAX_
    PAGES FoodNutrient+Food queries per shortfall key (each capped at
    CANDIDATE_POOL_PER_NUTRIENT * CANDIDATE_FETCH_MULTIPLIER rows),
    regardless of catalogue size, plus one constraint-tags query total
    (not per key).
    """
    seen_ids = set(excluded_food_ids)
    candidates: list[Food] = []
    rejected: list[RejectedCandidate] = []
    constraint_tags = load_constraint_tags(db, profile)
    page_size = CANDIDATE_POOL_PER_NUTRIENT * CANDIDATE_FETCH_MULTIPLIER

    for key in target_keys:
        kept_for_key = 0
        for page in range(CANDIDATE_FETCH_MAX_PAGES):
            if kept_for_key >= CANDIDATE_POOL_PER_NUTRIENT:
                break
            rows = (
                db.query(FoodNutrient, Food)
                .join(Food, FoodNutrient.food_id == Food.id)
                .filter(
                    FoodNutrient.nutrient_key == key,
                    or_(Food.data_type.is_(None), Food.data_type != "branded_food"),
                )
                .order_by(FoodNutrient.amount_per_100g.desc())
                .offset(page * page_size)
                .limit(page_size)
                .all()
            )
            if not rows:
                break  # nothing further to fetch for this nutrient at all

            for fn, food in rows:
                if kept_for_key >= CANDIDATE_POOL_PER_NUTRIENT:
                    break
                if food.id in seen_ids:
                    continue
                if is_implausible(fn.nutrient_key, fn.amount_per_100g):
                    # food-level seen_ids is NOT set here — see docstring
                    rejected.append(RejectedCandidate(food.name, "implausible source value", "implausible_value"))
                    continue
                if is_hard_excluded(food, profile.dietary_pattern if profile else None, constraint_tags):
                    rejected.append(
                        RejectedCandidate(food.name, "excluded by dietary constraints", "dietary_exclusion")
                    )
                    seen_ids.add(food.id)
                    continue
                metadata = resolve_candidate_metadata(food)
                if not metadata.suitable_for_direct_suggestion:
                    rejected.append(
                        RejectedCandidate(food.name, "not suitable for a direct standalone suggestion", "impractical")
                    )
                    seen_ids.add(food.id)
                    continue
                if (
                    meal_type is not None and metadata.suitable_meal_types
                    and meal_type not in metadata.suitable_meal_types
                ):
                    rejected.append(
                        RejectedCandidate(food.name, f"not typically suited to {meal_type}", "meal_type_mismatch")
                    )
                    seen_ids.add(food.id)
                    continue
                candidates.append(food)
                seen_ids.add(food.id)
                kept_for_key += 1

            if len(rows) < page_size:
                break  # short page — exhausted this nutrient's rows

    return candidates, rejected


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
    # carbon_tier_for_food/glycaemic_tier_for_food are only ever consulted
    # when the profile has actually chosen the matching goal — an inactive
    # goal must not silently nudge ranking for a profile that never asked
    # for it, and the nudge itself is scaled by that goal's own priority
    # rank, not applied at flat full strength (see
    # recommendation_scoring.score_candidate's carbon_tier docstring and
    # goals.goal_priority_weight).
    goal_keys = goal_keys_of(profile)
    carbon_priority_weight = goal_priority_weight(goal_keys, "reduce_carbon_footprint")
    glycaemic_priority_weight = goal_priority_weight(goal_keys, "blood_sugar_stability")

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
        treat_empty_day_as_zero=True,
    )
    shortfall_gaps = [
        g for g in before_gaps
        if g.status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET)
        and (priority_nutrient_keys is None or g.key in priority_nutrient_keys)
    ]
    if not shortfall_gaps:
        return IngredientSuggestionResult(suggestions=[], no_suggestion_reason=NoSuggestionReason.NO_SHORTFALL)
    shortfall_gaps.sort(key=lambda g: g.optimisation_weight, reverse=True)
    shortfall_keys = [g.key for g in shortfall_gaps[:MAX_SHORTFALL_KEYS_FOR_POOLING]]

    pool, rejected = _candidate_pool(db, shortfall_keys, excluded_food_ids, profile, meal_type=meal_type)
    if not pool:
        return IngredientSuggestionResult(
            suggestions=[], rejected=rejected, no_suggestion_reason=NoSuggestionReason.NO_ELIGIBLE_CANDIDATES,
        )

    scored: list[IngredientSuggestion] = []
    working_nutrients_by_food_id = dict(nutrients_by_food_id)

    for food in pool:
        # Eligibility (source, data-quality, dietary, practicality,
        # meal-type) was already decided in _candidate_pool — every food
        # reaching this loop has already passed all of it. metadata is
        # just recomputed here (cheap, pure Python) for its
        # serving/kind/source fields.
        metadata = resolve_candidate_metadata(food)
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
            treat_empty_day_as_zero=True,
        )

        energy_added = after_totals.get("energy", 0.0) - before_totals.get("energy", 0.0)
        if max_additional_energy is not None and energy_added > max_additional_energy:
            rejected.append(
                RejectedCandidate(
                    food.name, f"would add {energy_added:.0f}kcal, above the requested cap", "energy_limit"
                )
            )
            continue

        suitability = food_dietary_status(food, db, profile)
        coverage = _candidate_data_coverage(food, candidate_rows, shortfall_keys)
        practicality = PracticalityInput(is_plausible_serving=is_plausible_serving(metadata, trial_quantity))
        # "name_match" — these are always resolved from the candidate's
        # own name (never a proxy), unlike recipe/pair/substitution
        # candidates — see recommendation_scoring.ClassificationProvenance.
        carbon_tier = carbon_tier_for_food(food.name) if carbon_priority_weight is not None else None
        glycaemic_classification = (
            glycaemic_classification_for_food(food.name) if glycaemic_priority_weight is not None
            else GlycaemicClassification(tier=None, basis=None)
        )

        score = score_candidate(
            before_gaps, after_gaps, energy_added=energy_added, max_additional_energy=max_additional_energy,
            dietary_suitability=suitability, candidate_data_coverage=coverage, practicality=practicality,
            carbon_tier=carbon_tier, carbon_priority_weight=carbon_priority_weight or 1.0,
            carbon_provenance="name_match" if carbon_tier is not None else None,
            glycaemic_tier=glycaemic_classification.tier, glycaemic_priority_weight=glycaemic_priority_weight or 1.0,
            glycaemic_provenance="name_match" if glycaemic_classification.tier is not None else None,
            glycaemic_basis=glycaemic_classification.basis,
            weights=weights,
        )
        if score.total <= 0:
            rejected.append(
                RejectedCandidate(food.name, "did not meaningfully improve the current gaps", "no_improvement")
            )
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
            fdc_id=food.fdc_id, data_type=food.data_type, candidate_source=metadata.source,
            explanation=_explain(food.name, trial_quantity, score),
        ))

    # deterministic ordering: score desc, then food name — never left to
    # whatever order the DB/dict iteration happened to return
    scored.sort(key=lambda s: (-s.score.total, s.food_name))

    no_suggestion_reason = None
    if not scored:
        # every candidate that reached this loop already passed pool
        # eligibility — if every one of THOSE was rejected specifically
        # for the energy cap, that's the one actionable reason; anything
        # more mixed (meal-type/low-coverage/no-improvement) collapses to
        # the general "nothing scored" reason rather than overclaiming a
        # single specific cause.
        loop_rejections = [r for r in rejected if r.reason_code in ("energy_limit", "no_improvement")]
        if loop_rejections and all(r.reason_code == "energy_limit" for r in loop_rejections):
            no_suggestion_reason = NoSuggestionReason.ENERGY_LIMIT
        else:
            no_suggestion_reason = NoSuggestionReason.NO_MEANINGFUL_IMPROVEMENT

    return IngredientSuggestionResult(
        suggestions=scored[:max_suggestions], rejected=rejected, no_suggestion_reason=no_suggestion_reason,
    )


def _explain(food_name: str, quantity_g: float, score: ScoreBreakdown) -> str:
    if not score.nutrients_improved:
        return f"Adding {quantity_g:.0f}g of {food_name}."
    nutrients = ", ".join(NUTRIENTS[k].name for k in score.nutrients_improved if k in NUTRIENTS)
    return f"Adding {quantity_g:.0f}g of {food_name} helps close the remaining {nutrients} gap."
