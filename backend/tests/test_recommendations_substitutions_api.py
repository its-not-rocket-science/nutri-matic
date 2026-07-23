"""API-level tests for /api/recommendations/substitutions — prompt 8."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, User
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
    rice = Food(id=1, name="White rice, cooked", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    lentils = Food(id=2, name="Lentils", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
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


def test_substitution_suggestions_for_a_logged_recipe(client):
    token = register_and_token(client, "a@example.com")
    headers = auth_headers(token)

    # need the current user's own recipe to log via diary
    create_res = client.post(
        "/api/recipes", json={"name": "Rice Bowl", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=headers,
    )
    recipe_id = create_res.json()["id"]
    client.post(
        "/api/recipes", json={"name": "Lentil Bowl", "servings": 1, "ingredients": [{"food_id": 2, "quantity_g": 224}]},
        headers=headers,
    )

    entry_res = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "recipe_id": recipe_id, "quantity_servings": 1},
        headers=headers,
    )
    entry_id = entry_res.json()["id"]

    res = client.get(
        "/api/recommendations/substitutions", params={"entry_id": entry_id}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["current_recipe_name"] == "Rice Bowl"


def test_plain_food_entry_cannot_be_substituted(client):
    token = register_and_token(client, "b@example.com")
    headers = auth_headers(token)
    entry_res = client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=headers,
    )
    entry_id = entry_res.json()["id"]

    res = client.get("/api/recommendations/substitutions", params={"entry_id": entry_id}, headers=headers)
    assert res.status_code == 422


def test_nonexistent_entry_404s(client):
    token = register_and_token(client, "c@example.com")
    res = client.get(
        "/api/recommendations/substitutions", params={"entry_id": 999999}, headers=auth_headers(token),
    )
    assert res.status_code == 404


def test_requires_authentication(client):
    res = client.get("/api/recommendations/substitutions", params={"entry_id": 1})
    assert res.status_code in (401, 403)
