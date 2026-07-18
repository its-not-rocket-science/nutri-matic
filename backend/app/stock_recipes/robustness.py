"""Deterministic Monte Carlo nutritional-robustness analysis (prompt
sections 9/10).

A robustness rating describes how stable a recipe's important nutritional
conclusions remain when its ingredient quantities vary within realistic
uncertainty — it is NOT a health score, a suitability judgement, or a
guarantee about the source recipe's own reliability. See
docs/stock-recipes.md for the full "what this does and doesn't mean"
explanation shown to users.

Every metric here is computed by re-running the app's REAL nutrition
engine per simulated draw — aggregation.py's aggregate_nutrients/
aggregate_amino_acids, scoring.py's compute_diaas/compute_pdcaas,
protein_absorption.py's compute_absorbed_protein, and
bioavailability.py's estimate_meal_iron_absorption (this is what "iron
robustness" actually models: the vitamin-C/meat-fish-poultry-dependent
absorption estimate, not raw iron mg — matching the prompt's own worked
example). No nutrition math is reimplemented here.

Nothing outside these nine metrics is calculated. In particular, no
phytate/oxalate/tannin/other absorption-modifier model is invented — this
app has no validated data for any of them (see bioavailability.py's module
docstring), so a metric that would require one simply isn't attempted.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

from ..aggregation import AminoAcidAggregate, WeightedFood, aggregate_amino_acids, aggregate_nutrients
from ..bioavailability import estimate_meal_iron_absorption, is_meat_fish_poultry, split_food_iron
from ..models import Food, FoodNutrient
from ..protein_absorption import compute_absorbed_protein
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas, compute_pdcaas

ROBUSTNESS_MODEL_VERSION = "1.0.0"
DEFAULT_SIMULATION_COUNT = 200
DEFAULT_RANDOM_SEED = 42

METRIC_LABELS: dict[str, str] = {
    "protein": "Protein",
    "absorbed_protein_diaas": "DIAAS-absorbed protein",
    "absorbed_protein_pdcaas": "PDCAAS-absorbed protein",
    "protein_quality_diaas": "DIAAS protein quality",
    "protein_quality_pdcaas": "PDCAAS protein quality",
    "iron": "Iron (estimated absorbed)",
    "calcium": "Calcium",
    "fibre": "Fibre",
    "sodium": "Sodium",
}
# "important" for overall_rating purposes and for whether a metric is
# reported at all — protein_quality is informational (protein + absorbed
# protein already cover the practical outcome) and would otherwise
# double-count protein three times in the overall rating
_OVERALL_METRICS = ("protein", "absorbed_protein_diaas", "absorbed_protein_pdcaas", "iron", "calcium", "fibre", "sodium")


@dataclass
class RobustnessIngredientInput:
    food: Food
    quantity_g: float
    # relative perturbation half-width (0-1) — see estimate_bound_fraction()
    bound_fraction: float
    optional: bool


def estimate_bound_fraction(conversion_confidence: str | None, parsing_confidence: float | None) -> float:
    """How far (as a fraction of stated quantity) an ingredient's amount is
    allowed to plausibly vary in the simulation — tighter for a precise
    stated mass, wider for an approximate household measure or a generic
    unit-weight guess, per prompt section 9's "narrower bounds for precise
    packaged quantities... wider bounds for approximate household
    measures". Not one universal percentage."""
    base = {"exact": 0.10, "measured": 0.20, "estimated": 0.35}.get(conversion_confidence, 0.30)
    if parsing_confidence is not None:
        base += (1.0 - parsing_confidence) * 0.15
    return min(base, 0.5)


@dataclass
class MetricResult:
    baseline: float | None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    cv: float | None = None
    threshold: float | None = None
    prob_above_threshold: float | None = None
    top_influential: list[dict] = field(default_factory=list)
    optional_sensitivity: float | None = None
    unmatched_uncertainty_note: str | None = None
    display_rating: int | None = None
    explanation: str = ""
    not_calculated_reason: str | None = None


@dataclass
class RobustnessAnalysis:
    model_version: str
    simulation_count: int
    random_seed: int
    metrics: dict[str, MetricResult]
    overall_rating: int | None
    overall_explanation: str


def _score_safe(method, amino_acids, digestibility, pattern) -> float | None:
    try:
        if method == "diaas":
            if digestibility is None:
                return None
            return compute_diaas(amino_acids, digestibility, pattern).score
        if digestibility is None:
            return None
        return compute_pdcaas(amino_acids, digestibility, pattern).score
    except (IncompleteAminoAcidProfile, UnknownReferencePattern):
        return None


def _compute_draw_metrics(
    items: list[WeightedFood],
    nutrients_by_food_id: dict[int, list[FoodNutrient]],
    servings: float,
    pattern: str,
) -> dict[str, float | None]:
    aggregate: AminoAcidAggregate = aggregate_amino_acids(items)
    totals = aggregate_nutrients(items, nutrients_by_food_id, divide_by=servings)
    absorbed = compute_absorbed_protein(aggregate, pattern)

    values: dict[str, float | None] = {
        "protein": (aggregate.total_protein_g / servings) if aggregate.total_protein_g > 0 else None,
        "absorbed_protein_diaas": (absorbed.diaas_absorbed_g / servings) if absorbed and absorbed.diaas_absorbed_g is not None else None,
        "absorbed_protein_pdcaas": (absorbed.pdcaas_absorbed_g / servings) if absorbed and absorbed.pdcaas_absorbed_g is not None else None,
        "protein_quality_diaas": _score_safe("diaas", aggregate.amino_acids, aggregate.digestibility_diaas, pattern),
        "protein_quality_pdcaas": _score_safe("pdcaas", aggregate.amino_acids, aggregate.digestibility_pdcaas, pattern),
        "calcium": totals.get("calcium"),
        "fibre": totals.get("fiber_total"),
        "sodium": totals.get("sodium"),
    }

    iron_splits = []
    for item in items:
        if item.quantity_g <= 0:
            continue
        rows = {fn.nutrient_key: fn.amount_per_100g for fn in nutrients_by_food_id.get(item.food.id, [])}
        total_iron_mg = rows.get("iron", 0.0) * item.quantity_g / 100
        if total_iron_mg <= 0:
            continue
        measured_heme = rows.get("iron_heme")
        measured_non_heme = rows.get("iron_non_heme")
        if measured_heme is not None:
            measured_heme = measured_heme * item.quantity_g / 100
        if measured_non_heme is not None:
            measured_non_heme = measured_non_heme * item.quantity_g / 100
        iron_splits.append(split_food_iron(item.food.name, total_iron_mg, measured_heme, measured_non_heme))
    vitamin_c_mg = totals.get("vitamin_c", 0.0) * servings  # estimate_meal_iron_absorption wants per-meal, not per-serving
    has_mfp = any(is_meat_fish_poultry(i.food.name) for i in items if i.quantity_g > 0)
    iron_estimate = estimate_meal_iron_absorption(iron_splits, vitamin_c_mg, has_mfp) if iron_splits else None
    values["iron"] = (iron_estimate.absorbed_total_mg / servings) if iron_estimate else None

    return values


def _percentile(sorted_values: list[float], pct: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


def _rating_for(cv: float | None, unmatched_mass_fraction: float) -> int:
    if cv is None:
        base = 1
    elif cv <= 0.05:
        base = 5
    elif cv <= 0.10:
        base = 4
    elif cv <= 0.20:
        base = 3
    elif cv <= 0.35:
        base = 2
    else:
        base = 1
    # prompt section 9: "do not award a high score when ingredient
    # coverage... is poor" — caps the rating regardless of how stable the
    # *matched* portion of the recipe simulated as being
    if unmatched_mass_fraction > 0.30:
        base = min(base, 2)
    elif unmatched_mass_fraction > 0.10:
        base = min(base, 3)
    return base


def _explain(metric_key: str, result: MetricResult) -> str:
    label = METRIC_LABELS[metric_key]
    if result.not_calculated_reason:
        return f"{label} robustness was not calculated: {result.not_calculated_reason}"
    if result.display_rating is None:
        return f"{label} robustness could not be rated."
    if result.display_rating >= 4:
        text = f"{label} robustness is high — plausible ingredient quantity variation does not materially change this recipe's {label.lower()}."
    elif result.display_rating == 3:
        text = f"{label} robustness is moderate — this recipe's {label.lower()} shifts noticeably under plausible ingredient variation."
    else:
        driver = result.top_influential[0]["ingredient"] if result.top_influential else None
        if driver:
            text = (
                f"{label} robustness is low because most of the estimated {label.lower()} depends on the "
                f"quantity of {driver}."
            )
        else:
            text = f"{label} robustness is low — this recipe's {label.lower()} is sensitive to plausible ingredient variation."
    if result.unmatched_uncertainty_note:
        text += f" {result.unmatched_uncertainty_note}"
    return text


def run_robustness(
    ingredients: list[RobustnessIngredientInput],
    servings: float,
    nutrients_by_food_id: dict[int, list[FoodNutrient]],
    unmatched_mass_fraction: float,
    simulation_count: int = DEFAULT_SIMULATION_COUNT,
    random_seed: int = DEFAULT_RANDOM_SEED,
    pattern: str = DEFAULT_PATTERN,
) -> RobustnessAnalysis:
    rng = random.Random(random_seed)

    baseline_items = [WeightedFood(i.food, i.quantity_g) for i in ingredients]
    baseline_values = _compute_draw_metrics(baseline_items, nutrients_by_food_id, servings, pattern)

    optional_present = any(i.optional for i in ingredients)
    without_optional_items = [WeightedFood(i.food, 0.0 if i.optional else i.quantity_g) for i in ingredients]
    without_optional_values = (
        _compute_draw_metrics(without_optional_items, nutrients_by_food_id, servings, pattern)
        if optional_present
        else {}
    )

    draw_values: dict[str, list[float]] = {key: [] for key in METRIC_LABELS}
    draw_quantities: list[list[float]] = [[] for _ in ingredients]

    for _ in range(max(simulation_count, 1)):
        simulated_items = []
        for idx, ing in enumerate(ingredients):
            factor = 1.0 + rng.uniform(-ing.bound_fraction, ing.bound_fraction)
            simulated_qty = max(0.0, ing.quantity_g * factor)
            draw_quantities[idx].append(simulated_qty)
            simulated_items.append(WeightedFood(ing.food, simulated_qty))

        draw_result = _compute_draw_metrics(simulated_items, nutrients_by_food_id, servings, pattern)
        for key, value in draw_result.items():
            if value is not None:
                draw_values[key].append(value)

    metrics: dict[str, MetricResult] = {}
    for key, label in METRIC_LABELS.items():
        baseline = baseline_values.get(key)
        values = draw_values[key]
        if baseline is None or len(values) < max(3, simulation_count // 4):
            metrics[key] = MetricResult(
                baseline=baseline,
                not_calculated_reason=(
                    "this recipe has no data for this metric (e.g. missing digestibility or nutrient coverage)"
                    if baseline is None
                    else "too few valid simulated draws to report a stable statistic"
                ),
            )
            continue

        sorted_values = sorted(values)
        mean = statistics.fmean(values)
        stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
        cv = (stdev / mean) if mean else None
        threshold = baseline * 0.8
        prob_above = sum(1 for v in values if v >= threshold) / len(values)

        correlations = []
        for idx, ing in enumerate(ingredients):
            corr = _correlation(draw_quantities[idx], values[: len(draw_quantities[idx])])
            if corr is not None:
                correlations.append((abs(corr), ing.food.name, corr))
        correlations.sort(key=lambda c: c[0], reverse=True)
        top_influential = [{"ingredient": name, "impact": round(corr, 3)} for _, name, corr in correlations[:3]]

        optional_sensitivity = None
        if optional_present and without_optional_values.get(key) is not None and baseline:
            optional_sensitivity = round(abs(baseline - without_optional_values[key]) / baseline, 4)

        unmatched_note = (
            f"{unmatched_mass_fraction * 100:.0f}% of this recipe's ingredient mass could not be matched to a "
            f"food and is excluded from this analysis, adding uncertainty beyond what's simulated here."
            if unmatched_mass_fraction > 0.02
            else None
        )

        result = MetricResult(
            baseline=round(baseline, 3),
            median=round(_percentile(sorted_values, 0.5), 3),
            p10=round(_percentile(sorted_values, 0.1), 3),
            p90=round(_percentile(sorted_values, 0.9), 3),
            cv=round(cv, 4) if cv is not None else None,
            threshold=round(threshold, 3),
            prob_above_threshold=round(prob_above, 3),
            top_influential=top_influential,
            optional_sensitivity=optional_sensitivity,
            unmatched_uncertainty_note=unmatched_note,
            display_rating=_rating_for(cv, unmatched_mass_fraction),
        )
        result.explanation = _explain(key, result)
        metrics[key] = result

    overall_rating, overall_explanation = _overall(metrics)

    return RobustnessAnalysis(
        model_version=ROBUSTNESS_MODEL_VERSION,
        simulation_count=simulation_count,
        random_seed=random_seed,
        metrics=metrics,
        overall_rating=overall_rating,
        overall_explanation=overall_explanation,
    )


def _overall(metrics: dict[str, MetricResult]) -> tuple[int | None, str]:
    """Not a naive mean (prompt section 9): weighted toward the weakest
    calculated metric among the "important" subset, so one fragile/
    dominant-ingredient-dependent nutrient can't be smoothed away by
    several stable ones."""
    ratings = [
        (key, metrics[key].display_rating)
        for key in _OVERALL_METRICS
        if key in metrics and metrics[key].display_rating is not None
    ]
    if not ratings:
        return None, "Overall robustness could not be rated — no metric had enough data to simulate."

    values = [r for _, r in ratings]
    worst_key, worst_rating = min(ratings, key=lambda r: r[1])
    mean_rating = statistics.fmean(values)
    overall = max(1, min(5, round((worst_rating + mean_rating) / 2)))

    if overall >= 4:
        explanation = "Overall robustness is high — this recipe's key nutritional conclusions are stable across plausible ingredient variation."
    else:
        explanation = (
            f"Overall robustness is limited primarily by {METRIC_LABELS[worst_key].lower()} robustness "
            f"({worst_rating}/5) — {metrics[worst_key].explanation}"
        )
    return overall, explanation
