"""Tests for nutrient_targets.py — prompt 2 of the nutrient-gap
recommendation feature: representative profiles, all three analysis
periods, upper limits, and multi-day scaling."""

import pytest

from app.models import Profile
from app.nutrient_targets import (
    AnalysisPeriod,
    resolve_meal_comparison_target,
    resolve_nutrient_target,
)
from app.nutrients import (
    TARGET_TYPE_INFORMATIONAL,
    TARGET_TYPE_MAXIMUM_GUIDELINE,
    TARGET_TYPE_MINIMUM_OR_ADEQUATE_INTAKE,
    TARGET_TYPE_PERSONALIZED,
)


def make_profile(**kwargs):
    defaults = dict(
        user_id=1, name="Test", weight_kg=None, height_cm=None, birth_year=None, sex=None,
        activity_level=None, is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    return Profile(**defaults)


def test_unknown_nutrient_key_returns_none():
    profile = make_profile(sex="female")
    assert resolve_nutrient_target("not_a_real_nutrient", profile, AnalysisPeriod.DAY) is None


def test_ordinary_nutrient_minimum_or_adequate_intake():
    profile = make_profile(sex="female")
    target = resolve_nutrient_target("vitamin_c", profile, AnalysisPeriod.DAY)
    assert target.target_type == TARGET_TYPE_MINIMUM_OR_ADEQUATE_INTAKE
    assert target.lower_target == pytest.approx(40.0)
    assert target.preferred_target == pytest.approx(40.0)
    assert target.upper_target == pytest.approx(2000.0)  # UL present for vitamin_c
    assert target.optimisation_eligible is True
    assert target.source is not None


def test_profile_variants_resolve_different_drv():
    male = resolve_nutrient_target("iron", make_profile(sex="male"), AnalysisPeriod.DAY)
    female = resolve_nutrient_target("iron", make_profile(sex="female"), AnalysisPeriod.DAY)
    pregnant = resolve_nutrient_target("iron", make_profile(sex="female", is_pregnant=True), AnalysisPeriod.DAY)
    assert male.lower_target == pytest.approx(8.7)
    assert female.lower_target == pytest.approx(14.8)
    assert pregnant.lower_target == pytest.approx(14.8)
    # same nutrient, same upper limit regardless of sex/pregnancy (iron's UL has no confirmed split)
    assert male.upper_target == pytest.approx(45.0)
    assert pregnant.upper_target == pytest.approx(45.0)


def test_maximum_guideline_nutrient_has_only_an_upper_target():
    profile = make_profile(sex="female")
    sodium = resolve_nutrient_target("sodium", profile, AnalysisPeriod.DAY)
    assert sodium.target_type == TARGET_TYPE_MAXIMUM_GUIDELINE
    assert sodium.lower_target is None
    assert sodium.preferred_target is None
    assert sodium.upper_target == pytest.approx(2400.0)

    sat_fat = resolve_nutrient_target("saturated_fat", profile, AnalysisPeriod.DAY)
    assert sat_fat.target_type == TARGET_TYPE_MAXIMUM_GUIDELINE
    assert sat_fat.lower_target is None
    assert sat_fat.upper_target == pytest.approx(30.0)  # ceiling reused from the existing drv figure


def test_informational_nutrient_has_no_target_and_states_why():
    profile = make_profile(sex="female")
    target = resolve_nutrient_target("iron_heme", profile, AnalysisPeriod.DAY)
    assert target.target_type == TARGET_TYPE_INFORMATIONAL
    assert target.lower_target is None
    assert target.upper_target is None
    assert target.optimisation_eligible is False
    assert target.ineligibility_reason is not None


def test_personalized_energy_target():
    profile = make_profile(weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    target = resolve_nutrient_target("energy", profile, AnalysisPeriod.DAY)
    assert target.target_type == TARGET_TYPE_PERSONALIZED
    assert target.preferred_target is not None
    assert target.lower_target is None
    assert target.confidence == "personalized_calculation"
    assert target.goal_adjusted is False


def test_personalized_energy_target_goal_adjusted():
    profile = make_profile(
        weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate", goal="weight_loss",
    )
    target = resolve_nutrient_target("energy", profile, AnalysisPeriod.DAY)
    assert target.goal_adjusted is True
    assert "deficit" in target.source.lower()


def test_personalized_target_none_when_profile_incomplete():
    profile = make_profile(sex="male")  # missing weight/height/birth_year/activity_level
    target = resolve_nutrient_target("energy", profile, AnalysisPeriod.DAY)
    assert target.preferred_target is None
    assert target.optimisation_eligible is False
    assert target.ineligibility_reason is not None


def test_personalized_protein_target():
    profile = make_profile(weight_kg=70, birth_year=1990, sex="male", activity_level="sedentary")
    target = resolve_nutrient_target("protein", profile, AnalysisPeriod.DAY)
    assert target.target_type == TARGET_TYPE_PERSONALIZED
    assert target.preferred_target == pytest.approx(56.0)  # 0.8 * 70


def test_meal_and_day_period_give_the_same_flat_figure():
    """No automatic one-third-of-daily assumption — meal and day resolve
    identically unless a caller explicitly asks for a share/remaining
    figure via resolve_meal_comparison_target."""
    profile = make_profile(sex="female")
    day = resolve_nutrient_target("vitamin_c", profile, AnalysisPeriod.DAY)
    meal = resolve_nutrient_target("vitamin_c", profile, AnalysisPeriod.MEAL)
    assert day.preferred_target == meal.preferred_target
    assert day.scales_with_period is False
    assert meal.scales_with_period is False


def test_multi_day_scales_lower_preferred_and_upper():
    profile = make_profile(sex="female")
    target = resolve_nutrient_target("vitamin_c", profile, AnalysisPeriod.MULTI_DAY, day_count=7)
    assert target.lower_target == pytest.approx(40.0 * 7)
    assert target.preferred_target == pytest.approx(40.0 * 7)
    assert target.upper_target == pytest.approx(2000.0 * 7)
    assert target.scales_with_period is True


def test_multi_day_scales_personalized_energy_target():
    profile = make_profile(weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    day = resolve_nutrient_target("energy", profile, AnalysisPeriod.DAY)
    week = resolve_nutrient_target("energy", profile, AnalysisPeriod.MULTI_DAY, day_count=7)
    assert week.preferred_target == pytest.approx(day.preferred_target * 7)
    assert week.scales_with_period is True


def test_multi_day_with_day_count_one_does_not_mark_scaled():
    profile = make_profile(sex="female")
    target = resolve_nutrient_target("vitamin_c", profile, AnalysisPeriod.MULTI_DAY, day_count=1)
    assert target.scales_with_period is False


# --- meal comparison target -------------------------------------------

def test_meal_comparison_full_daily_when_nothing_given():
    profile = make_profile(sex="female")
    result = resolve_meal_comparison_target("vitamin_c", profile)
    assert result.comparison_mode == "full_daily"
    assert result.comparison_amount == pytest.approx(40.0)


def test_meal_comparison_remaining_daily():
    profile = make_profile(sex="female")
    result = resolve_meal_comparison_target("vitamin_c", profile, already_consumed_today=30.0)
    assert result.comparison_mode == "remaining_daily"
    assert result.comparison_amount == pytest.approx(10.0)


def test_meal_comparison_remaining_daily_never_negative():
    profile = make_profile(sex="female")
    result = resolve_meal_comparison_target("vitamin_c", profile, already_consumed_today=1000.0)
    assert result.comparison_amount == 0.0


def test_meal_comparison_explicit_share():
    profile = make_profile(sex="female")
    result = resolve_meal_comparison_target("vitamin_c", profile, explicit_share=1 / 3)
    assert result.comparison_mode == "explicit_share"
    assert result.comparison_amount == pytest.approx(40.0 / 3)


def test_meal_comparison_explicit_share_takes_priority_over_remaining():
    profile = make_profile(sex="female")
    result = resolve_meal_comparison_target(
        "vitamin_c", profile, already_consumed_today=30.0, explicit_share=0.5,
    )
    assert result.comparison_mode == "explicit_share"
    assert result.comparison_amount == pytest.approx(20.0)


def test_meal_comparison_none_for_unknown_nutrient():
    profile = make_profile(sex="female")
    assert resolve_meal_comparison_target("not_a_real_nutrient", profile) is None


def test_meal_comparison_handles_no_target_gracefully():
    """energy has no lower/preferred established when the profile is
    incomplete — comparison_amount must be None, not raise."""
    profile = make_profile(sex="male")
    result = resolve_meal_comparison_target("energy", profile, already_consumed_today=500.0)
    assert result.comparison_amount is None
