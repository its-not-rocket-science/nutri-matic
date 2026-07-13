import pytest

from app.aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS


def make_food(id_, protein_g_per_100g, aa_value, diaas_value, pdcaas_value):
    return Food(
        id=id_,
        name=f"food-{id_}",
        protein_g_per_100g=protein_g_per_100g,
        amino_acids=dict.fromkeys(AMINO_ACIDS, aa_value),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, diaas_value) if diaas_value is not None else None,
        digestibility_pdcaas=pdcaas_value,
    )


def test_aggregate_amino_acids_weighted_by_protein_contribution():
    # A: 10g protein/100g, 200g used -> 20g protein contributed
    # B: 5g protein/100g, 100g used -> 5g protein contributed
    food_a = make_food(1, protein_g_per_100g=10, aa_value=10, diaas_value=0.9, pdcaas_value=0.85)
    food_b = make_food(2, protein_g_per_100g=5, aa_value=30, diaas_value=0.8, pdcaas_value=0.7)

    result = aggregate_amino_acids(
        [WeightedFood(food_a, quantity_g=200), WeightedFood(food_b, quantity_g=100)]
    )

    assert result.total_protein_g == pytest.approx(25.0)
    # (10*20 + 30*5) / 25 = 350/25 = 14
    assert result.amino_acids["histidine"] == pytest.approx(14.0)
    # digestible mg: 10*20*0.9=180, 30*5*0.8=120 -> 300/350 = 0.857142...
    assert result.digestibility_diaas["histidine"] == pytest.approx(300 / 350)
    # pdcaas: (20*0.85 + 5*0.7) / 25 = 20.5/25 = 0.82
    assert result.digestibility_pdcaas == pytest.approx(0.82)


def test_aggregate_amino_acids_missing_data_makes_mixture_unscorable():
    food_a = make_food(1, protein_g_per_100g=10, aa_value=10, diaas_value=0.9, pdcaas_value=0.85)
    food_b = Food(
        id=2, name="incomplete", protein_g_per_100g=5,
        amino_acids=dict.fromkeys(AMINO_ACIDS, None), digestibility_diaas=None, digestibility_pdcaas=None,
    )

    result = aggregate_amino_acids(
        [WeightedFood(food_a, quantity_g=100), WeightedFood(food_b, quantity_g=100)]
    )

    assert result.amino_acids["histidine"] is None
    assert result.digestibility_diaas["histidine"] is None
    assert result.digestibility_pdcaas is None


def test_aggregate_amino_acids_zero_protein_returns_empty():
    food = make_food(1, protein_g_per_100g=0, aa_value=10, diaas_value=0.9, pdcaas_value=0.85)
    result = aggregate_amino_acids([WeightedFood(food, quantity_g=100)])
    assert result.total_protein_g == 0
    assert all(v is None for v in result.amino_acids.values())


def test_aggregate_nutrients_sums_and_divides_by_servings():
    food_a = Food(id=1, name="a", protein_g_per_100g=1, amino_acids={})
    food_b = Food(id=2, name="b", protein_g_per_100g=1, amino_acids={})
    food_nutrients = {
        1: [FoodNutrient(food_id=1, nutrient_key="vitamin_c", amount_per_100g=10)],
        2: [FoodNutrient(food_id=2, nutrient_key="vitamin_c", amount_per_100g=5)],
    }

    totals = aggregate_nutrients(
        [WeightedFood(food_a, quantity_g=200), WeightedFood(food_b, quantity_g=100)],
        food_nutrients,
        divide_by=2,
    )

    # (10*200/100 + 5*100/100) / 2 servings = (20 + 5) / 2 = 12.5
    assert totals["vitamin_c"] == pytest.approx(12.5)


def test_aggregate_nutrients_missing_row_contributes_zero():
    food_a = Food(id=1, name="a", protein_g_per_100g=1, amino_acids={})
    food_nutrients = {1: []}
    totals = aggregate_nutrients([WeightedFood(food_a, quantity_g=100)], food_nutrients)
    assert totals == {}
