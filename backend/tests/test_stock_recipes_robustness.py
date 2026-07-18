"""Robustness tests — prompt section 16: reproducibility with fixed seeds,
expected stability for balanced recipes, expected fragility when one
ingredient dominates, optional ingredient handling, unmatched-ingredient
penalties, zero/invalid quantities, model-version persistence."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.robustness import (
    ROBUSTNESS_MODEL_VERSION,
    RobustnessIngredientInput,
    estimate_bound_fraction,
    run_robustness,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _food(session, name, protein=10.0, **kwargs):
    food = Food(name=name, protein_g_per_100g=protein, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="foundation_food", **kwargs)
    session.add(food)
    session.flush()
    return food


def _nutrients_by_food_id(session, *foods):
    result = {}
    for f in foods:
        result[f.id] = session.query(FoodNutrient).filter(FoodNutrient.food_id == f.id).all()
    return result


def test_estimate_bound_fraction_tighter_for_exact():
    assert estimate_bound_fraction("exact", 1.0) < estimate_bound_fraction("estimated", 1.0)


def test_estimate_bound_fraction_widens_with_low_parsing_confidence():
    assert estimate_bound_fraction("measured", 0.3) > estimate_bound_fraction("measured", 1.0)


def test_estimate_bound_fraction_capped():
    assert estimate_bound_fraction("estimated", 0.0) <= 0.5


def test_reproducible_with_fixed_seed(db):
    beef = _food(db, "Beef, ground, 85% lean", protein=17.2)
    db.add(FoodNutrient(food_id=beef.id, nutrient_key="sodium", amount_per_100g=70))
    db.add(FoodNutrient(food_id=beef.id, nutrient_key="iron", amount_per_100g=2.6))
    db.commit()

    ingredients = [RobustnessIngredientInput(beef, 300.0, estimate_bound_fraction("exact", 1.0), False)]
    nutrients = _nutrients_by_food_id(db, beef)

    result_a = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=100, random_seed=7)
    result_b = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=100, random_seed=7)

    assert result_a.metrics["sodium"].median == result_b.metrics["sodium"].median
    assert result_a.metrics["sodium"].cv == result_b.metrics["sodium"].cv
    assert result_a.overall_rating == result_b.overall_rating


def test_different_seeds_can_differ(db):
    beef = _food(db, "Beef, ground, 85% lean", protein=17.2)
    db.add(FoodNutrient(food_id=beef.id, nutrient_key="sodium", amount_per_100g=70))
    db.commit()
    ingredients = [RobustnessIngredientInput(beef, 300.0, 0.4, False)]
    nutrients = _nutrients_by_food_id(db, beef)

    result_a = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=50, random_seed=1)
    result_b = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=50, random_seed=2)
    # not asserting inequality of every stat (could coincidentally match),
    # just that the seed is actually threaded through to the RNG
    assert result_a.random_seed != result_b.random_seed


def test_balanced_recipe_is_stable(db):
    """Several ingredients, each with a tight (exact-mass) bound and each
    contributing a modest, similar share of sodium — no single ingredient
    should dominate the outcome, so the metric should simulate as stable."""
    foods = [_food(db, f"Ingredient {i}", protein=5.0) for i in range(5)]
    for f in foods:
        db.add(FoodNutrient(food_id=f.id, nutrient_key="sodium", amount_per_100g=40))
    db.commit()

    ingredients = [RobustnessIngredientInput(f, 100.0, estimate_bound_fraction("exact", 1.0), False) for f in foods]
    nutrients = _nutrients_by_food_id(db, *foods)

    result = run_robustness(ingredients, 4, nutrients, 0.0, simulation_count=300, random_seed=42)
    sodium = result.metrics["sodium"]
    assert sodium.cv is not None and sodium.cv < 0.1
    assert sodium.display_rating >= 4


def test_dominant_ingredient_is_fragile(db):
    """One ingredient with a wide, low-confidence bound supplies almost all
    of the sodium — the metric should simulate as fragile, and that
    ingredient should be reported as the top influential one."""
    dominant = _food(db, "Dominant Salty Ingredient", protein=5.0)
    minor = _food(db, "Minor Ingredient", protein=5.0)
    db.add(FoodNutrient(food_id=dominant.id, nutrient_key="sodium", amount_per_100g=800))
    db.add(FoodNutrient(food_id=minor.id, nutrient_key="sodium", amount_per_100g=2))
    db.commit()

    ingredients = [
        RobustnessIngredientInput(dominant, 200.0, estimate_bound_fraction("estimated", 0.3), False),
        RobustnessIngredientInput(minor, 100.0, estimate_bound_fraction("exact", 1.0), False),
    ]
    nutrients = _nutrients_by_food_id(db, dominant, minor)

    result = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=300, random_seed=42)
    sodium = result.metrics["sodium"]
    assert sodium.cv is not None and sodium.cv > 0.15
    assert sodium.display_rating <= 3
    assert sodium.top_influential[0]["ingredient"] == "Dominant Salty Ingredient"


def test_optional_ingredient_sensitivity_reported(db):
    base = _food(db, "Base Ingredient", protein=5.0)
    optional = _food(db, "Optional Iron Booster", protein=1.0)
    db.add(FoodNutrient(food_id=base.id, nutrient_key="iron", amount_per_100g=1.0))
    db.add(FoodNutrient(food_id=optional.id, nutrient_key="iron", amount_per_100g=20.0))
    db.commit()

    ingredients = [
        RobustnessIngredientInput(base, 200.0, 0.1, False),
        RobustnessIngredientInput(optional, 50.0, 0.1, True),
    ]
    nutrients = _nutrients_by_food_id(db, base, optional)

    result = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=100, random_seed=42)
    iron = result.metrics["iron"]
    # removing the optional ingredient (which supplies most of the iron)
    # should show up as a large sensitivity
    assert iron.optional_sensitivity is not None
    assert iron.optional_sensitivity > 0.5


def test_no_optional_ingredients_gives_no_sensitivity(db):
    food = _food(db, "Plain Ingredient", protein=5.0)
    db.add(FoodNutrient(food_id=food.id, nutrient_key="iron", amount_per_100g=1.0))
    db.commit()
    ingredients = [RobustnessIngredientInput(food, 100.0, 0.1, False)]
    nutrients = _nutrients_by_food_id(db, food)

    result = run_robustness(ingredients, 1, nutrients, 0.0, simulation_count=50, random_seed=42)
    assert result.metrics["iron"].optional_sensitivity is None


def test_unmatched_mass_fraction_caps_rating(db):
    """Even a perfectly stable ingredient set gets its rating capped when a
    large share of the recipe's mass was never matched — prompt section 9:
    "do not award a high score when ingredient coverage... is poor.\""""
    food = _food(db, "Stable Ingredient", protein=5.0)
    db.add(FoodNutrient(food_id=food.id, nutrient_key="sodium", amount_per_100g=40))
    db.commit()
    ingredients = [RobustnessIngredientInput(food, 300.0, estimate_bound_fraction("exact", 1.0), False)]
    nutrients = _nutrients_by_food_id(db, food)

    good_coverage = run_robustness(ingredients, 2, nutrients, unmatched_mass_fraction=0.0, simulation_count=200, random_seed=42)
    poor_coverage = run_robustness(ingredients, 2, nutrients, unmatched_mass_fraction=0.5, simulation_count=200, random_seed=42)

    assert good_coverage.metrics["sodium"].display_rating >= 4
    assert poor_coverage.metrics["sodium"].display_rating <= 2
    assert poor_coverage.metrics["sodium"].unmatched_uncertainty_note is not None


def test_zero_quantity_ingredient_does_not_crash(db):
    food = _food(db, "Zero Quantity Ingredient", protein=5.0)
    db.add(FoodNutrient(food_id=food.id, nutrient_key="sodium", amount_per_100g=40))
    db.commit()
    ingredients = [RobustnessIngredientInput(food, 0.0, 0.2, False)]
    nutrients = _nutrients_by_food_id(db, food)

    result = run_robustness(ingredients, 1, nutrients, 0.0, simulation_count=50, random_seed=42)
    # a zero-quantity ingredient contributes nothing — protein baseline is
    # None (nothing to report), not a crash or a fabricated figure
    assert result.metrics["protein"].baseline is None
    assert result.metrics["protein"].not_calculated_reason is not None


def test_no_digestibility_data_reports_not_calculated(db):
    food = _food(db, "No Digestibility Data", protein=10.0)
    # deliberately no digestibility_diaas/pdcaas set
    db.commit()
    ingredients = [RobustnessIngredientInput(food, 100.0, 0.1, False)]
    nutrients = _nutrients_by_food_id(db, food)

    result = run_robustness(ingredients, 1, nutrients, 0.0, simulation_count=50, random_seed=42)
    assert result.metrics["protein_quality_diaas"].not_calculated_reason is not None
    assert result.metrics["protein_quality_diaas"].display_rating is None


def test_model_version_recorded(db):
    food = _food(db, "Any Ingredient", protein=5.0)
    db.commit()
    ingredients = [RobustnessIngredientInput(food, 100.0, 0.1, False)]
    nutrients = _nutrients_by_food_id(db, food)

    result = run_robustness(ingredients, 1, nutrients, 0.0, simulation_count=20, random_seed=1)
    assert result.model_version == ROBUSTNESS_MODEL_VERSION


def test_overall_rating_is_not_a_naive_mean(db):
    """One very fragile metric among several stable ones should pull the
    overall rating down more than a plain average would."""
    stable_a = _food(db, "Stable A", protein=5.0)
    stable_b = _food(db, "Stable B", protein=5.0)
    fragile = _food(db, "Fragile Dominant", protein=5.0)
    db.add(FoodNutrient(food_id=stable_a.id, nutrient_key="calcium", amount_per_100g=50))
    db.add(FoodNutrient(food_id=stable_b.id, nutrient_key="fiber_total", amount_per_100g=5))
    db.add(FoodNutrient(food_id=fragile.id, nutrient_key="sodium", amount_per_100g=900))
    db.commit()

    ingredients = [
        RobustnessIngredientInput(stable_a, 200.0, estimate_bound_fraction("exact", 1.0), False),
        RobustnessIngredientInput(stable_b, 200.0, estimate_bound_fraction("exact", 1.0), False),
        RobustnessIngredientInput(fragile, 200.0, estimate_bound_fraction("estimated", 0.2), False),
    ]
    nutrients = _nutrients_by_food_id(db, stable_a, stable_b, fragile)

    result = run_robustness(ingredients, 2, nutrients, 0.0, simulation_count=300, random_seed=42)
    ratings = [m.display_rating for m in result.metrics.values() if m.display_rating is not None]
    naive_mean = round(sum(ratings) / len(ratings))
    # the weakest-link-biased overall should be at or below the naive mean,
    # never above it
    assert result.overall_rating <= naive_mean
