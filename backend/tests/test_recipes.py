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
    measured = Food(
        id=1,
        name="measured food",
        protein_g_per_100g=20,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 40),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9),
        digestibility_diaas_source="measured",
        digestibility_pdcaas=0.9,
        digestibility_pdcaas_source="measured",
    )
    estimated = Food(
        id=2,
        name="estimated food",
        protein_g_per_100g=20,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 40),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.8),
        digestibility_diaas_source="estimated",
        digestibility_pdcaas=0.8,
        digestibility_pdcaas_source="estimated",
    )
    db.add_all([measured, estimated])
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _add_protein_row(client, food_id, amount_per_100g):
    """Adds a protein FoodNutrient row to this test's isolated in-memory db —
    kept out of the shared fixture so it doesn't affect unrelated tests."""
    db = next(app.dependency_overrides[get_db]())
    db.add(FoodNutrient(food_id=food_id, nutrient_key="protein", amount_per_100g=amount_per_100g))
    db.commit()
    db.close()


def test_recipe_nutrients_includes_personalized_protein_target(client):
    _add_protein_row(client, 1, 20.0)
    token = register_and_token(client, "a@example.com")
    client.put(
        "/api/profile",
        json={
            "sex": "male", "birth_year": 1990, "activity_level": "sedentary",
            "is_pregnant": False, "is_lactating": False, "weight_kg": 70, "height_cm": 175,
        },
        headers=auth_headers(token),
    )
    recipe = client.post(
        "/api/recipes",
        json={"name": "protein test", "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/nutrients", headers=auth_headers(token))
    assert res.status_code == 200
    protein = next(n for n in res.json() if n["key"] == "protein")
    assert protein["amount"] == pytest.approx(20.0)  # 200g @ 20g/100g / 2 servings
    assert protein["adult_drv"] == pytest.approx(56.0)  # sedentary, 70kg: 0.8 * 70
    assert protein["percent_drv"] == pytest.approx(20.0 / 56.0 * 100)
    assert protein["drv_confidence"] == "personalized_calculation"


def test_recipe_nutrients_protein_target_null_when_profile_incomplete(client):
    _add_protein_row(client, 1, 20.0)
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "protein test", "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/nutrients", headers=auth_headers(token))
    protein = next(n for n in res.json() if n["key"] == "protein")
    assert protein["adult_drv"] is None
    assert protein["percent_drv"] is None


def test_recipe_score_all_measured_ingredients_reports_measured(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "measured-only", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/score?method=diaas", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["digestibility_source"] == "measured"


def test_recipe_score_mixed_ingredients_reports_estimated(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={
            "name": "mixed",
            "servings": 1,
            "ingredients": [{"food_id": 1, "quantity_g": 100}, {"food_id": 2, "quantity_g": 100}],
        },
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/score?method=diaas", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["digestibility_source"] == "estimated"

    res_pdcaas = client.get(f"/api/recipes/{recipe['id']}/score?method=pdcaas", headers=auth_headers(token))
    assert res_pdcaas.json()["digestibility_source"] == "estimated"


def test_create_recipe_rejects_empty_ingredients(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/recipes", json={"name": "empty", "servings": 1, "ingredients": []}, headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_create_recipe_rejects_non_positive_servings(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/recipes",
        json={"name": "bad servings", "servings": 0, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_create_recipe_rejects_unknown_food_id(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/recipes",
        json={"name": "bad food", "servings": 1, "ingredients": [{"food_id": 9999, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 422
    assert "9999" in res.json()["detail"]
