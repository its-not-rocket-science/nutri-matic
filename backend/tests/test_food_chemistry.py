import pytest

from app.aggregation import WeightedFood
from app.food_chemistry import (
    compute_meal_protein_distribution,
    estimate_sodium_potassium,
    leucine_threshold_for_age,
)
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


def make_food(id_, protein_g_per_100g, leucine_mg_per_g_protein):
    aa = dict.fromkeys(AMINO_ACIDS, None)
    aa["leucine"] = leucine_mg_per_g_protein
    return Food(id=id_, name=f"food-{id_}", protein_g_per_100g=protein_g_per_100g, amino_acids=aa)


def test_leucine_threshold_defaults_to_younger_adult_when_age_unknown():
    assert leucine_threshold_for_age(None) == 2.5


def test_leucine_threshold_younger_vs_older_adult():
    assert leucine_threshold_for_age(30) == 2.5
    assert leucine_threshold_for_age(64) == 2.5
    assert leucine_threshold_for_age(65) == 3.0
    assert leucine_threshold_for_age(80) == 3.0


def test_meal_protein_distribution_computes_leucine_grams():
    # 30g protein/100g, 150g eaten -> 45g protein; leucine 80mg/g protein -> 45*80/1000 = 3.6g leucine
    food = make_food(1, protein_g_per_100g=30, leucine_mg_per_g_protein=80)
    result = compute_meal_protein_distribution("lunch", [WeightedFood(food, quantity_g=150)], leucine_threshold_g=2.5)

    assert result is not None
    assert result.protein_g == pytest.approx(45.0)
    assert result.leucine_g == pytest.approx(3.6)
    assert result.meets_leucine_threshold is True


def test_meal_protein_distribution_below_threshold():
    # 10g protein/100g, 50g eaten -> 5g protein; leucine 50mg/g -> 5*50/1000=0.25g, well under 2.5g threshold
    food = make_food(1, protein_g_per_100g=10, leucine_mg_per_g_protein=50)
    result = compute_meal_protein_distribution("snack", [WeightedFood(food, quantity_g=50)], leucine_threshold_g=2.5)

    assert result.meets_leucine_threshold is False
    assert result.leucine_g == pytest.approx(0.25)


def test_meal_protein_distribution_none_when_no_protein():
    food = make_food(1, protein_g_per_100g=0, leucine_mg_per_g_protein=80)
    result = compute_meal_protein_distribution("breakfast", [WeightedFood(food, quantity_g=100)], leucine_threshold_g=2.5)
    assert result is None


def test_meal_protein_distribution_missing_leucine_data_contributes_zero():
    food = Food(id=1, name="incomplete", protein_g_per_100g=20, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    result = compute_meal_protein_distribution("lunch", [WeightedFood(food, quantity_g=100)], leucine_threshold_g=2.5)
    assert result is not None
    assert result.protein_g == pytest.approx(20.0)
    assert result.leucine_g == 0.0
    assert result.meets_leucine_threshold is False


def test_sodium_potassium_none_when_nothing_logged():
    assert estimate_sodium_potassium(0, 0) is None


def test_sodium_potassium_none_ratio_when_no_potassium():
    result = estimate_sodium_potassium(500, 0)
    assert result.ratio is None
    assert "No potassium" in result.guidance


def test_sodium_potassium_within_who_target():
    # 1500mg sodium / 3600mg potassium = 0.417, below the ~0.57 target
    result = estimate_sodium_potassium(1500, 3600)
    assert result.ratio == pytest.approx(1500 / 3600)
    assert "At or below" in result.guidance


def test_sodium_potassium_above_who_target():
    # 3000mg sodium / 2000mg potassium = 1.5, well above ~0.57
    result = estimate_sodium_potassium(3000, 2000)
    assert result.ratio == pytest.approx(1.5)
    assert "Above" in result.guidance
