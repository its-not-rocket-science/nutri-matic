import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


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
    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_profile_defaults_after_registration(client):
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/profile", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "a@example.com"
    assert body["sex"] is None
    assert body["is_pregnant"] is False
    assert body["is_lactating"] is False


def test_get_profile_requires_auth(client):
    res = client.get("/api/profile")
    assert res.status_code == 403  # HTTPBearer's response for a missing Authorization header


def test_update_profile_round_trips_all_fields(client):
    token = register_and_token(client, "a@example.com")
    payload = {
        "sex": "female",
        "birth_year": 1990,
        "activity_level": "moderate",
        "is_pregnant": True,
        "is_lactating": False,
        "weight_kg": 65.5,
        "height_cm": 168.0,
    }
    res = client.put("/api/profile", json=payload, headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    for key, value in payload.items():
        assert body[key] == value

    # persisted, not just echoed back
    res2 = client.get("/api/profile", headers=auth_headers(token))
    assert res2.json() == body


def test_update_profile_scoped_to_current_user(client):
    token_a = register_and_token(client, "a@example.com")
    token_b = register_and_token(client, "b@example.com")

    client.put(
        "/api/profile",
        json={
            "sex": "male",
            "birth_year": 1985,
            "activity_level": "active",
            "is_pregnant": False,
            "is_lactating": False,
            "weight_kg": 80.0,
            "height_cm": 180.0,
        },
        headers=auth_headers(token_a),
    )

    res_b = client.get("/api/profile", headers=auth_headers(token_b))
    assert res_b.json()["sex"] is None  # user b's profile untouched by user a's update


def test_update_profile_sets_dietary_pattern(client):
    token = register_and_token(client, "a@example.com")
    payload = {
        "sex": None, "birth_year": None, "activity_level": None,
        "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
        "dietary_pattern": "vegan",
    }
    res = client.put("/api/profile", json=payload, headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["dietary_pattern"] == "vegan"


def test_update_profile_rejects_unknown_dietary_pattern(client):
    token = register_and_token(client, "a@example.com")
    payload = {
        "sex": None, "birth_year": None, "activity_level": None,
        "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
        "dietary_pattern": "carnivore-but-only-on-tuesdays",
    }
    res = client.put("/api/profile", json=payload, headers=auth_headers(token))
    assert res.status_code == 422


def test_update_profile_sets_currency(client):
    token = register_and_token(client, "a@example.com")
    payload = {
        "sex": None, "birth_year": None, "activity_level": None,
        "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
        "currency": "gbp",  # lowercase input, normalized to uppercase
    }
    res = client.put("/api/profile", json=payload, headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["currency"] == "GBP"

    res2 = client.get("/api/profile", headers=auth_headers(token))
    assert res2.json()["currency"] == "GBP"


def test_update_profile_rejects_malformed_currency(client):
    token = register_and_token(client, "a@example.com")
    payload = {
        "sex": None, "birth_year": None, "activity_level": None,
        "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
        "currency": "US$",
    }
    res = client.put("/api/profile", json=payload, headers=auth_headers(token))
    assert res.status_code == 422


def test_update_profile_clears_currency_back_to_browser_default(client):
    """Sending currency: null clears an explicit preference — the frontend
    then falls back to the browser locale's implied currency."""
    token = register_and_token(client, "a@example.com")
    base_payload = {
        "sex": None, "birth_year": None, "activity_level": None,
        "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
    }
    client.put("/api/profile", json={**base_payload, "currency": "JPY"}, headers=auth_headers(token))
    res = client.put("/api/profile", json={**base_payload, "currency": None}, headers=auth_headers(token))
    assert res.json()["currency"] is None


def test_get_dietary_vocabulary_no_auth_required(client):
    res = client.get("/api/profile/dietary-vocabulary")
    assert res.status_code == 200
    body = res.json()
    assert any(t["key"] == "peanut" for t in body["allergen_tags"])
    assert any(p["key"] == "vegan" for p in body["dietary_patterns"])
    assert any(p["key"] == "halal" for p in body["religious_requirements"])


def test_create_dietary_constraint(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/profile/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude", "note": None},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["category"] == "allergy"
    assert body["tag"] == "peanut"
    assert body["severity"] == "hard_exclude"

    res_list = client.get("/api/profile/dietary-constraints", headers=auth_headers(token))
    assert len(res_list.json()) == 1


def test_create_dietary_constraint_rejects_unknown_tag(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/profile/dietary-constraints",
        json={"category": "allergy", "tag": "kryptonite", "severity": "hard_exclude"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_create_dietary_constraint_rejects_duplicate(client):
    token = register_and_token(client, "a@example.com")
    body = {"category": "allergy", "tag": "peanut", "severity": "hard_exclude"}
    client.post("/api/profile/dietary-constraints", json=body, headers=auth_headers(token))
    res = client.post("/api/profile/dietary-constraints", json=body, headers=auth_headers(token))
    assert res.status_code == 409


def test_medical_constraint_must_have_null_tag(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/profile/dietary-constraints",
        json={"category": "medical", "tag": "peanut", "severity": None, "note": "diabetes"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422

    res_ok = client.post(
        "/api/profile/dietary-constraints",
        json={"category": "medical", "tag": None, "severity": None, "note": "diabetes"},
        headers=auth_headers(token),
    )
    assert res_ok.status_code == 201


def test_delete_dietary_constraint_scoped_to_owner(client):
    token_a = register_and_token(client, "a@example.com")
    token_b = register_and_token(client, "b@example.com")
    created = client.post(
        "/api/profile/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude"},
        headers=auth_headers(token_a),
    ).json()

    res = client.delete(f"/api/profile/dietary-constraints/{created['id']}", headers=auth_headers(token_b))
    assert res.status_code == 404

    res_ok = client.delete(f"/api/profile/dietary-constraints/{created['id']}", headers=auth_headers(token_a))
    assert res_ok.status_code == 204
