"""API-level tests for prompt 11's safety/eligibility wiring across all
four /api/recommendations/* endpoints — a too-young profile disables the
engine outright, and a stored medical dietary constraint surfaces as a
structured warning rather than being silently ignored."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS

CURRENT_YEAR = datetime.now().year


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


def get_owner_profile_id(client, headers):
    return client.get("/api/profiles", headers=headers).json()[0]["id"]


def set_birth_year(client, headers, profile_id, birth_year):
    client.put(
        f"/api/profiles/{profile_id}",
        json={"name": "Me", "sex": "female", "birth_year": birth_year},
        headers=headers,
    )


def test_child_profile_disables_ingredient_suggestions(client):
    token = register_and_token(client, "a@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 10)

    client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
        headers=headers,
    )
    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"] == []
    assert body["disabled_reason"] is not None
    assert "18" in body["disabled_reason"]


def test_child_profile_disables_recipe_suggestions(client):
    token = register_and_token(client, "b@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 10)

    res = client.get(
        "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"] == []
    assert body["disabled_reason"] is not None


def test_child_profile_disables_pair_suggestions(client):
    token = register_and_token(client, "c@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 10)

    res = client.get(
        "/api/recommendations/pairs", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"] == []
    assert body["disabled_reason"] is not None


def test_child_profile_disables_substitution_suggestions(client):
    token = register_and_token(client, "d@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)

    reg = client.post(
        "/api/recipes",
        json={"name": "Rice bowl", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=headers,
    )
    recipe_id = reg.json()["id"]
    entry = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "recipe_id": recipe_id, "quantity_servings": 1},
        headers=headers,
    )
    entry_id = entry.json()["id"]

    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 10)

    res = client.get(
        "/api/recommendations/substitutions", params={"entry_id": entry_id}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suggestions"] == []
    assert body["disabled_reason"] is not None
    # even disabled, the current recipe being considered is still reported
    assert body["current_recipe_id"] == recipe_id


def test_adult_profile_is_not_disabled(client):
    token = register_and_token(client, "e@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)

    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["disabled_reason"] is None
    assert "data_is_estimate" in body["warnings"]
    assert "absorption_varies" in body["warnings"]


def test_pregnant_profile_gets_pregnancy_warning_on_ingredients(client):
    token = register_and_token(client, "f@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    client.put(
        f"/api/profiles/{profile_id}",
        json={"name": "Me", "sex": "female", "birth_year": CURRENT_YEAR - 30, "is_pregnant": True},
        headers=headers,
    )

    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    assert "pregnancy_conservative" in res.json()["warnings"]


def test_medical_constraint_surfaces_as_warning_not_silently_dropped(client):
    token = register_and_token(client, "g@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)
    client.post(
        f"/api/profiles/{profile_id}/dietary-constraints",
        json={"category": "medical", "note": "renal diet — low potassium"},
        headers=headers,
    )

    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert "medical_constraint_present" in body["warnings"]
    # a medical constraint is a warning, not a disable — this feature just
    # never reads/acts on the note itself (see dietary_filter.py)
    assert body["disabled_reason"] is None


def test_recipe_mode_includes_recipe_variation_warning(client):
    token = register_and_token(client, "h@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)

    res = client.get(
        "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    assert "recipe_nutrients_vary" in res.json()["warnings"]
