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


def test_recipe_absorbed_protein_per_serving(client):
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
        json={"name": "absorbed test", "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/absorbed-protein", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    # 200g @ 20g/100g protein = 40g total, / 2 servings = 20g/serving
    assert body["total_protein_g"] == pytest.approx(20.0)
    # food id=1 ("measured") has uniform 0.9 digestibility for both methods
    assert body["diaas_absorbed_g"] == pytest.approx(18.0)
    assert body["pdcaas_absorbed_g"] == pytest.approx(18.0)
    assert body["target_g"] == pytest.approx(56.0)  # sedentary, 70kg: 0.8 * 70
    assert body["diaas_percent_drv"] == pytest.approx(18.0 / 56.0 * 100)
    assert body["pdcaas_percent_drv"] == pytest.approx(18.0 / 56.0 * 100)


def test_create_recipe_with_source_url_and_method(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/recipes",
        json={
            "name": "with source",
            "servings": 2,
            "ingredients": [{"food_id": 1, "quantity_g": 100}],
            "source_url": "https://example.com/recipe",
            "method": "Mix everything together and bake at 180C for 20 minutes.",
        },
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["source_url"] == "https://example.com/recipe"
    assert body["method"] == "Mix everything together and bake at 180C for 20 minutes."


def test_create_recipe_source_url_and_method_default_null(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/recipes",
        json={"name": "no extras", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["source_url"] is None
    assert body["method"] is None


def test_create_recipe_rejects_malformed_source_url(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/recipes",
        json={
            "name": "bad url",
            "servings": 1,
            "ingredients": [{"food_id": 1, "quantity_g": 100}],
            "source_url": "not-a-url",
        },
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_update_recipe_sets_source_url_and_method(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "editable", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.patch(
        f"/api/recipes/{recipe['id']}",
        json={"source_url": "https://example.com/foo", "method": "Boil it."},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source_url"] == "https://example.com/foo"
    assert body["method"] == "Boil it."


def test_update_recipe_rejects_malformed_source_url(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "editable", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.patch(
        f"/api/recipes/{recipe['id']}", json={"source_url": "ftp://nope"}, headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_update_recipe_can_clear_source_url_and_method(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={
            "name": "editable", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}],
            "source_url": "https://example.com/foo", "method": "Boil it.",
        },
        headers=auth_headers(token),
    ).json()

    res = client.patch(
        f"/api/recipes/{recipe['id']}",
        json={"source_url": None, "method": None},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source_url"] is None
    assert body["method"] is None


def test_update_recipe_omitting_source_url_leaves_it_unchanged(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={
            "name": "editable", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}],
            "source_url": "https://example.com/foo",
        },
        headers=auth_headers(token),
    ).json()

    res = client.patch(f"/api/recipes/{recipe['id']}", json={"name": "renamed"}, headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["source_url"] == "https://example.com/foo"


def _add_energy_row(client, food_id, amount_per_100g):
    db = next(app.dependency_overrides[get_db]())
    db.add(FoodNutrient(food_id=food_id, nutrient_key="energy", amount_per_100g=amount_per_100g))
    db.commit()
    db.close()


def test_recipe_nutrients_energy_reflects_weight_loss_goal(client):
    _add_energy_row(client, 1, 200.0)
    token = register_and_token(client, "a@example.com")
    client.put(
        "/api/profile",
        json={
            "sex": "male", "birth_year": 1990, "activity_level": "sedentary",
            "is_pregnant": False, "is_lactating": False, "weight_kg": 90, "height_cm": 180,
            "goal": "weight_loss",
        },
        headers=auth_headers(token),
    )
    recipe = client.post(
        "/api/recipes",
        json={"name": "energy test", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/nutrients", headers=auth_headers(token))
    assert res.status_code == 200
    energy = next(n for n in res.json() if n["key"] == "energy")
    assert energy["goal_adjusted"] is True
    assert "deficit" in energy["drv_source"].lower()
    # sedentary, 90kg, age 36: EER = (10*90 + 6.25*180 - 5*36 + 5) * 1.2
    eer = (10 * 90 + 6.25 * 180 - 5 * 36 + 5) * 1.2
    assert energy["adult_drv"] == pytest.approx(eer * 0.85)


def test_recipe_nutrients_energy_unadjusted_without_weight_loss_goal(client):
    _add_energy_row(client, 1, 200.0)
    token = register_and_token(client, "a@example.com")
    client.put(
        "/api/profile",
        json={
            "sex": "male", "birth_year": 1990, "activity_level": "sedentary",
            "is_pregnant": False, "is_lactating": False, "weight_kg": 90, "height_cm": 180,
        },
        headers=auth_headers(token),
    )
    recipe = client.post(
        "/api/recipes",
        json={"name": "energy test", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()

    res = client.get(f"/api/recipes/{recipe['id']}/nutrients", headers=auth_headers(token))
    energy = next(n for n in res.json() if n["key"] == "energy")
    assert energy["goal_adjusted"] is False
