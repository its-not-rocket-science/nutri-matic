"""Table-driven tests for nutrient_gap_analysis.py — prompt 3: clear
shortfalls, adequate intake, upper-limit breaches, missing data, partial
coverage, multi-day scaling, remaining-daily-target analysis, and
zero-energy/zero-protein edge cases."""

import dataclasses

import pytest

from app.models import Profile
from app.nutrient_gap_analysis import (
    NutrientStatus,
    analyse_nutrient_gap,
    analyse_nutrient_gaps,
    worst_gap,
)
from app.nutrient_targets import AnalysisPeriod, resolve_meal_comparison_target, resolve_nutrient_target
from app.reference_patterns import AMINO_ACIDS
from app.models import Food, FoodNutrient


def make_profile(**kwargs):
    defaults = dict(
        user_id=1, name="Test", weight_kg=None, height_cm=None, birth_year=None, sex=None,
        activity_level=None, is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    return Profile(**defaults)


PROFILE = make_profile(sex="female")


def target(key, period=AnalysisPeriod.DAY, **kwargs):
    return resolve_nutrient_target(key, PROFILE, period, **kwargs)


# --- table-driven: analyse_nutrient_gap direct classification --------------

CASES = [
    # (label, key, consumed, coverage, expected_status)
    ("clear shortfall", "vitamin_c", 5.0, 1.0, NutrientStatus.BELOW_TARGET),
    ("near target", "vitamin_c", 38.0, 1.0, NutrientStatus.NEAR_TARGET),  # 95% of 40
    ("adequate/within target", "vitamin_c", 45.0, 1.0, NutrientStatus.WITHIN_TARGET),
    ("above preferred, below UL", "vitamin_c", 100.0, 1.0, NutrientStatus.ABOVE_PREFERRED),  # 250% of 40, UL 2000
    ("upper-limit breach", "vitamin_c", 2500.0, 1.0, NutrientStatus.ABOVE_UPPER_LIMIT),
    ("missing data entirely", "vitamin_c", None, 0.0, NutrientStatus.INSUFFICIENT_DATA),
    ("partial coverage below bar", "vitamin_c", 5.0, 0.3, NutrientStatus.INSUFFICIENT_DATA),
    ("partial coverage above bar still judged", "vitamin_c", 5.0, 0.6, NutrientStatus.BELOW_TARGET),
]


@pytest.mark.parametrize("label,key,consumed,coverage,expected_status", CASES, ids=[c[0] for c in CASES])
def test_gap_classification(label, key, consumed, coverage, expected_status):
    result = analyse_nutrient_gap(key, consumed, coverage, target(key))
    assert result.status == expected_status


def test_below_target_reports_shortfall_and_weight():
    result = analyse_nutrient_gap("vitamin_c", 20.0, 1.0, target("vitamin_c"))
    assert result.absolute_shortfall == pytest.approx(20.0)
    assert result.percent_shortfall == pytest.approx(50.0)
    assert result.optimisation_weight > 0
    assert "gap" in result.explanation.lower()


def test_upper_limit_breach_reports_amount_above_both():
    result = analyse_nutrient_gap("iron", 50.0, 1.0, target("iron"))  # UL 45
    assert result.status == NutrientStatus.ABOVE_UPPER_LIMIT
    assert result.amount_above_upper_limit == pytest.approx(5.0)
    assert result.amount_above_preferred is not None
    assert result.optimisation_weight == 0.0


def test_maximum_guideline_nutrient_only_has_within_or_above_upper_limit():
    within = analyse_nutrient_gap("sodium", 2000.0, 1.0, target("sodium"))
    above = analyse_nutrient_gap("sodium", 3000.0, 1.0, target("sodium"))
    assert within.status == NutrientStatus.WITHIN_TARGET
    assert above.status == NutrientStatus.ABOVE_UPPER_LIMIT
    assert above.optimisation_weight == 0.0  # never a shortfall to "fix" by adding more


def test_informational_nutrient_always_insufficient_data_regardless_of_coverage():
    result = analyse_nutrient_gap("iron_heme", 5.0, 1.0, target("iron_heme"))
    assert result.status == NutrientStatus.INSUFFICIENT_DATA
    assert result.optimisation_weight == 0.0
    assert result.explanation  # states a reason, never blank


def test_never_calls_deficiency_or_disease():
    for consumed in (0.0, 5.0, 20.0, 45.0, 2500.0):
        result = analyse_nutrient_gap("vitamin_c", consumed, 1.0, target("vitamin_c"))
        text = result.explanation.lower()
        assert "deficien" not in text
        assert "disease" not in text
        assert "treat" not in text


# --- zero-energy / zero-protein edge cases ---------------------------------

def test_zero_energy_consumed_never_optimisation_weighted():
    """energy is deliberately excluded from optimisation_weight (matches
    the existing _find_worst_gap's exclusion) — even a severe zero-vs-target
    "shortfall" must never be treated as a gap to close by recommending food."""
    complete_profile = make_profile(weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    energy_target = resolve_nutrient_target("energy", complete_profile, AnalysisPeriod.DAY)
    result = analyse_nutrient_gap("energy", 0.0, 1.0, energy_target)
    assert result.status == NutrientStatus.BELOW_TARGET
    assert result.optimisation_weight == 0.0


def test_zero_protein_consumed_is_a_real_below_target_gap():
    profile = make_profile(weight_kg=70, birth_year=1990, sex="male", activity_level="sedentary")
    protein_target = resolve_nutrient_target("protein", profile, AnalysisPeriod.DAY)
    result = analyse_nutrient_gap("protein", 0.0, 1.0, protein_target)
    assert result.status == NutrientStatus.BELOW_TARGET
    assert result.optimisation_weight > 0  # protein IS optimisation-eligible, unlike energy


def test_unresolvable_personalized_target_is_insufficient_data():
    incomplete_profile = make_profile(sex="male")  # missing weight/height/etc
    energy_target = resolve_nutrient_target("energy", incomplete_profile, AnalysisPeriod.DAY)
    result = analyse_nutrient_gap("energy", 500.0, 1.0, energy_target)
    assert result.status == NutrientStatus.INSUFFICIENT_DATA


# --- multi-day scaling ------------------------------------------------------

def test_multi_day_shortfall_scales_with_target():
    week_target = target("vitamin_c", AnalysisPeriod.MULTI_DAY, day_count=7)
    # 200mg over a week vs a 280mg (40*7) target — clearly short
    result = analyse_nutrient_gap("vitamin_c", 200.0, 1.0, week_target)
    assert result.status == NutrientStatus.BELOW_TARGET
    assert result.absolute_shortfall == pytest.approx(80.0)


# --- remaining-daily-target analysis (via nutrient_targets integration) ---

def test_remaining_daily_target_analysis():
    comparison = resolve_meal_comparison_target("vitamin_c", PROFILE, already_consumed_today=35.0)
    # only 5mg of "room" left in the day's 40mg target
    adjusted_target = dataclasses.replace(
        comparison.target, preferred_target=comparison.comparison_amount, lower_target=comparison.comparison_amount,
    )
    result = analyse_nutrient_gap("vitamin_c", 2.0, 1.0, adjusted_target)
    assert result.status == NutrientStatus.BELOW_TARGET
    assert result.absolute_shortfall == pytest.approx(3.0)


# --- analyse_nutrient_gaps: full aggregation-facing entry point -----------

def test_analyse_nutrient_gaps_computes_coverage_from_missing_food_nutrient_rows():
    from app.aggregation import WeightedFood

    covered_food = Food(id=1, name="Covered Food", protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    uncovered_food = Food(id=2, name="Uncovered Food", protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    items = [WeightedFood(covered_food, 100.0), WeightedFood(uncovered_food, 100.0)]
    nutrients_by_food_id = {1: [FoodNutrient(food_id=1, nutrient_key="vitamin_c", amount_per_100g=40.0)]}
    totals = {"vitamin_c": 40.0}  # only the covered food contributed

    target_by_key = {"vitamin_c": target("vitamin_c")}
    results = analyse_nutrient_gaps(items, nutrients_by_food_id, totals, target_by_key)

    assert len(results) == 1
    assert results[0].coverage == pytest.approx(0.5)  # half the mass had a known value


def test_analyse_nutrient_gaps_priority_keys_zeroes_other_weights():
    from app.aggregation import WeightedFood

    food = Food(id=1, name="Test Food", protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    items = [WeightedFood(food, 100.0)]
    nutrients_by_food_id = {1: [
        FoodNutrient(food_id=1, nutrient_key="vitamin_c", amount_per_100g=5.0),
        FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=100.0),
    ]}
    totals = {"vitamin_c": 5.0, "calcium": 100.0}
    target_by_key = {"vitamin_c": target("vitamin_c"), "calcium": target("calcium")}

    results = analyse_nutrient_gaps(items, nutrients_by_food_id, totals, target_by_key, priority_keys={"calcium"})
    by_key = {r.key: r for r in results}
    assert by_key["vitamin_c"].status == NutrientStatus.BELOW_TARGET  # still computed
    assert by_key["vitamin_c"].optimisation_weight == 0.0  # but not weighted — not prioritised
    assert by_key["calcium"].optimisation_weight > 0


def test_worst_gap_picks_highest_weight():
    small_gap = analyse_nutrient_gap("vitamin_c", 38.0, 1.0, target("vitamin_c"))  # near target, small weight
    big_gap = analyse_nutrient_gap("calcium", 100.0, 1.0, target("calcium"))  # far below, big weight
    assert worst_gap([small_gap, big_gap]) is big_gap


def test_worst_gap_none_when_nothing_short():
    result = analyse_nutrient_gap("vitamin_c", 45.0, 1.0, target("vitamin_c"))
    assert worst_gap([result]) is None
