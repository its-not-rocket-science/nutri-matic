"""API-level tests for the full score breakdown — hardening prompt 3.
Covers all four suggestion modes: internal consistency (total equals the
sum of the breakdown's components), presence of every named term and the
model version, and that no internal/non-serialisable object leaks
through (every value is a plain JSON number)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, User
from app.reference_patterns import AMINO_ACIDS
from app.recommendation_scoring import RECOMMENDATION_MODEL_VERSION

NUMERIC_BREAKDOWN_FIELDS = (
    "weighted_gap_reduction",
    "multi_nutrient_bonus",
    "protein_quality_benefit",
    "dietary_fit",
    "practicality",
    "upper_limit_penalty",
    "above_preferred_penalty",
    "energy_overshoot_penalty",
    "uncertainty_penalty",
    "implausible_serving_penalty",
    "carbon_footprint_adjustment",
    "glycaemic_load_adjustment",
    "total",
    "model_version",
)
# operational-hardening prompt 3: classification metadata alongside the
# two approximate/opt-in adjustment terms — strings or None, never a
# plain number, so validated separately from NUMERIC_BREAKDOWN_FIELDS
# above.
CLASSIFICATION_BREAKDOWN_FIELDS = (
    "carbon_tier",
    "carbon_confidence",
    "carbon_provenance",
    "glycaemic_tier",
    "glycaemic_confidence",
    "glycaemic_provenance",
    "glycaemic_basis",
)
# PR review: int-or-None, not string-or-None and not "always a real
# number" — must fulfil the "tell a previously-seen classification apart
# from one under a different ruleset" purpose, so validated on its own.
VERSION_BREAKDOWN_FIELDS = (
    "carbon_classification_version",
    "glycaemic_classification_version",
)
BREAKDOWN_FIELDS = NUMERIC_BREAKDOWN_FIELDS + CLASSIFICATION_BREAKDOWN_FIELDS + VERSION_BREAKDOWN_FIELDS


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
    system_user = User(email="stock@example.com", password_hash="x", is_system=True)
    db.add(system_user)
    db.flush()

    rice = Food(id=1, name="White rice, cooked", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    lentils = Food(id=2, name="Lentils", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    yogurt = Food(id=3, name="Yogurt, greek", protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    strawberries = Food(id=4, name="Strawberries, raw", protein_g_per_100g=0.7, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    db.add_all([rice, lentils, yogurt, strawberries])
    db.flush()
    db.add_all([
        FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
        FoodNutrient(food_id=1, nutrient_key="fiber_total", amount_per_100g=0.4),
        FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=0.1),
        FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=1.0),
        FoodNutrient(food_id=1, nutrient_key="vitamin_c", amount_per_100g=0.0),
        FoodNutrient(food_id=2, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=3.3),
        FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=116.0),
        FoodNutrient(food_id=3, nutrient_key="calcium", amount_per_100g=110.0),
        FoodNutrient(food_id=3, nutrient_key="energy", amount_per_100g=59.0),
        FoodNutrient(food_id=4, nutrient_key="vitamin_c", amount_per_100g=59.0),
        FoodNutrient(food_id=4, nutrient_key="energy", amount_per_100g=32.0),
    ])
    recipe = Recipe(user_id=system_user.id, name="Public Lentil Soup", servings=2, is_public=True, import_slug="lentil_soup_test")
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, food_id=2, quantity_g=200))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def owner_profile(client, token):
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    return next(p for p in profiles if p["is_account_owner"])


_BASE_PROFILE_PAYLOAD = {
    "name": "Me",
    "sex": None, "birth_year": None, "activity_level": None,
    "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
}


def _assert_valid_breakdown(breakdown: dict):
    assert set(breakdown.keys()) == set(BREAKDOWN_FIELDS)
    for key in NUMERIC_BREAKDOWN_FIELDS:
        value = breakdown[key]
        assert isinstance(value, (int, float)), f"{key} is not a plain number: {value!r}"
    for key in CLASSIFICATION_BREAKDOWN_FIELDS:
        value = breakdown[key]
        assert value is None or isinstance(value, str), f"{key} is not a string or None: {value!r}"
    for key in VERSION_BREAKDOWN_FIELDS:
        value = breakdown[key]
        assert value is None or isinstance(value, int), f"{key} is not an int or None: {value!r}"
    assert breakdown["model_version"] == RECOMMENDATION_MODEL_VERSION
    # operational-hardening prompt 3's own acceptance criterion: a
    # classification is present exactly when there's real signal to
    # report, independent of whether that signal happened to score as
    # neutral — "medium" carbon/GI tiers are a REAL classification that
    # deliberately contributes 0.0 (see recommendation_scoring.py's
    # _carbon_footprint_adjustment/_glycaemic_load_adjustment: only
    # high/very_high/low tiers move the score; medium is the honest
    # boring middle, not "no data"). So the invariant checked here is
    # "tier present iff confidence/provenance present", NOT "adjustment
    # non-zero iff tier present" — a non-zero adjustment always implies a
    # tier (checked separately below), but the converse doesn't hold.
    if breakdown["carbon_tier"] is None:
        assert breakdown["carbon_confidence"] is None
        assert breakdown["carbon_provenance"] is None
        assert breakdown["carbon_classification_version"] is None
        assert breakdown["carbon_footprint_adjustment"] == 0.0
    else:
        assert breakdown["carbon_confidence"] == "low"
        assert breakdown["carbon_provenance"] in ("name_match", "dominant_ingredient_proxy")
        assert breakdown["carbon_classification_version"] >= 1
    if breakdown["glycaemic_tier"] is None:
        assert breakdown["glycaemic_confidence"] is None
        assert breakdown["glycaemic_provenance"] is None
        assert breakdown["glycaemic_basis"] is None
        assert breakdown["glycaemic_classification_version"] is None
        assert breakdown["glycaemic_load_adjustment"] == 0.0
    else:
        assert breakdown["glycaemic_confidence"] == "low"
        assert breakdown["glycaemic_provenance"] in ("name_match", "dominant_ingredient_proxy")
        assert breakdown["glycaemic_basis"] in ("category_match", "negligible_carbohydrate")
        assert breakdown["glycaemic_classification_version"] >= 1
    expected_total = (
        breakdown["weighted_gap_reduction"]
        + breakdown["multi_nutrient_bonus"]
        + breakdown["protein_quality_benefit"]
        + breakdown["dietary_fit"]
        + breakdown["practicality"]
        + breakdown["carbon_footprint_adjustment"]
        + breakdown["glycaemic_load_adjustment"]
        - breakdown["upper_limit_penalty"]
        - breakdown["above_preferred_penalty"]
        - breakdown["energy_overshoot_penalty"]
        - breakdown["uncertainty_penalty"]
        - breakdown["implausible_serving_penalty"]
    )
    assert breakdown["total"] == pytest.approx(expected_total)


def test_ingredient_suggestion_score_breakdown(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )
    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"], "fixture must produce at least one suggestion to test"
    suggestion = body["suggestions"][0]
    assert "score" in suggestion
    assert "score_breakdown" in suggestion
    assert suggestion["score_breakdown"]["total"] == pytest.approx(suggestion["score"])
    _assert_valid_breakdown(suggestion["score_breakdown"])


def test_ingredient_suggestion_carbon_and_glycaemic_classification_end_to_end(client):
    """operational-hardening prompt 3: with reduce_carbon_footprint/
    blood_sugar_stability actually active on the profile, the real HTTP
    JSON response must carry real, non-None classification metadata —
    not just the correct schema shape (already covered above, where no
    goal is active and every field is legitimately None)."""
    token = register_and_token(client, "carbon-e2e@example.com")
    owner = owner_profile(client, token)
    client.put(
        f"/api/profiles/{owner['id']}",
        json={**_BASE_PROFILE_PAYLOAD, "goals": ["reduce_carbon_footprint", "blood_sugar_stability"]},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )
    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    lentils = next((s for s in body["suggestions"] if s["food_name"] == "Lentils"), None)
    assert lentils is not None, "Lentils must be suggested to exercise a real classification"
    breakdown = lentils["score_breakdown"]
    assert breakdown["carbon_tier"] == "low"
    assert breakdown["carbon_confidence"] == "low"
    assert breakdown["carbon_provenance"] == "name_match"
    assert breakdown["carbon_classification_version"] >= 1
    assert breakdown["glycaemic_tier"] == "low"
    assert breakdown["glycaemic_confidence"] == "low"
    assert breakdown["glycaemic_provenance"] == "name_match"
    assert breakdown["glycaemic_basis"] == "category_match"
    assert breakdown["glycaemic_classification_version"] >= 1


def test_recipe_suggestion_score_breakdown(client):
    token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )
    res = client.get(
        "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"], "fixture must produce at least one suggestion to test"
    suggestion = body["suggestions"][0]
    assert suggestion["score_breakdown"]["total"] == pytest.approx(suggestion["score"])
    _assert_valid_breakdown(suggestion["score_breakdown"])


def test_substitution_suggestion_score_breakdown(client):
    token = register_and_token(client, "c@example.com")
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
        "/api/recommendations/substitutions", params={"entry_id": entry["id"]}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"], "fixture must produce at least one suggestion to test"
    suggestion = body["suggestions"][0]
    assert suggestion["score_breakdown"]["total"] == pytest.approx(suggestion["score"])
    _assert_valid_breakdown(suggestion["score_breakdown"])


def test_pair_suggestion_score_breakdown(client):
    token = register_and_token(client, "d@example.com")
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    res = client.get(
        "/api/recommendations/pairs",
        params={"entry_date": "2026-01-01", "priority_nutrients": "calcium,vitamin_c"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"], "fixture must produce at least one suggestion to test"
    suggestion = body["suggestions"][0]
    assert suggestion["score_breakdown"]["total"] == pytest.approx(suggestion["score"])
    _assert_valid_breakdown(suggestion["score_breakdown"])
    # first/second's own solo_score stay bare floats, never a full breakdown
    assert isinstance(suggestion["first"]["solo_score"], (int, float))
    assert "score_breakdown" not in suggestion["first"]
    assert "score_breakdown" not in suggestion["second"]
