"""Tests for recommend_validate.py — prompt 14's maintainer validation
CLI. Read-only; asserts each check function's real behaviour against a
small fixture DB, not just that it runs without raising."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, User
from app.recommend_validate import (
    check_duplicate_candidate_keys,
    check_low_confidence_proxies,
    check_model_version,
    check_poor_coverage_candidates,
    check_recipes_missing_meal_categories,
    check_serving_metadata,
    check_unsupported_nutrient_targets,
    run_validation,
)
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_serving_metadata_is_currently_clean():
    # ServingRange.__post_init__ already guarantees this for every
    # CURATED_FOODS entry — this check should therefore always be clean,
    # confirming the defensive check agrees with the dataclass invariant
    assert check_serving_metadata() == []


def test_known_overlap_between_orange_and_orange_juice_is_reported(monkeypatch):
    """"orange" and "orange juice" are both real, intentional CURATED_FOODS
    keys that happen to overlap — resolve_candidate_metadata resolves this
    deterministically (longest key wins, see _longest_matching_key), so
    this is an expected informational finding, not a bug."""
    problems = check_duplicate_candidate_keys()
    assert any("orange" in p and "orange juice" in p for p in problems)


def test_duplicate_key_detection_actually_catches_a_shadowed_pair(monkeypatch):
    import app.recommend_validate as mod
    from app.candidate_metadata import CURATED_FOODS

    fake = dict(CURATED_FOODS)
    # "yogurt" would shadow-match anything "yogurt, greek" also matches
    fake["yogurt"] = next(iter(CURATED_FOODS.values()))
    monkeypatch.setattr(mod, "CURATED_FOODS", fake)

    problems = mod.check_duplicate_candidate_keys()
    assert any("yogurt" in p for p in problems)


def test_no_unsupported_nutrient_targets_today():
    assert check_unsupported_nutrient_targets() == []


def test_unsupported_target_detection_actually_catches_a_bad_entry(monkeypatch):
    import app.recommend_validate as mod
    from app.nutrients import NUTRIENTS, NutrientDef

    fake = dict(NUTRIENTS)
    fake["fake_nutrient"] = NutrientDef(
        name="Fake", unit="g", fdc_nutrient_nbr="999", drv={}, optimisation_eligible=True,
    )
    monkeypatch.setattr(mod, "NUTRIENTS", fake)

    problems = mod.check_unsupported_nutrient_targets()
    assert any("fake_nutrient" in p for p in problems)


def test_recipes_missing_meal_categories_reports_a_count(db):
    user = User(email="a@example.com", password_hash="x")
    db.add(user)
    db.commit()
    db.add(Recipe(user_id=user.id, name="Test Recipe", servings=1))
    db.commit()

    problems = check_recipes_missing_meal_categories(db)
    assert len(problems) == 1
    assert "1 recipe(s)" in problems[0]


def test_recipes_missing_meal_categories_empty_when_no_recipes(db):
    assert check_recipes_missing_meal_categories(db) == []


def test_model_version_is_reported():
    problems = check_model_version()
    assert len(problems) == 1
    assert "RECOMMENDATION_MODEL_VERSION" in problems[0]


def test_poor_coverage_candidate_is_flagged(db):
    # "Lentils" curated food, but the matching DB row only has one
    # tracked nutrient's worth of data — well under half of NUTRIENTS
    food = Food(
        name="Lentils, cooked", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS),
        data_type="sr_legacy_food",
    )
    db.add(food)
    db.flush()
    db.add(FoodNutrient(food_id=food.id, nutrient_key="fiber_total", amount_per_100g=8.0))
    db.commit()

    problems = check_poor_coverage_candidates(db)
    assert any("lentils" in p.lower() for p in problems)


def test_no_matching_food_row_is_silently_skipped(db):
    # an empty catalog: nothing to cross-reference, never a crash
    assert check_poor_coverage_candidates(db) == []


def test_low_confidence_proxy_recipe_is_flagged(db):
    user = User(email="a@example.com", password_hash="x", is_system=True)
    db.add(user)
    db.commit()
    food = Food(
        name="Some ingredient", protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS),
        data_type="sr_legacy_food",
    )
    db.add(food)
    db.flush()
    recipe = Recipe(
        user_id=user.id, name="Low Confidence Soup", servings=1,
        is_public=True, import_slug="low_conf_test", match_coverage_lines=0.3,
    )
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=100))
    db.commit()

    problems = check_low_confidence_proxies(db)
    assert any("Low Confidence Soup" in p for p in problems)


def test_high_confidence_recipe_is_not_flagged(db):
    user = User(email="a@example.com", password_hash="x", is_system=True)
    db.add(user)
    db.commit()
    food = Food(
        name="Some ingredient", protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS),
        data_type="sr_legacy_food",
    )
    db.add(food)
    db.flush()
    recipe = Recipe(
        user_id=user.id, name="High Confidence Soup", servings=1,
        is_public=True, import_slug="high_conf_test", match_coverage_lines=0.95,
    )
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=100))
    db.commit()

    problems = check_low_confidence_proxies(db)
    assert problems == []


def test_run_validation_combines_every_check(db):
    problems = run_validation(db)
    # at minimum the always-present informational model-version line
    assert any("RECOMMENDATION_MODEL_VERSION" in p for p in problems)
