import pytest

from app.bioavailability import (
    IronSplit,
    estimate_calcium_phosphorus,
    estimate_meal_iron_absorption,
    is_meat_fish_poultry,
    split_food_iron,
)


def test_is_meat_fish_poultry_true_for_animal_flesh():
    assert is_meat_fish_poultry("Chicken, breast, meat only, cooked")
    assert is_meat_fish_poultry("Salmon, Atlantic, farmed, cooked")


def test_is_meat_fish_poultry_false_for_plant_foods():
    assert not is_meat_fish_poultry("Spinach, raw")
    assert not is_meat_fish_poultry("Lentils, raw")


def test_is_meat_fish_poultry_excludes_substitutes():
    assert not is_meat_fish_poultry("Chicken substitute, meatless, plant-based")


def test_split_food_iron_uses_measured_values_when_present():
    split = split_food_iron("Beef, ground, cooked", total_iron_mg=2.0, measured_heme_mg=1.5, measured_non_heme_mg=0.5)
    assert split.heme_mg == 1.5
    assert split.non_heme_mg == 0.5
    assert split.is_estimated is False


def test_split_food_iron_estimates_for_meat():
    split = split_food_iron("Beef, ground, cooked", total_iron_mg=2.0, measured_heme_mg=None, measured_non_heme_mg=None)
    assert split.heme_mg == pytest.approx(0.8)  # 40% of 2.0
    assert split.non_heme_mg == pytest.approx(1.2)
    assert split.is_estimated is True


def test_split_food_iron_plant_food_all_non_heme_not_flagged_estimated():
    split = split_food_iron("Spinach, raw", total_iron_mg=2.7, measured_heme_mg=None, measured_non_heme_mg=None)
    assert split.heme_mg == 0.0
    assert split.non_heme_mg == 2.7
    assert split.is_estimated is False


def test_estimate_meal_iron_absorption_baseline_tier():
    splits = [IronSplit(heme_mg=0.0, non_heme_mg=2.0, is_estimated=False)]
    result = estimate_meal_iron_absorption(splits, vitamin_c_mg=0.0, has_meat_fish_poultry=False)
    assert result is not None
    assert result.non_heme_absorption_tier == "baseline"
    assert result.absorbed_non_heme_mg == pytest.approx(0.1)  # 5% of 2.0
    assert result.absorbed_heme_mg == 0.0


def test_estimate_meal_iron_absorption_enhanced_by_vitamin_c():
    splits = [IronSplit(heme_mg=0.0, non_heme_mg=2.0, is_estimated=False)]
    result = estimate_meal_iron_absorption(splits, vitamin_c_mg=30.0, has_meat_fish_poultry=False)
    assert result.non_heme_absorption_tier == "enhanced"
    assert result.absorbed_non_heme_mg == pytest.approx(0.2)  # 10% of 2.0


def test_estimate_meal_iron_absorption_enhanced_by_mfp_presence():
    splits = [IronSplit(heme_mg=0.8, non_heme_mg=1.2, is_estimated=True)]
    result = estimate_meal_iron_absorption(splits, vitamin_c_mg=0.0, has_meat_fish_poultry=True)
    assert result.non_heme_absorption_tier == "enhanced"
    assert result.absorbed_heme_mg == pytest.approx(0.2)  # 25% of 0.8
    assert result.iron_split_source == "estimated"


def test_estimate_meal_iron_absorption_none_when_no_iron():
    result = estimate_meal_iron_absorption([], vitamin_c_mg=50.0, has_meat_fish_poultry=False)
    assert result is None


def test_estimate_calcium_phosphorus_none_when_no_phosphorus():
    assert estimate_calcium_phosphorus(500, 0) is None


def test_estimate_calcium_phosphorus_low_ratio_flagged():
    result = estimate_calcium_phosphorus(calcium_mg=300, phosphorus_mg=900)
    assert result.ratio == pytest.approx(1 / 3)
    assert "Phosphorus intake is higher" in result.guidance


def test_estimate_calcium_phosphorus_within_range():
    result = estimate_calcium_phosphorus(calcium_mg=700, phosphorus_mg=550)
    assert result.ratio == pytest.approx(700 / 550)
    assert "traditionally recommended" in result.guidance


def test_estimate_calcium_phosphorus_high_ratio():
    result = estimate_calcium_phosphorus(calcium_mg=2000, phosphorus_mg=500)
    assert result.ratio == pytest.approx(4.0)
    assert "notably higher" in result.guidance
