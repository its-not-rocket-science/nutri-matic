"""API-level tests for /api/recommendations/recipes — prompt 7."""

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
    system_user = User(email="stock@example.com", password_hash="x", is_system=True)
    db.add(system_user)
    db.flush()

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
    recipe = Recipe(user_id=system_user.id, name="Public Lentil Soup", servings=2, is_public=True)
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


def test_recipe_suggestions_for_a_diary_day(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    if body["suggestions"]:
        assert body["suggestions"][0]["recipe_name"] == "Public Lentil Soup"
        assert body["suggestions"][0]["is_stock"] is True


def test_no_suggestions_returns_empty_list(client):
    token = register_and_token(client, "b@example.com")
    res = client.get(
        "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json() == {"suggestions": []}


def test_invalid_goal_rejected(client):
    token = register_and_token(client, "c@example.com")
    res = client.get(
        "/api/recommendations/recipes",
        params={"entry_date": "2026-01-01", "goal": "not_a_real_goal"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_requires_authentication(client):
    res = client.get("/api/recommendations/recipes", params={"entry_date": "2026-01-01"})
    assert res.status_code in (401, 403)
