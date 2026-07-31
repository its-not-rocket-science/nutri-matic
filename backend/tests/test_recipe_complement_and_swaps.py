"""Prompt 5.2: recipe-level complementary-ingredient and same-family
ingredient-swap suggestions. Both reuse existing engines rather than new
scoring logic — complement.suggest_complements (generalized from a
single food to a recipe's own scoreable ingredient mix) and optimizer.
suggest_meal_optimizations (the same "swap" scoring gap-suggestions/
meal-optimize/plan-optimize already use)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS


def _aa(lysine: float, others: float = 100.0) -> dict:
    return {aa: (lysine if aa == "lysine" else others) for aa in AMINO_ACIDS}


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
    # low-lysine grain (limiting amino acid = lysine) for complement tests
    grain = Food(
        id=1, name="Rice, white, cooked", protein_g_per_100g=20, amino_acids=_aa(lysine=20),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9),
    )
    # high-lysine complement candidate
    beans = Food(
        id=2, name="Beans, black, cooked", protein_g_per_100g=20, amino_acids=_aa(lysine=200),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9),
    )
    # low-iron ingredient for swap tests, plus a SAME-FAMILY (optimizer.py's
    # swap candidates are matched by the "Name, ..." prefix before the
    # first comma — "Rice" here) high-iron swap candidate
    low_iron = Food(id=3, name="Rice, brown, cooked", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    high_iron = Food(id=4, name="Rice, wild, cooked", protein_g_per_100g=4, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add_all([grain, beans, low_iron, high_iron])
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=3, nutrient_key="iron", amount_per_100g=0.1),
            FoodNutrient(food_id=4, nutrient_key="iron", amount_per_100g=8.0),
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


def set_owner_sex(client, token, sex="female"):
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    owner = next(p for p in profiles if p["is_account_owner"])
    client.put(
        f"/api/profiles/{owner['id']}",
        json={
            "name": owner["name"], "sex": sex, "birth_year": None, "activity_level": None,
            "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
        },
        headers=auth_headers(token),
    )


# --- complement (5.2a) ---------------------------------------------------


def test_recipe_complement_suggests_real_pairing(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "Rice", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/complement?method=diaas", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["limiting_amino_acid"] == "lysine"
    names = [s["food_name"] for s in body["suggestions"]]
    assert "Beans, black, cooked" in names


def test_recipe_complement_excludes_recipes_own_ingredients(client):
    """Shouldn't suggest re-adding a food already in the recipe."""
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={
            "name": "Rice and beans", "servings": 1,
            "ingredients": [{"food_id": 1, "quantity_g": 100}, {"food_id": 2, "quantity_g": 100}],
        },
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/complement?method=diaas", headers=auth_headers(token))
    names = [s["food_name"] for s in res.json()["suggestions"]]
    assert "Beans, black, cooked" not in names


def test_recipe_complement_404_for_inaccessible_recipe(client):
    owner_token = register_and_token(client, "owner@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "Rice", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(owner_token),
    ).json()

    other_token = register_and_token(client, "other@example.com")
    res = client.get(f"/api/recipes/{recipe['id']}/complement", headers=auth_headers(other_token))
    assert res.status_code == 404


# --- ingredient swaps (5.2b) ----------------------------------------------


def test_ingredient_swap_suggests_higher_iron_alternative(client):
    token = register_and_token(client, "a@example.com")
    set_owner_sex(client, token)
    recipe = client.post(
        "/api/recipes",
        json={"name": "Rice bowl", "servings": 1, "ingredients": [{"food_id": 3, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/ingredient-swaps", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert len(body) > 0
    swap = body[0]
    assert swap["action"] == "swap"
    assert swap["replaces_food_id"] == 3
    assert swap["food_id"] == 4
    assert swap["after_percent_drv"] > swap["before_percent_drv"]


def test_ingredient_swap_empty_for_recipe_with_no_ingredients_data():
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
    db.add(Food(id=1, name="Undocumented food", protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS, None)))
    db.commit()
    db.close()

    client = TestClient(app)
    token = register_and_token(client, "a@example.com")
    set_owner_sex(client, token)
    recipe = client.post(
        "/api/recipes",
        json={"name": "Mystery", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/ingredient-swaps", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json() == []

    app.dependency_overrides.clear()


def test_ingredient_swap_404_for_inaccessible_recipe(client):
    owner_token = register_and_token(client, "owner@example.com")
    set_owner_sex(client, owner_token)
    recipe = client.post(
        "/api/recipes",
        json={"name": "Rice bowl", "servings": 1, "ingredients": [{"food_id": 3, "quantity_g": 100}]},
        headers=auth_headers(owner_token),
    ).json()

    other_token = register_and_token(client, "other@example.com")
    res = client.get(f"/api/recipes/{recipe['id']}/ingredient-swaps", headers=auth_headers(other_token))
    assert res.status_code == 404
