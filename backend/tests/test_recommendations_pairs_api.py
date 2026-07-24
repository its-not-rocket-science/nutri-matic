"""API-level test for /api/recommendations/pairs — prompt 9."""

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
    rice = Food(id=1, name="White rice, cooked", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    yogurt = Food(id=2, name="Yogurt, greek", protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    berries = Food(id=3, name="Strawberries, raw", protein_g_per_100g=0.7, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    db.add_all([rice, yogurt, berries])
    db.flush()
    db.add_all([
        FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
        FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=1.0),
        FoodNutrient(food_id=2, nutrient_key="calcium", amount_per_100g=110.0),
        FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=59.0),
        FoodNutrient(food_id=3, nutrient_key="vitamin_c", amount_per_100g=59.0),
        FoodNutrient(food_id=3, nutrient_key="energy", amount_per_100g=32.0),
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


def test_pair_suggestions_for_a_diary_day(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/recommendations/pairs",
        params={"entry_date": "2026-01-01", "priority_nutrients": "calcium,vitamin_c"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    if body["suggestions"]:
        names = {body["suggestions"][0]["first"]["food_name"], body["suggestions"][0]["second"]["food_name"]}
        assert names == {"Yogurt, greek", "Strawberries, raw"}


def test_no_suggestions_returns_empty_list(client):
    token = register_and_token(client, "b@example.com")
    res = client.get(
        "/api/recommendations/pairs", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"] == []
    assert body["disabled_reason"] is None


def test_requires_authentication(client):
    res = client.get("/api/recommendations/pairs", params={"entry_date": "2026-01-01"})
    assert res.status_code in (401, 403)
