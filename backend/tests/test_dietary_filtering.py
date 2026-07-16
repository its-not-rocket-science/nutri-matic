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
    db.add_all(
        [
            Food(
                id=1, name="Peanut butter, smooth", protein_g_per_100g=25,
                amino_acids=dict.fromkeys(AMINO_ACIDS, 15),
            ),
            Food(
                id=2, name="Almond butter", protein_g_per_100g=21,
                amino_acids=dict.fromkeys(AMINO_ACIDS, 14),
            ),
            Food(
                id=3, name="Beef, ground, cooked", protein_g_per_100g=26,
                amino_acids=dict.fromkeys(AMINO_ACIDS, 20),
            ),
        ]
    )
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=5.0),
            FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=3.5),
            FoodNutrient(food_id=3, nutrient_key="iron", amount_per_100g=2.6),
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


def add_peanut_allergy(client, token):
    res = client.post(
        "/api/profile/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude", "note": None},
        headers=auth_headers(token),
    )
    assert res.status_code == 201


def test_search_by_name_excludes_hard_allergen_when_authenticated(client):
    token = register_and_token(client, "a@example.com")
    add_peanut_allergy(client, token)

    res = client.get("/api/foods/search-by-name?q=butter", headers=auth_headers(token))
    assert res.status_code == 200
    names = [f["name"] for f in res.json()]
    assert "Peanut butter, smooth" not in names
    assert "Almond butter" in names


def test_search_by_name_unfiltered_when_anonymous(client):
    res = client.get("/api/foods/search-by-name?q=butter")
    assert res.status_code == 200
    names = [f["name"] for f in res.json()]
    assert "Peanut butter, smooth" in names


def test_search_by_name_unfiltered_for_user_with_no_constraints(client):
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/foods/search-by-name?q=butter", headers=auth_headers(token))
    names = [f["name"] for f in res.json()]
    assert "Peanut butter, smooth" in names


def test_nutrient_search_excludes_hard_allergen(client):
    token = register_and_token(client, "a@example.com")
    add_peanut_allergy(client, token)

    res = client.post(
        "/api/foods/search",
        json={"filters": [{"key": "iron", "op": "gte", "value": 0}], "limit": 20},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    names = [f["name"] for f in res.json()]
    assert "Peanut butter, smooth" not in names
    assert "Almond butter" in names


def test_vegan_pattern_excludes_meat_not_plant_foods(client):
    token = register_and_token(client, "a@example.com")

    client.put(
        "/api/profile",
        json={
            "sex": None, "birth_year": None, "activity_level": None,
            "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
            "dietary_pattern": "vegan",
        },
        headers=auth_headers(token),
    )

    res = client.get("/api/foods/search-by-name?q=beef", headers=auth_headers(token))
    names = [f["name"] for f in res.json()]
    assert "Beef, ground, cooked" not in names

    res2 = client.get("/api/foods/search-by-name?q=almond", headers=auth_headers(token))
    names2 = [f["name"] for f in res2.json()]
    assert "Almond butter" in names2


def test_recipe_search_excludes_recipe_with_hard_excluded_ingredient(client):
    token = register_and_token(client, "a@example.com")
    add_peanut_allergy(client, token)

    client.post(
        "/api/recipes",
        json={"name": "PB snack", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 30}]},
        headers=auth_headers(token),
    )
    client.post(
        "/api/recipes",
        json={"name": "Almond snack", "servings": 1, "ingredients": [{"food_id": 2, "quantity_g": 30}]},
        headers=auth_headers(token),
    )

    res = client.post(
        "/api/recipes/search",
        json={"filters": [], "limit": 20},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    names = [r["name"] for r in res.json()]
    assert "PB snack" not in names
    assert "Almond snack" in names
