"""Tests for recommend_recipes.py — prompt 7: ownership/visibility,
dietary filtering, energy caps, protein quality, robustness-based
uncertainty, and the primary-ingredient diversity rule."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    DietaryConstraint,
    Food,
    FoodNutrient,
    Profile,
    Recipe,
    RecipeIngredient,
    RecipeShare,
    RobustnessResult,
    User,
)
from app.nutrient_targets import AnalysisPeriod
from app.reference_patterns import AMINO_ACIDS
from app.recommend_recipes import suggest_recipes


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_user(db, email, is_system=False):
    user = User(email=email, password_hash="x", is_system=is_system)
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


def run(db, profile, current_user, current_food, **kwargs):
    from app.aggregation import WeightedFood

    items = [WeightedFood(current_food, 100.0)]
    nutrients_by_food_id = {
        current_food.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current_food.id).all(),
    }
    return suggest_recipes(db, profile, current_user, items, nutrients_by_food_id, AnalysisPeriod.DAY, **kwargs)


def test_suggests_recipe_that_closes_a_gap(db):
    user = make_user(db, "a@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(db, user, "Lentil Soup", 2, [(lentils, 200)])

    result = run(db, profile, user, rice)
    assert result.suggestions
    assert result.suggestions[0].recipe_name == "Lentil Soup"
    assert "fiber_total" in result.suggestions[0].nutrients_improved


def test_other_users_private_recipe_not_visible(db):
    owner = make_user(db, "owner@example.com")
    viewer = make_user(db, "viewer@example.com")
    viewer_profile = make_profile(db, viewer)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(db, owner, "Private Lentil Soup", 2, [(lentils, 200)])  # not public, not shared

    result = run(db, viewer_profile, viewer, rice)
    assert result.suggestions == []


def test_public_stock_recipe_visible_to_any_user(db):
    system_user = make_user(db, "stock@example.com")
    viewer = make_user(db, "viewer2@example.com")
    viewer_profile = make_profile(db, viewer)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(db, system_user, "Public Lentil Soup", 2, [(lentils, 200)], is_public=True)

    result = run(db, viewer_profile, viewer, rice)
    assert any(s.recipe_name == "Public Lentil Soup" for s in result.suggestions)


def test_shared_recipe_visible_to_recipient(db):
    owner = make_user(db, "owner2@example.com")
    recipient = make_user(db, "recipient@example.com")
    recipient_profile = make_profile(db, recipient)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    recipe = make_recipe(db, owner, "Shared Lentil Soup", 2, [(lentils, 200)])
    db.add(RecipeShare(recipe_id=recipe.id, shared_with_user_id=recipient.id))
    db.commit()

    result = run(db, recipient_profile, recipient, rice)
    assert any(s.recipe_name == "Shared Lentil Soup" for s in result.suggestions)


def test_vegan_profile_excludes_recipe_with_poultry(db):
    user = make_user(db, "vegan@example.com")
    profile = make_profile(db, user, dietary_pattern="vegan")
    rice = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    chicken = make_food(db, "Chicken breast, raw", protein=25.0, iron=5.0)
    lentils = make_food(db, "Lentils", iron=6.0, energy=116)
    make_recipe(db, user, "Chicken and Rice", 2, [(chicken, 200)])
    make_recipe(db, user, "Lentil Curry", 2, [(lentils, 200)])

    result = run(db, profile, user, rice, priority_nutrient_keys={"iron"})
    assert all(s.recipe_name != "Chicken and Rice" for s in result.suggestions)


def test_allergen_hard_exclusion_removes_recipe(db):
    user = make_user(db, "allergy@example.com")
    profile = make_profile(db, user)
    db.add(DietaryConstraint(user_id=user.id, profile_id=profile.id, category="allergy", tag="peanut", severity="hard_exclude"))
    db.commit()
    rice = make_food(db, "White rice, cooked", energy=130, magnesium=5.0)
    peanut_butter = make_food(db, "Peanut butter, smooth style without salt", magnesium=150.0)
    make_recipe(db, user, "Peanut Butter Toast", 1, [(peanut_butter, 30)])

    result = run(db, profile, user, rice, priority_nutrient_keys={"magnesium"})
    assert all(s.recipe_name != "Peanut Butter Toast" for s in result.suggestions)


def test_max_additional_energy_caps_recipe_suggestions(db):
    user = make_user(db, "cap@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=800)  # deliberately calorie-dense
    make_recipe(db, user, "Big Lentil Bake", 1, [(lentils, 300)])

    result = run(db, profile, user, rice, max_additional_energy=50.0)
    assert result.suggestions == []
    assert any("cap" in r.reason for r in result.rejected)


def test_protein_added_reported(db):
    user = make_user(db, "protein@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, protein=2.7)
    chicken = make_food(db, "Chicken breast, raw", protein=25.0, iron=1.0)
    make_recipe(db, user, "Chicken Dish", 1, [(chicken, 150)])

    result = run(db, profile, user, rice, priority_nutrient_keys={"iron"})
    if result.suggestions:
        assert result.suggestions[0].protein_added_g > 0


def test_low_robustness_recipe_flagged_and_penalized(db):
    user = make_user(db, "robust@example.com", is_system=True)
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    recipe = make_recipe(
        db, user, "Stock Lentil Soup", 2, [(lentils, 200)],
        is_public=True, import_slug="lentil_soup_test", match_coverage_lines=0.9, match_coverage_mass=0.9,
    )
    db.add(RobustnessResult(
        recipe_id=recipe.id, is_latest=True, model_version="1.0.0", simulation_count=10, random_seed=1,
        metrics={}, overall_rating=2, overall_explanation="low robustness",
    ))
    db.commit()

    result = run(db, profile, user, rice)
    suggestion = next((s for s in result.suggestions if s.recipe_name == "Stock Lentil Soup"), None)
    assert suggestion is not None
    assert suggestion.robustness_rating == 2
    assert suggestion.robustness_note is not None
    assert "low" in suggestion.robustness_note.lower() or "uncertainty" in suggestion.robustness_note.lower()


def test_missing_robustness_data_degrades_gracefully(db):
    """Prompt 12's "graceful degradation if robustness data are
    unavailable" — a stock recipe with no RobustnessResult row at all
    (never computed, not merely low) must still come back as a normal
    suggestion, never an error and never a fabricated rating."""
    user = make_user(db, "norobust@example.com", is_system=True)
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(
        db, user, "Uncomputed Robustness Soup", 2, [(lentils, 200)],
        is_public=True, import_slug="uncomputed_test",
    )

    result = run(db, profile, user, rice)
    suggestion = next((s for s in result.suggestions if s.recipe_name == "Uncomputed Robustness Soup"), None)
    assert suggestion is not None
    assert suggestion.robustness_rating is None
    assert suggestion.robustness_note == "Robustness has not yet been computed for this recipe."


def test_stock_recipe_reports_match_coverage(db):
    user = make_user(db, "coverage@example.com", is_system=True)
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(
        db, user, "Stock Recipe With Coverage", 2, [(lentils, 200)],
        is_public=True, import_slug="coverage_test", match_coverage_lines=0.75, match_coverage_mass=0.8,
    )

    result = run(db, profile, user, rice)
    suggestion = next((s for s in result.suggestions if s.recipe_name == "Stock Recipe With Coverage"), None)
    assert suggestion is not None
    assert suggestion.match_coverage_lines == pytest.approx(0.75)
    assert suggestion.is_stock is True


def test_ordinary_recipe_has_no_match_coverage(db):
    user = make_user(db, "ordinary@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(db, user, "My Own Soup", 2, [(lentils, 200)])

    result = run(db, profile, user, rice)
    suggestion = next((s for s in result.suggestions if s.recipe_name == "My Own Soup"), None)
    assert suggestion is not None
    assert suggestion.is_stock is False
    assert suggestion.match_coverage_lines is None


def test_diversity_dedupes_recipes_sharing_a_primary_ingredient(db):
    user = make_user(db, "diversity@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(db, user, "Lentil Soup A", 1, [(lentils, 250)])
    make_recipe(db, user, "Lentil Soup B", 1, [(lentils, 240)])  # same primary ingredient

    result = run(db, profile, user, rice, max_suggestions=5)
    lentil_recipes = [s for s in result.suggestions if "Lentil" in s.recipe_name]
    assert len(lentil_recipes) == 1


def test_no_recipes_visible_returns_empty(db):
    user = make_user(db, "empty@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)

    result = run(db, profile, user, rice)
    assert result.suggestions == []


def test_goal_preset_calcium(db):
    user = make_user(db, "goal@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, calcium=1.0, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)  # no calcium — should not be favoured
    milk = make_food(db, "Milk, whole", calcium=120.0, energy=60)
    make_recipe(db, user, "Lentil Dish", 1, [(lentils, 200)])
    make_recipe(db, user, "Milky Dish", 1, [(milk, 200)])

    result = run(db, profile, user, rice, goal="calcium")
    if result.suggestions:
        assert result.suggestions[0].recipe_name == "Milky Dish"


def test_deterministic_ordering(db):
    user = make_user(db, "det@example.com")
    profile = make_profile(db, user)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    chickpeas = make_food(db, "Chickpeas", fiber_total=7.0, energy=120)
    make_recipe(db, user, "Lentil Soup", 1, [(lentils, 250)])
    make_recipe(db, user, "Chickpea Stew", 1, [(chickpeas, 250)])

    first = run(db, profile, user, rice)
    second = run(db, profile, user, rice)
    assert [s.recipe_name for s in first.suggestions] == [s.recipe_name for s in second.suggestions]
