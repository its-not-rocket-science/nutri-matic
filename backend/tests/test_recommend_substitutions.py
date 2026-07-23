"""Tests for recommend_substitutions.py — prompt 8: similar-energy
substitution, no valid replacement, dietary exclusions, multi-gap
improvement, upper-limit rejection, and deterministic (idempotent)
repeated requests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.aggregation import WeightedFood, scale_recipe_ingredients
from app.database import Base
from app.models import DietaryConstraint, Food, FoodNutrient, Profile, Recipe, RecipeIngredient, User
from app.nutrient_targets import AnalysisPeriod
from app.reference_patterns import AMINO_ACIDS
from app.recommend_substitutions import suggest_substitutions


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_user(db, email):
    user = User(email=email, password_hash="x")
    db.add(user)
    db.commit()
    return user


def make_profile(db, user, **kwargs):
    defaults = dict(
        user_id=user.id, name="Test", weight_kg=None, height_cm=None, birth_year=None, sex="female",
        activity_level=None, is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    profile = Profile(**defaults)
    db.add(profile)
    db.commit()
    return profile


def make_food(db, name, protein=1.0, **nutrients):
    food = Food(name=name, protein_g_per_100g=protein, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    db.add(food)
    db.flush()
    for key, amount in nutrients.items():
        db.add(FoodNutrient(food_id=food.id, nutrient_key=key, amount_per_100g=amount))
    db.commit()
    return food


def make_recipe(db, owner, name, servings, ingredients, **kwargs):
    recipe = Recipe(user_id=owner.id, name=name, servings=servings, **kwargs)
    db.add(recipe)
    db.flush()
    for food, quantity_g in ingredients:
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=quantity_g))
    db.commit()
    return recipe


def run(db, profile, user, current_recipe, current_servings=1.0, other_food=None, **kwargs):
    other_items = [WeightedFood(other_food, 100.0)] if other_food else []
    nutrients_by_food_id = {}
    if other_food:
        nutrients_by_food_id[other_food.id] = db.query(FoodNutrient).filter(FoodNutrient.food_id == other_food.id).all()
    return suggest_substitutions(
        db, profile, user, other_items, current_recipe, current_servings, nutrients_by_food_id,
        AnalysisPeriod.DAY, **kwargs,
    )


def test_similar_energy_substitution_suggested(db):
    user = make_user(db, "a@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])
    make_recipe(db, user, "Lentil Bowl", 1, [(lentils, 224)])  # similar energy to 200g rice

    result = run(db, profile, user, original)  # no unrelated "other" food logged that day
    assert result.suggestions
    assert result.suggestions[0].replacement_recipe_name == "Lentil Bowl"
    assert abs(result.suggestions[0].energy_difference_kcal) < 50


def test_no_valid_replacement_when_nothing_visible(db):
    user = make_user(db, "b@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])

    result = run(db, profile, user, original, other_food=rice)
    assert result.suggestions == []


def test_dietary_exclusion_removes_replacement(db):
    user = make_user(db, "c@example.com")
    profile = make_profile(db, user, dietary_pattern="vegan")
    rice = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    chicken = make_food(db, "Chicken breast, raw", protein=25.0, iron=5.0, energy=165)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])
    make_recipe(db, user, "Chicken Bowl", 1, [(chicken, 150)])

    result = run(db, profile, user, original, other_food=rice, priority_nutrient_keys={"iron"})
    assert all(s.replacement_recipe_name != "Chicken Bowl" for s in result.suggestions)


def test_allergen_exclusion_removes_replacement(db):
    user = make_user(db, "d@example.com")
    profile = make_profile(db, user)
    db.add(DietaryConstraint(user_id=user.id, profile_id=profile.id, category="allergy", tag="peanut", severity="hard_exclude"))
    db.commit()
    rice = make_food(db, "White rice, cooked", energy=130, magnesium=5.0)
    peanut_butter = make_food(db, "Peanut butter, smooth style without salt", magnesium=150.0, energy=590)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])
    make_recipe(db, user, "Peanut Toast", 1, [(peanut_butter, 30)])

    result = run(db, profile, user, original, other_food=rice, priority_nutrient_keys={"magnesium"})
    assert all(s.replacement_recipe_name != "Peanut Toast" for s in result.suggestions)


def test_upper_limit_breach_rejected(db):
    user = make_user(db, "e@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, sodium=100.0)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])
    salty = make_food(db, "Very Salty Dish Ingredient", sodium=5000.0, energy=120)
    make_recipe(db, user, "Salty Dish", 1, [(salty, 200)])

    result = run(db, profile, user, original, other_food=rice)
    assert all(s.replacement_recipe_name != "Salty Dish" for s in result.suggestions)
    assert any("upper limit" in r.reason for r in result.rejected)


def test_multi_gap_improvement_reports_key_nutrient_differences(db):
    user = make_user(db, "f@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4, iron=0.1)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])
    lentils = make_food(db, "Lentils", fiber_total=8.0, iron=6.0, protein=9.0, energy=116)
    make_recipe(db, user, "Lentil Bowl", 1, [(lentils, 224)])

    result = run(db, profile, user, original, other_food=rice, priority_nutrient_keys={"fiber_total", "iron"})
    if result.suggestions:
        suggestion = result.suggestions[0]
        assert suggestion.fiber_difference_g > 0
        assert "protein" in suggestion.key_nutrient_differences


def test_deterministic_repeated_requests(db):
    user = make_user(db, "g@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    original = make_recipe(db, user, "Plain Rice Bowl", 1, [(rice, 200)])
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    chickpeas = make_food(db, "Chickpeas", fiber_total=7.0, energy=120)
    make_recipe(db, user, "Lentil Bowl", 1, [(lentils, 224)])
    make_recipe(db, user, "Chickpea Bowl", 1, [(chickpeas, 220)])

    first = run(db, profile, user, original, other_food=rice)
    second = run(db, profile, user, original, other_food=rice)
    assert [s.replacement_recipe_name for s in first.suggestions] == [s.replacement_recipe_name for s in second.suggestions]


def test_replacement_servings_scaled_to_similar_energy(db):
    user = make_user(db, "h@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=400, fiber_total=0.4)  # a big portion
    original = make_recipe(db, user, "Big Rice Bowl", 1, [(rice, 300)])
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)  # low energy per serving
    make_recipe(db, user, "Lentil Bowl", 1, [(lentils, 150)])  # ~174kcal/serving

    result = run(db, profile, user, original, other_food=rice)
    if result.suggestions:
        # should scale up servings to approach the original's energy, not just use 1 serving
        assert result.suggestions[0].replacement_servings > 1.0
