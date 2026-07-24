"""API-level tests for hardening prompt 4's provenance/mapping-confidence
exposure — quality_summary and robustness_model_version on recipe and
substitution suggestions, and fdc_id/data_type/candidate_source on
ingredient suggestions. Covers exact, regional, analogue, proxy,
fallback-resolved, mixed-quality, missing-robustness, and legacy-null
cases at the real HTTP response level."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, RecipeIngredientProvenance, RobustnessResult, User
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSession()
    system_user = User(id=1, email="stock@example.com", password_hash="x", is_system=True)
    db.add(system_user)
    db.flush()

    rice = Food(
        id=1, name="White rice, cooked", protein_g_per_100g=2.7, fdc_id=169756,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    lentils = Food(
        id=2, name="Lentils", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    # distinct foods for the mixed-quality/legacy-null recipes below — the
    # recipe suggestion diversity rule dedupes by primary ingredient, so
    # three recipes all built from the same "Lentils" food would collapse
    # to just the highest-scoring one, hiding the other two scenarios
    lentils_mixed = Food(
        id=3, name="Lentils Mixed", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    lentils_legacy = Food(
        id=4, name="Lentils Legacy", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add_all([rice, lentils, lentils_mixed, lentils_legacy])
    db.flush()
    db.add_all([
        FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
        FoodNutrient(food_id=1, nutrient_key="fiber_total", amount_per_100g=0.4),
        FoodNutrient(food_id=2, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=116.0),
        FoodNutrient(food_id=3, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=3, nutrient_key="energy", amount_per_100g=116.0),
        FoodNutrient(food_id=4, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=4, nutrient_key="energy", amount_per_100g=116.0),
    ])

    # exact-match, high-robustness stock recipe
    exact_recipe = Recipe(
        id=1, user_id=system_user.id, name="Exact Lentil Soup", servings=2,
        is_public=True, import_slug="exact_test", match_coverage_lines=1.0, match_coverage_mass=1.0,
    )
    db.add(exact_recipe)
    db.flush()
    exact_ing = RecipeIngredient(recipe_id=exact_recipe.id, food_id=2, quantity_g=200)
    db.add(exact_ing)
    db.flush()
    db.add(RecipeIngredientProvenance(
        recipe_ingredient_id=exact_ing.id, raw_text="200g lentils",
        match_method="alias", match_relationship="exact", match_confidence=1.0,
    ))
    db.add(RobustnessResult(
        recipe_id=exact_recipe.id, is_latest=True, model_version="1.2.0", simulation_count=200, random_seed=1,
        metrics={}, overall_rating=5, overall_explanation="high robustness",
    ))

    # mixed-quality stock recipe: regional + analogue + proxy + fallback, no robustness row
    mixed_recipe = Recipe(
        id=2, user_id=system_user.id, name="Mixed Quality Soup", servings=2,
        is_public=True, import_slug="mixed_test", match_coverage_lines=0.75, match_coverage_mass=0.7,
    )
    db.add(mixed_recipe)
    db.flush()
    mixed_ing_a = RecipeIngredient(recipe_id=mixed_recipe.id, food_id=3, quantity_g=100)
    mixed_ing_b = RecipeIngredient(recipe_id=mixed_recipe.id, food_id=3, quantity_g=100)
    db.add_all([mixed_ing_a, mixed_ing_b])
    db.flush()
    db.add(RecipeIngredientProvenance(
        recipe_ingredient_id=mixed_ing_a.id, raw_text="regional lentils",
        match_method="alias", match_relationship="regional_equivalent", match_confidence=0.85,
    ))
    db.add(RecipeIngredientProvenance(
        recipe_ingredient_id=mixed_ing_b.id, raw_text="proxy lentils",
        match_method="alias", match_relationship="category_proxy", match_confidence=0.3,
        match_used_fallback=True,
    ))

    # legacy-null stock recipe: import_slug set (a real stock recipe) but
    # no RecipeIngredientProvenance rows at all — imported before
    # per-ingredient provenance tracking existed
    legacy_recipe = Recipe(
        id=3, user_id=system_user.id, name="Legacy Null Soup", servings=2,
        is_public=True, import_slug="legacy_test",
    )
    db.add(legacy_recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=legacy_recipe.id, food_id=4, quantity_g=200))

    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _get_recipe_suggestions(client, headers, entry_date="2026-01-01"):
    client.post(
        "/api/diary", json={"entry_date": entry_date, "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=headers,
    )
    res = client.get(
        "/api/recommendations/recipes", params={"entry_date": entry_date, "max_suggestions": 10}, headers=headers,
    )
    assert res.status_code == 200
    return {s["recipe_name"]: s for s in res.json()["suggestions"]}


def test_exact_match_recipe_quality_summary(client):
    token = register_and_token(client, "a@example.com")
    by_name = _get_recipe_suggestions(client, auth_headers(token))
    assert "Exact Lentil Soup" in by_name
    summary = by_name["Exact Lentil Soup"]["quality_summary"]
    assert summary["exact_or_regional_count"] == 1
    assert summary["proportion_exact_or_regional"] == 1.0
    assert summary["analogue_count"] == 0
    assert summary["proxy_or_reviewed_count"] == 0


def test_high_robustness_recipe_reports_rating_and_model_version(client):
    token = register_and_token(client, "b@example.com")
    by_name = _get_recipe_suggestions(client, auth_headers(token))
    suggestion = by_name["Exact Lentil Soup"]
    assert suggestion["robustness_rating"] == 5
    assert suggestion["robustness_model_version"] == "1.2.0"


def test_mixed_quality_recipe_reports_regional_analogue_and_proxy(client):
    token = register_and_token(client, "c@example.com")
    by_name = _get_recipe_suggestions(client, auth_headers(token))
    assert "Mixed Quality Soup" in by_name
    summary = by_name["Mixed Quality Soup"]["quality_summary"]
    assert summary["exact_or_regional_count"] == 1  # regional_equivalent
    assert summary["proxy_or_reviewed_count"] == 1  # category_proxy
    assert summary["fallback_resolution_count"] == 1
    assert summary["unresolved_or_low_confidence_count"] == 1  # the 0.3-confidence proxy


def test_mixed_quality_recipe_has_no_robustness_row(client):
    """Missing-robustness case: a recipe with no RobustnessResult row at
    all must report rating/model_version as null, never fabricated."""
    token = register_and_token(client, "d@example.com")
    by_name = _get_recipe_suggestions(client, auth_headers(token))
    suggestion = by_name["Mixed Quality Soup"]
    assert suggestion["robustness_rating"] is None
    assert suggestion["robustness_model_version"] is None


def test_legacy_null_recipe_reports_unmapped_ingredients_gracefully(client):
    """A stock recipe (import_slug set) with zero RecipeIngredientProvenance
    rows at all — imported before per-ingredient provenance tracking
    existed. Must never crash and never fabricate a confidence figure."""
    token = register_and_token(client, "e@example.com")
    by_name = _get_recipe_suggestions(client, auth_headers(token))
    assert "Legacy Null Soup" in by_name
    summary = by_name["Legacy Null Soup"]["quality_summary"]
    assert summary["unmapped_count"] == 1
    assert summary["exact_or_regional_count"] == 0
    assert summary["min_mapping_confidence"] is None
    assert summary["weighted_mapping_confidence"] is None
    assert summary["proportion_exact_or_regional"] is None


def test_ingredient_suggestion_reports_fdc_id_and_data_type(client):
    token = register_and_token(client, "f@example.com")
    headers = auth_headers(token)
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=headers,
    )
    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"]
    suggestion = body["suggestions"][0]
    assert suggestion["food_name"] == "Lentils"
    assert suggestion["fdc_id"] is None  # Lentils fixture has no fdc_id set
    assert suggestion["data_type"] == "sr_legacy_food"
    assert suggestion["candidate_source"] == "curated"


def test_substitution_reports_quality_summary_and_robustness_version(client):
    token = register_and_token(client, "g@example.com")
    headers = auth_headers(token)
    rice_recipe = client.post(
        "/api/recipes", json={"name": "Rice Bowl", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=headers,
    ).json()
    entry = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "recipe_id": rice_recipe["id"], "quantity_servings": 1},
        headers=headers,
    ).json()

    res = client.get(
        "/api/recommendations/substitutions",
        params={"entry_id": entry["id"], "max_suggestions": 10},
        headers=headers,
    )
    assert res.status_code == 200
    by_name = {s["replacement_recipe_name"]: s for s in res.json()["suggestions"]}
    if "Exact Lentil Soup" in by_name:
        suggestion = by_name["Exact Lentil Soup"]
        assert suggestion["robustness_model_version"] == "1.2.0"
        assert suggestion["quality_summary"]["exact_or_regional_count"] == 1
