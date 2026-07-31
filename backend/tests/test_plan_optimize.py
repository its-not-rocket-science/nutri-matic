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
    # No FoodNutrient rows at all — aggregate_nutrients only ever populates
    # a key from an actual FoodNutrient row (protein_g_per_100g isn't one of
    # its inputs), so a plan built only from this food produces an empty
    # nutrients_out and _find_worst_gap has no candidate to return. Used by
    # test_plan_optimize_none_when_entries_exist_but_no_computable_gap.
    no_data_food = Food(id=4, name="Undocumented food", protein_g_per_100g=5.0, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add_all([rice_white, rice_brown, spinach, no_data_food])
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


def test_plan_optimize_returns_ranked_suggestions_across_the_week(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-15", "meal": "dinner", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/meal-plan/optimize?start_date=2026-07-13&end_date=2026-07-19", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["start_date"] == "2026-07-13"
    assert body["end_date"] == "2026-07-19"
    assert body["target_nutrient_key"] == "iron"
    assert len(body["suggestions"]) > 0


def test_plan_optimize_none_when_no_entries(client):
    token = register_and_token(client, "a@example.com")
    res = client.get(
        "/api/meal-plan/optimize?start_date=2026-07-13&end_date=2026-07-19", headers=auth_headers(token)
    )
    assert res.status_code == 200
    assert res.json() is None


def test_plan_optimize_none_when_entries_exist_but_no_computable_gap(client):
    """Prompt 1.2: GET /api/meal-plan/optimize returns None for two
    genuinely different reasons — no entries in range (see
    test_plan_optimize_none_when_no_entries), or entries exist but there's
    no computable gap to target. Both are correct, by-design responses;
    this pins down the second one specifically so the frontend fix that
    tells them apart doesn't silently start conflating them again."""
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 4, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/meal-plan/optimize?start_date=2026-07-13&end_date=2026-07-19", headers=auth_headers(token)
    )
    assert res.status_code == 200
    assert res.json() is None


def test_plan_optimize_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/meal-plan/optimize?start_date=2026-07-13&end_date=2026-07-19", headers=auth_headers(other_token)
    )
    assert res.json() is None


def test_plan_optimize_respects_max_additional_cost(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.put(
        "/api/food-prices/3",
        json={"package_price": 100.0, "package_quantity_g": 100.0},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/meal-plan/optimize?start_date=2026-07-13&end_date=2026-07-19&max_additional_cost=1.0",
        headers=auth_headers(token),
    )
    body = res.json()
    assert all(s["food_name"] != "Spinach, raw" for s in body["suggestions"])
