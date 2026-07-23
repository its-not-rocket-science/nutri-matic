"""Deterministic nutrient gap/excess analysis — prompt 3 of the
nutrient-gap recommendation feature (see
docs/nutrient-gap-recommendations.md).

Compares an already-aggregated consumed total (from `aggregation.
aggregate_nutrients` — this module never aggregates anything itself) against
a `nutrient_targets.NutrientTarget`, and classifies the result into one of
six statuses. Never says "deficient" or "excess disease risk" — only
below/near/within/above-preferred/above-upper-limit, framed as position
relative to this app's own reference range, exactly per the feature's
governing rule (see the top of prompts.txt: "must never diagnose a
medical deficiency").

Reuses `aggregation.compute_protein_quality_with_coverage`'s own
philosophy directly: missing data reduces *coverage*, and low coverage
downgrades the result to `insufficient_data` — it never silently treats
an uncovered nutrient as "0 consumed, therefore a huge shortfall". Protein
*quality* (DIAAS/PDCAAS) isn't computed here at all — that's a per-gram-
protein concept with its own coverage-aware machinery
(`compute_protein_quality_with_coverage`); a caller wanting it as a
priority goal reads that directly, rather than this module reimplementing
it as a per-100g nutrient it isn't.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .aggregation import WeightedFood
from .data_quality import is_implausible
from .models import FoodNutrient
from .nutrient_targets import NutrientTarget
from .nutrients import NUTRIENTS, TARGET_TYPE_MAXIMUM_GUIDELINE


class NutrientStatus(str, Enum):
    INSUFFICIENT_DATA = "insufficient_data"
    BELOW_TARGET = "below_target"
    NEAR_TARGET = "near_target"
    WITHIN_TARGET = "within_target"
    ABOVE_PREFERRED = "above_preferred"
    ABOVE_UPPER_LIMIT = "above_upper_limit"


# "near" the target: within this fraction below the preferred figure —
# e.g. 90-100% of target reads as "near", not "below", since a user who's
# at 95% of their fibre target isn't meaningfully short of it.
NEAR_TARGET_BAND = 0.10
# how far above the preferred figure still counts as squarely "within" —
# e.g. up to 150% of a vitamin's RNI is still just "within_target", not
# flagged as an excess worth a warning; beyond that (and short of any
# upper limit) is "above_preferred".
WITHIN_TARGET_ABOVE_BAND = 0.50
# below this fraction of a candidate's mass having a known value for a
# given nutrient, the comparison is judged too unreliable to categorise
# as anything but "insufficient_data" — matches
# aggregation.DEFAULT_MINIMUM_PROTEIN_QUALITY_COVERAGE's spirit (a
# stated bar, not silently accepting any coverage at all).
MINIMUM_COVERAGE_FOR_STATUS = 0.5
# nutrient keys never treated as an optimisation-worthy "gap" to close by
# recommending more food, even though they still get a normal status for
# display — matches the existing app's _find_worst_gap, which already
# excludes energy from "worst gap" hunting (a calorie target isn't a
# shortfall in the same sense a vitamin/mineral one is).
_NEVER_OPTIMISATION_TARGET = {"energy"}


@dataclass(frozen=True)
class NutrientGapResult:
    key: str
    name: str
    unit: str
    # None only when truly nothing is known (coverage is 0) — a real,
    # covered zero is 0.0, never conflated with "unknown".
    consumed_amount: float | None
    # fraction (0-1) of this candidate's total mass that had a known,
    # plausible value for this nutrient — 1.0 whenever every contributing
    # item did. Never itself treated as "confidence in the target" (see
    # `target.confidence` for that, a separate concern).
    coverage: float
    target: NutrientTarget
    status: NutrientStatus
    # target - consumed, only when status is below_target/near_target
    absolute_shortfall: float | None = None
    percent_shortfall: float | None = None
    # consumed - preferred_target, only when status is above_preferred/above_upper_limit
    amount_above_preferred: float | None = None
    # consumed - upper_target, only when status is above_upper_limit
    amount_above_upper_limit: float | None = None
    # 0 unless status is below_target/near_target and this nutrient is
    # optimisation-eligible — how much closing this specific shortfall
    # should matter to a candidate-scoring caller (prompt 4), already
    # scaled by coverage and target confidence. Never negative; prompt 4
    # is what turns this into a signed score contribution alongside its
    # own excess penalties.
    optimisation_weight: float = 0.0
    explanation: str = ""


def _coverage(items: list[WeightedFood], nutrients_by_food_id: dict[int, list[FoodNutrient]], key: str) -> float:
    total_mass = sum(item.quantity_g for item in items)
    if total_mass <= 0:
        return 1.0  # nothing consumed at all — no basis to call this "uncovered" either
    covered_mass = 0.0
    for item in items:
        for fn in nutrients_by_food_id.get(item.food.id, []):
            if fn.nutrient_key == key and not is_implausible(fn.nutrient_key, fn.amount_per_100g):
                covered_mass += item.quantity_g
                break
    return covered_mass / total_mass


def _confidence_multiplier(target: NutrientTarget) -> float:
    """Weaker DRV/UL provenance discounts optimisation_weight rather than
    letting a "secondary_source" figure carry the same weight as a
    "live_confirmed"/"personalized_calculation" one — see nutrients.py's
    own confidence tiers, read here rather than re-judged."""
    return 1.0 if target.confidence in ("live_confirmed", "personalized_calculation") else 0.85


def _status_and_amounts(
    consumed: float, target: NutrientTarget,
) -> tuple[NutrientStatus, float | None, float | None, float | None, float | None]:
    """Returns (status, absolute_shortfall, percent_shortfall,
    amount_above_preferred, amount_above_upper_limit)."""
    if target.target_type == TARGET_TYPE_MAXIMUM_GUIDELINE or target.preferred_target is None:
        # ceiling-only nutrient (or one with no lower/preferred target at
        # all, e.g. optimisation-ineligible) — no shortfall concept applies
        if target.upper_target is not None and consumed > target.upper_target:
            return NutrientStatus.ABOVE_UPPER_LIMIT, None, None, None, consumed - target.upper_target
        return NutrientStatus.WITHIN_TARGET, None, None, None, None

    preferred = target.preferred_target
    if target.upper_target is not None and consumed > target.upper_target:
        return (
            NutrientStatus.ABOVE_UPPER_LIMIT, None, None,
            max(consumed - preferred, 0.0), consumed - target.upper_target,
        )
    if consumed > preferred * (1 + WITHIN_TARGET_ABOVE_BAND):
        return NutrientStatus.ABOVE_PREFERRED, None, None, consumed - preferred, None
    if consumed >= preferred:
        return NutrientStatus.WITHIN_TARGET, None, None, None, None
    if consumed >= preferred * (1 - NEAR_TARGET_BAND):
        shortfall = preferred - consumed
        return NutrientStatus.NEAR_TARGET, shortfall, (shortfall / preferred * 100), None, None
    shortfall = preferred - consumed
    return NutrientStatus.BELOW_TARGET, shortfall, (shortfall / preferred * 100), None, None


def analyse_nutrient_gap(
    key: str,
    consumed_amount: float | None,
    coverage: float,
    target: NutrientTarget,
) -> NutrientGapResult:
    """The pure comparison step — given an already-computed consumed
    amount/coverage and a resolved target, classify it. Split out from
    `analyse_nutrient_gaps` (which does the aggregation bookkeeping) so
    the classification logic itself is trivially unit-testable without a
    database or WeightedFood list at all."""
    nutrient_def = NUTRIENTS.get(key)
    name = target.name
    unit = target.unit

    if consumed_amount is None or coverage < MINIMUM_COVERAGE_FOR_STATUS or not target.optimisation_eligible:
        reason = (
            target.ineligibility_reason
            if not target.optimisation_eligible
            else f"only {coverage:.0%} of consumed mass has known {name} data — too little to compare reliably"
        )
        return NutrientGapResult(
            key=key, name=name, unit=unit, consumed_amount=consumed_amount, coverage=coverage,
            target=target, status=NutrientStatus.INSUFFICIENT_DATA,
            explanation=reason or f"insufficient data to assess {name}",
        )

    status, shortfall, percent_shortfall, above_preferred, above_upper = _status_and_amounts(consumed_amount, target)

    weight = 0.0
    if status in (NutrientStatus.BELOW_TARGET, NutrientStatus.NEAR_TARGET) and key not in _NEVER_OPTIMISATION_TARGET:
        # normalised so a 100%-short nutrient tops out at 1.0 rather than
        # growing unbounded — prompt 3's "cap the value of overcorrecting"
        weight = min(percent_shortfall / 100, 1.0) * coverage * _confidence_multiplier(target)

    explanation = _explain(key, name, unit, consumed_amount, target, status, shortfall, above_preferred, above_upper)

    return NutrientGapResult(
        key=key, name=name, unit=unit, consumed_amount=consumed_amount, coverage=coverage, target=target,
        status=status, absolute_shortfall=shortfall, percent_shortfall=percent_shortfall,
        amount_above_preferred=above_preferred, amount_above_upper_limit=above_upper,
        optimisation_weight=weight, explanation=explanation,
    )


def _explain(
    key: str, name: str, unit: str, consumed: float, target: NutrientTarget, status: NutrientStatus,
    shortfall: float | None, above_preferred: float | None, above_upper: float | None,
) -> str:
    if status == NutrientStatus.BELOW_TARGET:
        return f"{name} is below target by {shortfall:.1f}{unit} — helps close the remaining {name.lower()} gap."
    if status == NutrientStatus.NEAR_TARGET:
        return f"{name} is close to target ({shortfall:.1f}{unit} remaining)."
    if status == NutrientStatus.WITHIN_TARGET:
        return f"{name} is within the target range."
    if status == NutrientStatus.ABOVE_PREFERRED:
        return f"{name} is above the preferred amount by {above_preferred:.1f}{unit}, though not above the upper reference range."
    if status == NutrientStatus.ABOVE_UPPER_LIMIT:
        return f"{name} is above the upper reference range by {above_upper:.1f}{unit}."
    return f"Not enough data to assess {name} reliably."


def analyse_nutrient_gaps(
    items: list[WeightedFood],
    nutrients_by_food_id: dict[int, list[FoodNutrient]],
    totals: dict[str, float],
    target_by_key: dict[str, NutrientTarget],
    *,
    priority_keys: set[str] | None = None,
) -> list[NutrientGapResult]:
    """The full per-nutrient comparison for one meal/day/meal-plan-day/
    multi-day total. `totals` is `aggregation.aggregate_nutrients`'s own
    output (already computed by the caller — this module never
    aggregates); `target_by_key` is one `nutrient_targets.
    resolve_nutrient_target` result per key the caller cares about.

    `priority_keys`, when given, zeroes `optimisation_weight` for every
    key NOT in the set (status/consumed/coverage/explanation are still
    computed and returned for every key — "prioritise", not "hide"). None
    means every optimisation-eligible key keeps its natural weight.
    Protein quality, specifically, isn't a key in `NUTRIENTS` at all — a
    caller prioritising it reads `aggregation.
    compute_protein_quality_with_coverage` directly, not this function.
    """
    results = []
    for key, target in target_by_key.items():
        consumed = totals.get(key)
        coverage = _coverage(items, nutrients_by_food_id, key) if consumed is not None else 0.0
        result = analyse_nutrient_gap(key, consumed, coverage, target)
        if priority_keys is not None and key not in priority_keys:
            result = _zero_weight(result)
        results.append(result)
    return results


def _zero_weight(result: NutrientGapResult) -> NutrientGapResult:
    if result.optimisation_weight == 0.0:
        return result
    return NutrientGapResult(
        key=result.key, name=result.name, unit=result.unit, consumed_amount=result.consumed_amount,
        coverage=result.coverage, target=result.target, status=result.status,
        absolute_shortfall=result.absolute_shortfall, percent_shortfall=result.percent_shortfall,
        amount_above_preferred=result.amount_above_preferred, amount_above_upper_limit=result.amount_above_upper_limit,
        optimisation_weight=0.0, explanation=result.explanation,
    )


def worst_gap(results: list[NutrientGapResult]) -> NutrientGapResult | None:
    """The single highest-weight shortfall — the generalised, multi-
    nutrient-analysis-aware form of routers/diary.py's existing
    `_find_worst_gap` (which picks the lowest raw %DRV). Returns None if
    nothing here has a positive optimisation_weight at all (every tracked
    nutrient is within/above target, or none has enough data/eligibility
    to judge)."""
    candidates = [r for r in results if r.optimisation_weight > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.optimisation_weight)
