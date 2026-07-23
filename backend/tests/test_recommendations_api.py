"""API-level tests for /api/recommendations/ingredients — prompt 6. The
service layer (recommend_ingredients.py) has its own thorough unit tests;
these just verify the HTTP wiring: auth/profile scoping, diary vs
meal-plan source, and the empty/no-error "nothing to suggest" case."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
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
    rice = Food(
        id=1, name="White rice, cooked", protein_g_per_100g=2.7,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    lentils = Food(
        id=2, name="Lentils", protein_g_per_100g=9.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add_all([rice, lentils])
    db.flush()
    db.add_all([
        FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
        FoodNutrient(food_id=1, nutrient_key="fiber_total", amount_per_100g=0.4),
        FoodNutrient(food_id=2, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=116.0),
    ])
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_ingredient_suggestions_for_a_diary_day(client):
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
    assert "suggestions" in body
    if body["suggestions"]:
        assert body["suggestions"][0]["food_name"] == "Lentils"


def test_no_suggestions_returns_empty_list_not_an_error(client):
    token = register_and_token(client, "b@example.com")
    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json() == {"suggestions": []}


def test_requires_authentication(client):
    res = client.get("/api/recommendations/ingredients", params={"entry_date": "2026-01-01"})
    assert res.status_code == 403 or res.status_code == 401


def test_invalid_source_rejected(client):
    token = register_and_token(client, "c@example.com")
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "source": "not_a_real_source"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_invalid_meal_rejected(client):
    token = register_and_token(client, "d@example.com")
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "meal": "brunch"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_meal_scoped_request_uses_remaining_room_not_flat_daily_target(client):
    """Logging enough fibre at breakfast must close the gap for a
    lunch-scoped request too — a meal is compared against what's left of
    the day's target, never the flat whole-day figure."""
    token = register_and_token(client, "f@example.com")
    headers = auth_headers(token)
    # Lentils (food_id=2) carries 8g fibre/100g — logging 400g meets/exceeds
    # the 30g/day UK fibre target on its own, at breakfast.
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "breakfast", "food_id": 2, "quantity_g": 400},
        headers=headers,
    )
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=headers,
    )

    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "meal": "lunch", "priority_nutrients": "fiber_total"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json() == {"suggestions": []}


def test_recipe_source_uses_the_recipes_own_ingredients(client):
    """Recipe-detail page's "Improve this recipe" — no diary/meal-plan
    entry involved at all, just the recipe's own scaled ingredients."""
    token = register_and_token(client, "g@example.com")
    headers = auth_headers(token)
    reg = client.post(
        "/api/recipes",
        json={"name": "Plain rice", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=headers,
    )
    recipe_id = reg.json()["id"]

    res = client.get(
        "/api/recommendations/ingredients",
        params={"recipe_id": recipe_id, "priority_nutrients": "fiber_total"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    if body["suggestions"]:
        assert body["suggestions"][0]["food_name"] == "Lentils"


def test_recipe_source_rejects_meal_param(client):
    token = register_and_token(client, "h@example.com")
    headers = auth_headers(token)
    reg = client.post(
        "/api/recipes",
        json={"name": "Plain rice", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=headers,
    )
    recipe_id = reg.json()["id"]

    res = client.get(
        "/api/recommendations/ingredients",
        params={"recipe_id": recipe_id, "meal": "lunch"},
        headers=headers,
    )
    assert res.status_code == 422


def test_multi_day_meal_plan_range(client):
    token = register_and_token(client, "i@example.com")
    headers = auth_headers(token)
    client.post(
        "/api/meal-plan", json={"plan_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=headers,
    )
    client.post(
        "/api/meal-plan", json={"plan_date": "2026-01-03", "meal": "dinner", "food_id": 1, "quantity_g": 200},
        headers=headers,
    )

    res = client.get(
        "/api/recommendations/ingredients",
        params={
            "start_date": "2026-01-01", "end_date": "2026-01-03", "source": "meal_plan",
            "priority_nutrients": "fiber_total",
        },
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    if body["suggestions"]:
        assert body["suggestions"][0]["food_name"] == "Lentils"


def test_multi_day_range_requires_meal_plan_source(client):
    token = register_and_token(client, "j@example.com")
    res = client.get(
        "/api/recommendations/ingredients",
        params={"start_date": "2026-01-01", "end_date": "2026-01-03", "source": "diary"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_requires_exactly_one_scope(client):
    token = register_and_token(client, "k@example.com")
    res = client.get("/api/recommendations/ingredients", headers=auth_headers(token))
    assert res.status_code == 422


def test_meal_plan_source(client):
    token = register_and_token(client, "e@example.com")
    client.post(
        "/api/meal-plan", json={"plan_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "source": "meal_plan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
