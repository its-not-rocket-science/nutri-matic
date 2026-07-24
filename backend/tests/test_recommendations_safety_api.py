"""API-level tests for prompt 11's safety/eligibility wiring across all
four /api/recommendations/* endpoints — a too-young profile disables the
engine outright, and (hardening prompt 5) so does an unacknowledged
medical dietary constraint, by default, until explicitly and revocably
acknowledged via /api/profiles/{id}/medical-acknowledgement."""

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


def test_medical_constraint_disables_by_default(client):
    """Hardening prompt 5: unlike an ordinary warning, a medical
    constraint disables the whole engine by default."""
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
    assert body["suggestions"] == []
    assert body["disabled_reason"] is not None
    assert body["disabled_reason_code"] == "unacknowledged_medical_constraint"
    # the warning still shows even while disabled — never silently dropped
    assert "medical_constraint_present" in body["warnings"]


def test_acknowledging_medical_constraint_re_enables_recommendations(client):
    token = register_and_token(client, "h@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)
    client.post(
        f"/api/profiles/{profile_id}/dietary-constraints",
        json={"category": "medical", "note": "renal diet"},
        headers=headers,
    )

    ack_res = client.post(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=headers)
    assert ack_res.status_code == 201
    assert ack_res.json()["revoked_at"] is None

    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["disabled_reason"] is None
    # acknowledging is not the same as the concern going away — still shown
    assert "medical_constraint_present" in body["warnings"]


def test_revoking_acknowledgement_disables_again(client):
    token = register_and_token(client, "i@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)
    client.post(
        f"/api/profiles/{profile_id}/dietary-constraints",
        json={"category": "medical", "note": "renal diet"},
        headers=headers,
    )
    client.post(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=headers)

    revoke_res = client.delete(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=headers)
    assert revoke_res.status_code == 204

    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.json()["disabled_reason_code"] == "unacknowledged_medical_constraint"


def test_medical_acknowledgement_status_endpoint(client):
    token = register_and_token(client, "j@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)

    assert client.get(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=headers).json() is None

    client.post(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=headers)
    status = client.get(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=headers).json()
    assert status is not None
    assert status["revoked_at"] is None
    assert status["profile_id"] == profile_id


def test_cannot_acknowledge_another_users_profile(client):
    owner_token = register_and_token(client, "owner@example.com")
    owner_headers = auth_headers(owner_token)
    profile_id = get_owner_profile_id(client, owner_headers)

    attacker_token = register_and_token(client, "attacker@example.com")
    res = client.post(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=auth_headers(attacker_token))
    assert res.status_code == 404


def test_no_query_string_bypass_for_medical_disable(client):
    """There is deliberately no request parameter anywhere on the
    recommendation endpoints that can re-enable a disabled profile —
    only the dedicated, authenticated, ownership-checked
    /medical-acknowledgement endpoint can."""
    token = register_and_token(client, "l@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)
    client.post(
        f"/api/profiles/{profile_id}/dietary-constraints",
        json={"category": "medical", "note": "renal diet"},
        headers=headers,
    )

    for bypass_params in (
        {"acknowledge_medical": "true"},
        {"medical_ack": "1"},
        {"override_safety": "true"},
        {"skip_medical_check": "true"},
    ):
        res = client.get(
            "/api/recommendations/ingredients",
            params={"entry_date": "2026-01-01", **bypass_params},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["disabled_reason_code"] == "unacknowledged_medical_constraint"


def test_disabled_recommendation_never_calls_the_candidate_service(client, monkeypatch):
    """Proves candidate generation/scoring never runs when disabled —
    hardening prompt 5's explicit requirement — by making the service
    function raise if called at all."""
    import app.routers.recommendations as recommendations_module

    token = register_and_token(client, "k@example.com")
    headers = auth_headers(token)
    profile_id = get_owner_profile_id(client, headers)
    set_birth_year(client, headers, profile_id, CURRENT_YEAR - 30)
    client.post(
        f"/api/profiles/{profile_id}/dietary-constraints",
        json={"category": "medical", "note": "renal diet"},
        headers=headers,
    )

    def _boom(*a, **k):
        raise AssertionError("suggest_ingredients was called despite the engine being disabled")

    monkeypatch.setattr(recommendations_module, "suggest_ingredients", _boom)
    res = client.get(
        "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["suggestions"] == []


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
