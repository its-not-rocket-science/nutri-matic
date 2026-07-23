"""Profile- and period-aware nutrient target resolution — prompt 2 of the
nutrient-gap recommendation feature (see
docs/nutrient-gap-recommendations.md for the audit this builds on).

Generalises `nutrients.resolve_drv`/`energy_goal.calculate_energy_target`/
`protein_requirement.calculate_protein_target_g` (each already profile-
aware, but implicitly "for one day" with no shared shape) to three
explicit analysis periods — meal, day, multi-day — and adds the
target-*shape* metadata plain %DRV comparison doesn't carry: whether a
figure is something to reach, a ceiling to stay under, or has no
optimisation target at all, plus a tolerable-upper-limit figure where one
is confidently known (see `nutrients.NutrientDef.upper_limit`).

This module resolves *targets only* — it never looks at what's actually
been consumed. That's `nutrient_gap_analysis.py`'s job (prompt 3), which
consumes `NutrientTarget` as the comparison side of its output. Keeping
them separate means a target can be resolved (and unit-tested) without a
diary/meal-plan entry existing at all.

Never diagnoses: every value here is paired with real source/confidence
provenance (reusing the exact fields `nutrients.NutrientDef` already
carries, not a parallel copy), and a nutrient this app has no
confidently-sourced target for returns `None`/`optimisation_eligible=False`
with a stated reason, never an invented number. Nothing here uses the
word "deficient" or "excess" — see `nutrient_gap_analysis.py` for the
below/near/within/above vocabulary actually used once a real consumed
amount is compared against these targets.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from .energy_goal import calculate_energy_target
from .models import Profile
from .nutrients import (
    NUTRIENTS,
    TARGET_TYPE_MAXIMUM_GUIDELINE,
    TARGET_TYPE_PERSONALIZED,
    DRVProfile,
    resolve_drv,
    resolve_upper_limit,
)
from .protein_requirement import calculate_protein_target_g


class AnalysisPeriod(str, Enum):
    MEAL = "meal"
    DAY = "day"
    MULTI_DAY = "multi_day"


@dataclass(frozen=True)
class NutrientTarget:
    key: str
    name: str
    unit: str
    # nutrients.TARGET_TYPE_* — what kind of claim this target makes
    target_type: str
    # the RNI/AI-style "reach at least this" figure — None for a ceiling-
    # only (TARGET_TYPE_MAXIMUM_GUIDELINE), ineligible, or unresolvable
    # target
    lower_target: float | None
    # this app doesn't track a distinct "ideal, above the minimum" figure
    # separate from the RNI/AI itself, so preferred_target currently always
    # equals lower_target where both apply — kept as its own field per the
    # prompt's schema, and so a nutrient that genuinely gains a distinct
    # preferred figure later doesn't need a shape change.
    preferred_target: float | None
    # a tolerable upper limit (most nutrients) or the ceiling itself, for
    # TARGET_TYPE_MAXIMUM_GUIDELINE nutrients where the "target" IS the
    # ceiling (sodium, saturated fat) — None wherever no figure is
    # confidently known, never fabricated
    upper_target: float | None
    # True only when this specific result was actually multiplied by a
    # multi-day day_count — a flat one-day figure (meal/day periods, or a
    # multi-day nutrient this app has no scaling basis for) is False
    scales_with_period: bool
    source: str | None
    confidence: str | None
    upper_source: str | None = None
    upper_confidence: str | None = None
    optimisation_eligible: bool = True
    ineligibility_reason: str | None = None
    # True only for "energy", when the target reflects a weight-loss goal's
    # calorie deficit rather than plain maintenance — see energy_goal.py
    goal_adjusted: bool = False


_ENERGY_SOURCE = "Personalized target: Mifflin-St Jeor BMR x activity level (see energy.py)"
_ENERGY_DEFICIT_SOURCE = (
    "Personalized target: Mifflin-St Jeor BMR x activity level, minus a weight-loss-goal "
    "calorie deficit (see energy_goal.py)"
)
_PROTEIN_SOURCE = "Personalized target: bodyweight x activity-level protein factor (see protein_requirement.py)"
_PERSONALIZED_CONFIDENCE = "personalized_calculation"


def _profile_key(profile: Profile) -> DRVProfile:
    return (profile.sex, profile.is_pregnant, profile.is_lactating)


def resolve_nutrient_target(
    key: str, profile: Profile, period: AnalysisPeriod, *, day_count: int = 1,
) -> NutrientTarget | None:
    """The target for one nutrient, for one profile, over one analysis
    period.

    `day_count` only matters for `MULTI_DAY` (how many days the plan
    spans) — MEAL/DAY always resolve "one day's worth" as a flat figure;
    a meal is never automatically treated as a fraction of the day (see
    `resolve_meal_comparison_target` for the actual, explicit
    remaining-daily/share-of-daily machinery prompt section 2 asks for).

    Missing consumed data is not this function's concern at all — it
    returns a target or it doesn't; `nutrient_gap_analysis.py` is what
    turns "missing consumed amount" into a coverage/confidence signal.

    Returns `None` only if `key` isn't a tracked nutrient at all. Every
    *tracked* nutrient — even one with no optimisation target — still
    gets a `NutrientTarget` (lower/preferred/upper all `None`,
    `optimisation_eligible=False`, a stated reason), so a caller can
    always show *something* for every nutrient it has consumed data for,
    never silently drop one.
    """
    nutrient_def = NUTRIENTS.get(key)
    if nutrient_def is None:
        return None

    scale = day_count if period == AnalysisPeriod.MULTI_DAY else 1
    scales_with_period = scale != 1

    if nutrient_def.target_type == TARGET_TYPE_PERSONALIZED:
        return _resolve_personalized_target(key, nutrient_def, profile, scale, scales_with_period)

    drv_profile = _profile_key(profile)
    upper = resolve_upper_limit(key, drv_profile)
    upper_scaled = upper * scale if upper is not None else None

    if nutrient_def.target_type == TARGET_TYPE_MAXIMUM_GUIDELINE:
        # the ceiling itself may live in `drv` (saturated_fat, which
        # already had a real figure there before this module existed) or
        # in `upper_limit` (sodium, whose `drv` is deliberately left at 0
        # for backward compatibility — see nutrients.py) — try drv first
        # since a nutrient wouldn't set both.
        ceiling = resolve_drv(key, drv_profile)
        ceiling = ceiling * scale if ceiling is not None else upper_scaled
        return NutrientTarget(
            key=key, name=nutrient_def.name, unit=nutrient_def.unit, target_type=nutrient_def.target_type,
            lower_target=None, preferred_target=None, upper_target=ceiling,
            scales_with_period=scales_with_period,
            source=nutrient_def.drv_source or nutrient_def.upper_limit_source,
            confidence=nutrient_def.drv_confidence or nutrient_def.upper_limit_confidence,
            upper_source=nutrient_def.upper_limit_source, upper_confidence=nutrient_def.upper_limit_confidence,
            optimisation_eligible=nutrient_def.optimisation_eligible,
            ineligibility_reason=nutrient_def.ineligibility_reason,
        )

    if not nutrient_def.optimisation_eligible:
        return NutrientTarget(
            key=key, name=nutrient_def.name, unit=nutrient_def.unit, target_type=nutrient_def.target_type,
            lower_target=None, preferred_target=None, upper_target=upper_scaled,
            scales_with_period=scales_with_period,
            source=nutrient_def.drv_source, confidence=nutrient_def.drv_confidence,
            upper_source=nutrient_def.upper_limit_source, upper_confidence=nutrient_def.upper_limit_confidence,
            optimisation_eligible=False,
            ineligibility_reason=nutrient_def.ineligibility_reason or nutrient_def.drv_source,
        )

    drv = resolve_drv(key, drv_profile)
    drv_scaled = drv * scale if drv is not None else None
    return NutrientTarget(
        key=key, name=nutrient_def.name, unit=nutrient_def.unit, target_type=nutrient_def.target_type,
        lower_target=drv_scaled, preferred_target=drv_scaled, upper_target=upper_scaled,
        scales_with_period=scales_with_period,
        source=nutrient_def.drv_source, confidence=nutrient_def.drv_confidence,
        upper_source=nutrient_def.upper_limit_source, upper_confidence=nutrient_def.upper_limit_confidence,
        optimisation_eligible=drv is not None,
        ineligibility_reason=None if drv is not None else "no DRV established for this profile",
    )


def _resolve_personalized_target(
    key: str, nutrient_def, profile: Profile, scale: float, scales_with_period: bool,
) -> NutrientTarget:
    if key == "energy":
        result = calculate_energy_target(profile)
        target, goal_adjusted = result if result is not None else (None, False)
        return NutrientTarget(
            key=key, name=nutrient_def.name, unit=nutrient_def.unit, target_type=nutrient_def.target_type,
            lower_target=None, preferred_target=(target * scale) if target is not None else None,
            upper_target=None, scales_with_period=scales_with_period,
            source=_ENERGY_DEFICIT_SOURCE if goal_adjusted else _ENERGY_SOURCE,
            confidence=_PERSONALIZED_CONFIDENCE,
            optimisation_eligible=target is not None,
            ineligibility_reason=None if target is not None else "profile incomplete — see energy.calculate_eer",
            goal_adjusted=goal_adjusted,
        )
    if key == "protein":
        target = calculate_protein_target_g(profile)
        return NutrientTarget(
            key=key, name=nutrient_def.name, unit=nutrient_def.unit, target_type=nutrient_def.target_type,
            lower_target=None, preferred_target=(target * scale) if target is not None else None,
            upper_target=None, scales_with_period=scales_with_period,
            source=_PROTEIN_SOURCE, confidence=_PERSONALIZED_CONFIDENCE,
            optimisation_eligible=target is not None,
            ineligibility_reason=None if target is not None else "profile incomplete — see protein_requirement.py",
        )
    raise AssertionError(f"unhandled personalized nutrient key: {key!r}")  # pragma: no cover


@dataclass(frozen=True)
class MealComparisonTarget:
    """What a *meal's* consumed amount of one nutrient should actually be
    compared against — distinct from the plain day-level `NutrientTarget`,
    since a meal's target is never automatically one-third of the day's
    (see comparison_mode)."""

    target: NutrientTarget  # the underlying day-level target/provenance
    comparison_amount: float | None
    # "remaining_daily" — target minus what's already logged elsewhere
    # that day (comparison_amount can be 0 if the day's target is already
    # met/exceeded, never negative);
    # "explicit_share" — caller-specified fraction of the day's target,
    # used when there's no diary context to compute a remaining figure
    # from (e.g. reviewing a standalone recipe/meal in isolation);
    # "full_daily" — neither given: the day's target as-is, for a caller
    # that wants to interpret the comparison itself.
    comparison_mode: str


def adjust_target_for_remaining(target: NutrientTarget, already_consumed: float) -> NutrientTarget:
    """The "remaining room" version of a day-level target — `lower_target`/
    `preferred_target`/`upper_target` each reduced by `already_consumed`
    (never below 0), everything else (`target_type`, `source`, etc.)
    unchanged. For comparing just *one meal's own consumption* against
    what's left of the day's target, rather than the whole day's figure —
    the `recommend_*` modules use this for meal-scoped requests with real
    diary context, the same "remaining daily target" prompt section 2's
    `resolve_meal_comparison_target` already established for a single
    comparison_amount; this is the per-field version for a full
    `NutrientTarget` a scoring/gap-analysis pipeline can consume directly.
    """
    def remaining(value: float | None) -> float | None:
        return max(value - already_consumed, 0.0) if value is not None else None

    return dataclasses.replace(
        target,
        lower_target=remaining(target.lower_target),
        preferred_target=remaining(target.preferred_target),
        upper_target=remaining(target.upper_target),
    )


def resolve_meal_comparison_target(
    key: str,
    profile: Profile,
    *,
    already_consumed_today: float | None = None,
    explicit_share: float | None = None,
) -> MealComparisonTarget | None:
    """`already_consumed_today` (this nutrient's total from every OTHER
    entry logged that day) takes priority when given — "remaining daily
    target" is the more meaningful comparison whenever real diary context
    exists. `explicit_share` (e.g. 1/3) is for the no-diary-context case —
    reviewing one meal/recipe on its own — and is never applied
    automatically; a caller that gives neither gets the plain day target
    back, `comparison_mode="full_daily"`.

    Returns `None` only if the underlying day-level target itself can't
    be resolved (unknown nutrient key)."""
    day_target = resolve_nutrient_target(key, profile, AnalysisPeriod.DAY)
    if day_target is None:
        return None

    preferred = day_target.preferred_target
    if explicit_share is not None:
        comparison = preferred * explicit_share if preferred is not None else None
        mode = "explicit_share"
    elif already_consumed_today is not None:
        comparison = max(preferred - already_consumed_today, 0.0) if preferred is not None else None
        mode = "remaining_daily"
    else:
        comparison = preferred
        mode = "full_daily"

    return MealComparisonTarget(target=day_target, comparison_amount=comparison, comparison_mode=mode)
