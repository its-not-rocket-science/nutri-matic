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
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
    rice_white = Food(id=1, name="Rice, white, cooked", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    rice_brown = Food(id=2, name="Rice, brown, cooked", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    spinach = Food(id=3, name="Spinach, raw", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add_all([rice_white, rice_brown, spinach])
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=1.0),
            FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
            FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=2.0),
            FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=130.0),
            FoodNutrient(food_id=3, nutrient_key="iron", amount_per_100g=3.0),
            FoodNutrient(food_id=3, nutrient_key="energy", amount_per_100g=20.0),
        ]
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_meal_optimize_returns_ranked_suggestions(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["meal"] == "lunch"
    assert body["target_nutrient_key"] == "iron"
    # swap (rice white -> brown), add spinach, and add brown rice (a
    # genuinely different action from the swap — keep the white rice AND
    # add brown rice, vs. replace it) are all real, distinct, computed
    # improvements
    assert len(body["suggestions"]) == 3

    swap = next(s for s in body["suggestions"] if s["action"] == "swap")
    assert swap["food_name"] == "Rice, brown, cooked"
    assert swap["replaces_food_name"] == "Rice, white, cooked"

    add_spinach = next(s for s in body["suggestions"] if s["action"] == "add" and s["food_name"] == "Spinach, raw")
    assert add_spinach["quantity_g"] == pytest.approx(30.0)

    # the food already in this meal (white rice) is never suggested as an
    # "add" candidate — that's just "log more of what you already have"
    assert all(
        not (s["action"] == "add" and s["food_name"] == "Rice, white, cooked") for s in body["suggestions"]
    )

    # swap has no calorie cost (same energy), so it should rank above the add
    assert body["suggestions"][0]["action"] == "swap"


def test_meal_optimize_none_when_meal_empty(client):
    token = register_and_token(client, "a@example.com")
    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    assert res.status_code == 200
    assert res.json() is None


def test_meal_optimize_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(other_token)
    )
    assert res.json() is None
