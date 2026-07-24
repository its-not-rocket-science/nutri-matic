"""General, deterministic candidate-scoring engine — prompt 4 of the
nutrient-gap recommendation feature (see
docs/nutrient-gap-recommendations.md).

No machine learning anywhere, per the prompt's own instruction — every
score is a documented, centrally-configurable arithmetic combination of
real, already-computed signals this app produces elsewhere:
`nutrient_gap_analysis` (before/after gap comparison — real simulated
totals, never estimated from a candidate's raw per-100g content alone,
matching `optimizer.py`'s existing convention),
`aggregation.compute_protein_quality_with_coverage` (protein quality),
`dietary_tags.Suitability` (soft dietary fit — hard exclusions are a
caller-side filter, never reaching this module at all), and whatever
ingredient-mapping/data-quality confidence a caller has for the candidate.

This module scores ONE already-simulated candidate at a time — it has no
opinion on what the candidate IS (a food, a recipe, a swap) or how it was
generated; `recommend_ingredients.py`/`recommend_recipes.py`/etc (prompts
6-9) own that, this module only turns "here's the before state and the
after state" into a score breakdown.

`PracticalityInput` (prompt 5) is optional and defaults to "no data" (a
neutral practicality contribution and no implausible-serving penalty) —
this module's shape doesn't change once prompt 5's candidate metadata
exists, real values just start flowing into a field that was previously
always `None`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .aggregation import ProteinQualityResult
from .dietary_tags import Suitability
from .nutrient_gap_analysis import NutrientGapResult, NutrientStatus

# Bump whenever ScoringWeights' defaults, the scoring formula itself, or
# any other part of score_candidate's arithmetic changes materially enough
# that an old cached/stored result could no longer be trusted — see
# prompt 12 (docs/nutrient-gap-recommendations.md's performance/caching
# section) for why a cache key needs this, and prompt 14's maintainer
# instructions for when to bump it. Not tied to the feature's own prompt
# numbering — this only tracks the scoring formula/weights.
RECOMMENDATION_MODEL_VERSION = 1


@dataclass(frozen=True)
class PracticalityInput:
    """Prompt 5's candidate-metadata signal, read here but not computed
    here. `is_plausible_serving` is None (not False) when this app simply
    has no serving-size data for the candidate at all — an unknown isn't
    the same claim as "known to be implausible"."""

    is_plausible_serving: bool | None = None
    preparation_burden: str | None = None  # "none" | "light" | "moderate" | "significant" — informational only, not scored


@dataclass(frozen=True)
class ScoringWeights:
    """Every tunable constant the scoring formula uses, in one place —
    prompt 4 point 10: "keep all parameters centrally configurable and
    documented." Change a value here (or pass an override instance to
    `score_candidate`) rather than a magic number buried in the formula."""

    # weighted_gap_reduction
    gap_reduction_weight: float = 1.0
    # a candidate that meaningfully improves more than one prioritised
    # nutrient gets a multiplicative bonus on top of the raw weight sum —
    # prompt 4 point: "coverage of multiple priority nutrients". Capped so
    # touching a 6th nutrient doesn't keep compounding forever.
    multi_nutrient_bonus_per_extra: float = 0.15
    multi_nutrient_bonus_max_extra: int = 4
    # protein_quality_benefit — per whole point of DIAAS/PDCAAS score gained
    protein_quality_weight: float = 0.5
    # dietary_fit
    dietary_ok_bonus: float = 0.3
    dietary_avoid_penalty: float = 0.5
    dietary_unknown_penalty: float = 0.2
    # practicality (prompt 5 — neutral until PracticalityInput carries real data)
    practicality_bonus: float = 0.3
    implausible_serving_penalty: float = 0.6
    # upper_limit_penalty — deliberately much larger than the mild
    # above-preferred multiplier, per prompt 4: "upper-limit breaches must
    # create a stronger penalty than merely exceeding a preferred target"
    above_preferred_penalty_weight: float = 0.4
    upper_limit_penalty_weight: float = 4.0
    # energy_overshoot_penalty — per 100kcal over the caller's stated cap;
    # 0 contribution whenever no cap was given at all (no opinion on a
    # constraint the caller didn't ask for)
    energy_overshoot_weight_per_100kcal: float = 0.2
    # uncertainty_penalty components
    low_confidence_weight: float = 0.5  # scales (1 - ingredient_confidence)
    low_coverage_weight: float = 0.5  # scales (1 - candidate's own data coverage)


DEFAULT_WEIGHTS = ScoringWeights()


@dataclass(frozen=True)
class ScoreBreakdown:
    """Never just one number (prompt 4 point 1) — every term the
    conceptual formula names, plus which nutrients actually improved, so
    an explanation can say something concrete rather than "trust the
    score"."""

    weighted_gap_reduction: float
    protein_quality_benefit: float
    dietary_fit: float
    practicality: float
    upper_limit_penalty: float
    # a milder excess penalty than upper_limit_penalty — folded into the
    # same conceptual "excess" formula term as upper_limit_penalty (see
    # the module's conceptual formula), broken out as its own field here
    # purely so a caller/test can see the two are scaled very differently,
    # not just infer it from the total.
    above_preferred_penalty: float
    energy_overshoot_penalty: float
    uncertainty_penalty: float
    implausible_serving_penalty: float
    total: float
    nutrients_improved: list[str] = field(default_factory=list)
    nutrients_worsened: list[str] = field(default_factory=list)


def _gap_reduction(before: list[NutrientGapResult], after: list[NutrientGapResult], weights: ScoringWeights) -> tuple[float, list[str]]:
    """Sum of optimisation_weight actually reduced by this candidate,
    across every nutrient the caller resolved gaps for. A nutrient already
    at/above target before (weight already 0) can contribute nothing here
    — prompt 4 point 3: "avoid rewarding nutrients already substantially
    above target" is true by construction, not a special case.

    A nutrient whose status becomes `insufficient_data` after the
    candidate is added is explicitly excluded here, even though its
    weight also drops to 0 — that drop means the candidate's added mass
    *diluted coverage* for a nutrient it carries no data for (more total
    mass, no new information), not that the shortfall was addressed.
    Counting that as a "reduction" would reward a candidate for making
    this app less able to judge a gap, exactly backwards."""
    after_by_key = {g.key: g for g in after}
    total = 0.0
    improved: list[str] = []
    for b in before:
        a = after_by_key.get(b.key)
        if a is None or a.status == NutrientStatus.INSUFFICIENT_DATA:
            continue
        reduction = b.optimisation_weight - a.optimisation_weight
        if reduction > 1e-9:
            total += reduction
            improved.append(b.key)

    if len(improved) > 1:
        bonus_nutrients = min(len(improved) - 1, weights.multi_nutrient_bonus_max_extra)
        total *= 1 + weights.multi_nutrient_bonus_per_extra * bonus_nutrients

    return total * weights.gap_reduction_weight, improved


@dataclass(frozen=True)
class _ExcessPenalties:
    upper_limit_penalty: float
    above_preferred_penalty: float
    worsened: list[str]


def _excess_penalty(before: list[NutrientGapResult], after: list[NutrientGapResult], weights: ScoringWeights) -> _ExcessPenalties:
    """Penalises a candidate for *creating or worsening* an excess — never
    for an excess that already existed before the candidate was added
    (that's not this candidate's doing). Upper-limit breaches are
    penalised far more heavily than merely exceeding the preferred amount,
    normalised per-nutrient (amount-above / upper-or-preferred-target) so
    a big-unit nutrient (sodium, mg) and a small-unit one (vitamin B12,
    mcg) contribute on the same relative scale."""
    before_by_key = {g.key: g for g in before}
    upper_limit_penalty = 0.0
    above_preferred_penalty = 0.0
    worsened: list[str] = []
    for a in after:
        b = before_by_key.get(a.key)
        before_upper = b.amount_above_upper_limit if b is not None else None
        before_preferred = b.amount_above_preferred if b is not None else None

        if a.status == NutrientStatus.ABOVE_UPPER_LIMIT:
            new_excess = a.amount_above_upper_limit - (before_upper or 0.0)
            if new_excess > 1e-9 and a.target.upper_target:
                upper_limit_penalty += (new_excess / a.target.upper_target) * weights.upper_limit_penalty_weight
                worsened.append(a.key)
        elif a.status == NutrientStatus.ABOVE_PREFERRED:
            new_excess = (a.amount_above_preferred or 0.0) - (before_preferred or 0.0)
            reference = a.target.preferred_target or a.target.upper_target
            if new_excess > 1e-9 and reference:
                above_preferred_penalty += (new_excess / reference) * weights.above_preferred_penalty_weight
                worsened.append(a.key)

    return _ExcessPenalties(upper_limit_penalty, above_preferred_penalty, worsened)


def _protein_quality_benefit(
    before: ProteinQualityResult | None, after: ProteinQualityResult | None, weights: ScoringWeights,
) -> float:
    if before is None or after is None or before.score is None or after.score is None:
        return 0.0
    return max(after.score.score - before.score.score, 0.0) * weights.protein_quality_weight


def _dietary_fit(suitability: Suitability | None, weights: ScoringWeights) -> float:
    if suitability is None:
        return 0.0
    if suitability.status == "ok":
        return weights.dietary_ok_bonus
    if suitability.status == "avoid":
        return -weights.dietary_avoid_penalty
    if suitability.status == "unknown":
        return -weights.dietary_unknown_penalty
    return 0.0  # "excluded" should never reach scoring at all — hard-filtered upstream


def _energy_overshoot_penalty(energy_added: float, max_additional_energy: float | None, weights: ScoringWeights) -> float:
    if max_additional_energy is None:
        return 0.0
    overshoot = energy_added - max_additional_energy
    if overshoot <= 0:
        return 0.0
    return (overshoot / 100) * weights.energy_overshoot_weight_per_100kcal


def _uncertainty_penalty(
    ingredient_confidence: float | None, candidate_data_coverage: float | None, weights: ScoringWeights,
) -> float:
    penalty = 0.0
    if ingredient_confidence is not None:
        penalty += (1 - ingredient_confidence) * weights.low_confidence_weight
    if candidate_data_coverage is not None:
        penalty += (1 - candidate_data_coverage) * weights.low_coverage_weight
    return penalty


def _practicality(practicality: PracticalityInput | None, weights: ScoringWeights) -> tuple[float, float]:
    if practicality is None or practicality.is_plausible_serving is None:
        return 0.0, 0.0  # no data — neutral, never guessed either way
    if practicality.is_plausible_serving:
        return weights.practicality_bonus, 0.0
    return 0.0, weights.implausible_serving_penalty


def score_candidate(
    before_gaps: list[NutrientGapResult],
    after_gaps: list[NutrientGapResult],
    *,
    energy_added: float = 0.0,
    max_additional_energy: float | None = None,
    protein_quality_before: ProteinQualityResult | None = None,
    protein_quality_after: ProteinQualityResult | None = None,
    dietary_suitability: Suitability | None = None,
    ingredient_confidence: float | None = None,
    candidate_data_coverage: float | None = None,
    practicality: PracticalityInput | None = None,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> ScoreBreakdown:
    """Scores one already-simulated candidate — `before_gaps`/`after_gaps`
    are `nutrient_gap_analysis.analyse_nutrient_gaps` results for the same
    nutrient set, before and after the candidate is hypothetically added.
    Every other argument is optional and defaults to "no signal" (0/None),
    never a fabricated value — a caller that can't supply protein-quality
    or provenance data simply gets no contribution from that term, not a
    guessed one.
    """
    gap_reduction, improved = _gap_reduction(before_gaps, after_gaps, weights)
    excess = _excess_penalty(before_gaps, after_gaps, weights)
    upper_limit_penalty, above_preferred_penalty, worsened = (
        excess.upper_limit_penalty, excess.above_preferred_penalty, excess.worsened,
    )

    protein_quality_benefit = _protein_quality_benefit(protein_quality_before, protein_quality_after, weights)
    dietary_fit = _dietary_fit(dietary_suitability, weights)
    energy_overshoot_penalty = _energy_overshoot_penalty(energy_added, max_additional_energy, weights)
    uncertainty_penalty = _uncertainty_penalty(ingredient_confidence, candidate_data_coverage, weights)
    practicality_bonus, serving_penalty = _practicality(practicality, weights)

    total = (
        gap_reduction
        + protein_quality_benefit
        + dietary_fit
        + practicality_bonus
        - upper_limit_penalty
        - above_preferred_penalty
        - energy_overshoot_penalty
        - uncertainty_penalty
        - serving_penalty
    )

    return ScoreBreakdown(
        weighted_gap_reduction=gap_reduction,
        protein_quality_benefit=protein_quality_benefit,
        dietary_fit=dietary_fit,
        practicality=practicality_bonus,
        upper_limit_penalty=upper_limit_penalty,
        above_preferred_penalty=above_preferred_penalty,
        energy_overshoot_penalty=energy_overshoot_penalty,
        uncertainty_penalty=uncertainty_penalty,
        implausible_serving_penalty=serving_penalty,
        total=total,
        nutrients_improved=improved,
        nutrients_worsened=worsened,
    )
