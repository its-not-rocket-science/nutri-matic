import pytest

from app.aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients, scale_recipe_ingredients
from app.models import Food, FoodNutrient, RecipeIngredient
from app.reference_patterns import AMINO_ACIDS


def make_food(
    id_, protein_g_per_100g, aa_value, diaas_value, pdcaas_value, diaas_source=None, pdcaas_source=None
):
    return Food(
        id=id_,
        name=f"food-{id_}",
        protein_g_per_100g=protein_g_per_100g,
        amino_acids=dict.fromkeys(AMINO_ACIDS, aa_value),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, diaas_value) if diaas_value is not None else None,
        digestibility_diaas_source=diaas_source,
        digestibility_pdcaas=pdcaas_value,
        digestibility_pdcaas_source=pdcaas_source,
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


def test_aggregate_source_is_measured_only_if_every_contributor_measured():
    food_a = make_food(
        1, protein_g_per_100g=10, aa_value=10, diaas_value=0.9, pdcaas_value=0.85,
        diaas_source="measured", pdcaas_source="measured",
    )
    food_b = make_food(
        2, protein_g_per_100g=5, aa_value=30, diaas_value=0.8, pdcaas_value=0.7,
        diaas_source="measured", pdcaas_source="measured",
    )

    result = aggregate_amino_acids([WeightedFood(food_a, quantity_g=100), WeightedFood(food_b, quantity_g=100)])
    assert result.digestibility_diaas_source == "measured"
    assert result.digestibility_pdcaas_source == "measured"


def test_aggregate_source_is_estimated_if_any_contributor_estimated():
    food_a = make_food(
        1, protein_g_per_100g=10, aa_value=10, diaas_value=0.9, pdcaas_value=0.85,
        diaas_source="measured", pdcaas_source="measured",
    )
    food_b = make_food(
        2, protein_g_per_100g=5, aa_value=30, diaas_value=0.8, pdcaas_value=0.7,
        diaas_source="estimated", pdcaas_source="estimated",
    )

    result = aggregate_amino_acids([WeightedFood(food_a, quantity_g=100), WeightedFood(food_b, quantity_g=100)])
    assert result.digestibility_diaas_source == "estimated"
    assert result.digestibility_pdcaas_source == "estimated"


def test_aggregate_amino_acids_partial_diaas_profile_leaves_only_missing_aa_null():
    """Mirrors the real-world "measured" digestibility rows in
    digestibility_reference.py, where a study reports coefficients for most
    but not all amino acids (e.g. histidine/tryptophan not reported for
    egg/chicken) — the dict has some keys present and others entirely
    absent. Amino acids WITH a reported coefficient must still aggregate
    correctly; only the unreported one should end up null."""
    partial_diaas = dict.fromkeys(AMINO_ACIDS, 0.9)
    del partial_diaas["histidine"]  # not reported by the source study
    food = Food(
        id=1, name="partially-measured", protein_g_per_100g=10,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 20),
        digestibility_diaas=partial_diaas,
        digestibility_pdcaas=0.85,
    )

    result = aggregate_amino_acids([WeightedFood(food, quantity_g=100)])

    assert result.digestibility_diaas["histidine"] is None
    assert result.digestibility_diaas["leucine"] == pytest.approx(0.9)
    assert result.amino_acids["histidine"] == pytest.approx(20.0)  # AA content itself is still known


def test_aggregate_source_is_none_when_no_contributor_has_digestibility():
    food = make_food(1, protein_g_per_100g=10, aa_value=10, diaas_value=None, pdcaas_value=None)
    result = aggregate_amino_acids([WeightedFood(food, quantity_g=100)])
    assert result.digestibility_diaas_source is None
    assert result.digestibility_pdcaas_source is None


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


def test_scale_recipe_ingredients_by_servings_eaten():
    # recipe makes 4 servings from 400g of food A and 200g of food B
    food_a = Food(id=1, name="a", protein_g_per_100g=1, amino_acids={})
    food_b = Food(id=2, name="b", protein_g_per_100g=1, amino_acids={})
    ingredients = [
        RecipeIngredient(recipe_id=1, food_id=1, quantity_g=400),
        RecipeIngredient(recipe_id=1, food_id=2, quantity_g=200),
    ]

    # eating 1.5 of the 4 servings -> scale factor 1.5/4 = 0.375
    weighted = scale_recipe_ingredients(
        ingredients, recipe_servings=4, servings_eaten=1.5, foods_by_id={1: food_a, 2: food_b}
    )

    by_food_id = {w.food.id: w.quantity_g for w in weighted}
    assert by_food_id[1] == pytest.approx(400 * 0.375)
    assert by_food_id[2] == pytest.approx(200 * 0.375)


def test_diary_day_combines_direct_food_and_recipe_entries():
    """A day with one direct food entry and one 'N servings of a recipe'
    entry should aggregate exactly as if the recipe's scaled ingredients
    had been logged directly."""
    direct_food = Food(id=1, name="yogurt", protein_g_per_100g=1, amino_acids={})
    recipe_food_a = Food(id=2, name="a", protein_g_per_100g=1, amino_acids={})
    recipe_food_b = Food(id=3, name="b", protein_g_per_100g=1, amino_acids={})

    recipe_ingredients = [
        RecipeIngredient(recipe_id=1, food_id=2, quantity_g=400),
        RecipeIngredient(recipe_id=1, food_id=3, quantity_g=200),
    ]
    # 2 servings out of 4 -> scale 0.5
    from_recipe = scale_recipe_ingredients(
        recipe_ingredients, recipe_servings=4, servings_eaten=2,
        foods_by_id={2: recipe_food_a, 3: recipe_food_b},
    )
    items = [WeightedFood(direct_food, quantity_g=150), *from_recipe]

    food_nutrients = {
        1: [FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=100)],
        2: [FoodNutrient(food_id=2, nutrient_key="calcium", amount_per_100g=10)],
        3: [FoodNutrient(food_id=3, nutrient_key="calcium", amount_per_100g=20)],
    }

    totals = aggregate_nutrients(items, food_nutrients)

    # yogurt: 100*150/100 = 150
    # recipe: food a scaled to 200g -> 10*200/100=20; food b scaled to 100g -> 20*100/100=20
    # total = 150 + 20 + 20 = 190
    assert totals["calcium"] == pytest.approx(190.0)
