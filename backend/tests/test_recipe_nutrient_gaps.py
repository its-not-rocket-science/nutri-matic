"""Prompt 5.1: GET /api/recipes/{id}/nutrient-gaps — a recipe's most
significant nutrient shortfalls, one serving compared against a typical
daily target. Reuses nutrient_gap_analysis.py/nutrient_targets.py (the
same canonical service /api/recommendations/*'s "Improve this recipe"
already uses), not a second gap-finding implementation."""

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
    # low iron, low calcium, high vitamin C -- deliberately below/near
    # target for two nutrients, comfortably above for a third
    rice = Food(id=1, name="Rice, white, cooked", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add(rice)
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=0.2),
            FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=1.0),
            FoodNutrient(food_id=1, nutrient_key="vitamin_c", amount_per_100g=500.0),
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


def create_recipe(client, token, servings=2, quantity_g=100):
    res = client.post(
        "/api/recipes",
        json={"name": "Plain rice", "servings": servings, "ingredients": [{"food_id": 1, "quantity_g": quantity_g}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    return res.json()


def test_returns_below_target_nutrients_sorted_by_weight(client):
    token = register_and_token(client, "a@example.com")
    set_owner_sex(client, token)
    recipe = create_recipe(client, token)

    res = client.get(f"/api/recipes/{recipe['id']}/nutrient-gaps", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    keys = [g["key"] for g in body]
    assert "iron" in keys
    assert "calcium" in keys
    for g in body:
        assert g["status"] in ("below_target", "near_target")


def test_excludes_nutrients_already_at_or_above_target(client):
    token = register_and_token(client, "a@example.com")
    set_owner_sex(client, token)
    recipe = create_recipe(client, token)

    res = client.get(f"/api/recipes/{recipe['id']}/nutrient-gaps", headers=auth_headers(token))
    keys = [g["key"] for g in res.json()]
    assert "vitamin_c" not in keys  # 500mg/100g, well above any daily target


def test_respects_limit(client):
    token = register_and_token(client, "a@example.com")
    set_owner_sex(client, token)
    recipe = create_recipe(client, token)

    res = client.get(f"/api/recipes/{recipe['id']}/nutrient-gaps?limit=1", headers=auth_headers(token))
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_reflects_one_serving_not_the_whole_recipe(client):
    """2 servings, 100g rice total -> 50g/serving -> 0.1mg iron/serving,
    not the full-batch 0.2mg. Confirms scale_recipe_ingredients divides
    down to 1 serving, not the recipe's raw stored ingredient quantity."""
    token = register_and_token(client, "a@example.com")
    set_owner_sex(client, token)
    recipe = create_recipe(client, token, servings=2, quantity_g=100)

    res = client.get(f"/api/recipes/{recipe['id']}/nutrient-gaps", headers=auth_headers(token))
    iron = next(g for g in res.json() if g["key"] == "iron")
    assert iron["consumed_amount"] == pytest.approx(0.1)


def test_empty_list_for_recipe_with_no_ingredients_data():
    """A recipe whose only food has no nutrient rows at all -> nothing to
    aggregate -> empty list, not an error."""
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
    recipe = create_recipe(client, token)

    res = client.get(f"/api/recipes/{recipe['id']}/nutrient-gaps", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json() == []

    app.dependency_overrides.clear()


def test_inaccessible_recipe_404s(client):
    owner_token = register_and_token(client, "owner@example.com")
    set_owner_sex(client, owner_token)
    recipe = create_recipe(client, owner_token)

    other_token = register_and_token(client, "other@example.com")
    res = client.get(f"/api/recipes/{recipe['id']}/nutrient-gaps", headers=auth_headers(other_token))
    assert res.status_code == 404
