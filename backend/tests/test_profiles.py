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


def owner_profile(client, token):
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    return next(p for p in profiles if p["is_account_owner"])


BASE_PROFILE_PAYLOAD = {
    "name": "Me",
    "sex": None, "birth_year": None, "activity_level": None,
    "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
}


def test_registration_creates_an_owner_profile(client):
    token = register_and_token(client, "a@example.com")
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    assert len(profiles) == 1
    assert profiles[0]["is_account_owner"] is True
    assert profiles[0]["sex"] is None


def test_get_profiles_requires_auth(client):
    res = client.get("/api/profiles")
    assert res.status_code == 403  # HTTPBearer's response for a missing Authorization header


def test_update_owner_profile_round_trips_all_fields(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    payload = {
        "name": "Me",
        "sex": "female",
        "birth_year": 1990,
        "activity_level": "moderate",
        "is_pregnant": True,
        "is_lactating": False,
        "weight_kg": 65.5,
        "height_cm": 168.0,
    }
    res = client.put(f"/api/profiles/{owner['id']}", json=payload, headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    for key, value in payload.items():
        assert body[key] == value

    # persisted, not just echoed back
    res2 = client.get(f"/api/profiles/{owner['id']}", headers=auth_headers(token))
    assert res2.json() == body


def test_profile_update_scoped_to_owning_account(client):
    token_a = register_and_token(client, "a@example.com")
    token_b = register_and_token(client, "b@example.com")
    owner_a = owner_profile(client, token_a)

    res = client.put(
        f"/api/profiles/{owner_a['id']}",
        json={**BASE_PROFILE_PAYLOAD, "sex": "male"},
        headers=auth_headers(token_b),
    )
    assert res.status_code == 404


def test_create_dependent_profile(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/profiles",
        json={**BASE_PROFILE_PAYLOAD, "name": "Jack", "birth_year": 2018},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Jack"
    assert body["is_account_owner"] is False

    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    assert len(profiles) == 2
    assert {p["name"] for p in profiles} == {"Me", "Jack"}


def test_owner_profile_cannot_be_deleted(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.delete(f"/api/profiles/{owner['id']}", headers=auth_headers(token))
    assert res.status_code == 422


def test_dependent_profile_can_be_deleted_and_cascades_its_data(client):
    token = register_and_token(client, "a@example.com")
    dependent = client.post(
        "/api/profiles", json={**BASE_PROFILE_PAYLOAD, "name": "Jack"}, headers=auth_headers(token)
    ).json()

    client.post(
        f"/api/profiles/{dependent['id']}/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude", "note": None},
        headers=auth_headers(token),
    )
    client.post(
        "/api/weight-logs?profile_id=" + str(dependent["id"]),
        json={"log_date": "2026-01-01", "weight_kg": 30.0},
        headers=auth_headers(token),
    )
    client.post(f"/api/profiles/{dependent['id']}/medical-acknowledgement", headers=auth_headers(token))

    res = client.delete(f"/api/profiles/{dependent['id']}", headers=auth_headers(token))
    assert res.status_code == 204

    res_get = client.get(f"/api/profiles/{dependent['id']}", headers=auth_headers(token))
    assert res_get.status_code == 404

    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    assert len(profiles) == 1


def test_cross_account_profile_id_404s_on_diary(client):
    """A profile_id belonging to a different account must 404 on a
    profile-scoped endpoint, not silently succeed or leak data."""
    token_a = register_and_token(client, "a@example.com")
    token_b = register_and_token(client, "b@example.com")
    owner_a = owner_profile(client, token_a)

    res = client.get(f"/api/diary?entry_date=2026-01-01&profile_id={owner_a['id']}", headers=auth_headers(token_b))
    assert res.status_code == 404


def test_update_owner_profile_sets_dietary_pattern(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.put(
        f"/api/profiles/{owner['id']}",
        json={**BASE_PROFILE_PAYLOAD, "dietary_pattern": "vegan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json()["dietary_pattern"] == "vegan"


def test_update_profile_rejects_unknown_dietary_pattern(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.put(
        f"/api/profiles/{owner['id']}",
        json={**BASE_PROFILE_PAYLOAD, "dietary_pattern": "carnivore-but-only-on-tuesdays"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_update_profile_sets_goal(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.put(
        f"/api/profiles/{owner['id']}",
        json={**BASE_PROFILE_PAYLOAD, "goal": "protein_quality"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json()["goal"] == "protein_quality"


def test_update_profile_rejects_unknown_goal(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.put(
        f"/api/profiles/{owner['id']}",
        json={**BASE_PROFILE_PAYLOAD, "goal": "world_domination"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_update_profile_accepts_weight_loss_goals(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    for goal in ("weight_loss", "visceral_fat_reduction"):
        res = client.put(
            f"/api/profiles/{owner['id']}", json={**BASE_PROFILE_PAYLOAD, "goal": goal}, headers=auth_headers(token)
        )
        assert res.status_code == 200
        assert res.json()["goal"] == goal


def test_get_dietary_vocabulary_no_auth_required(client):
    res = client.get("/api/profiles/dietary-vocabulary")
    assert res.status_code == 200
    body = res.json()
    assert any(t["key"] == "peanut" for t in body["allergen_tags"])
    assert any(p["key"] == "vegan" for p in body["dietary_patterns"])
    assert any(p["key"] == "halal" for p in body["religious_requirements"])


def test_create_dietary_constraint(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude", "note": None},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["category"] == "allergy"
    assert body["tag"] == "peanut"
    assert body["severity"] == "hard_exclude"

    res_list = client.get(f"/api/profiles/{owner['id']}/dietary-constraints", headers=auth_headers(token))
    assert len(res_list.json()) == 1


def test_dietary_constraints_are_independent_per_profile(client):
    """The whole point of the feature: one profile's allergy doesn't leak
    onto another profile under the same account."""
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    dependent = client.post(
        "/api/profiles", json={**BASE_PROFILE_PAYLOAD, "name": "Jack"}, headers=auth_headers(token)
    ).json()

    client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude", "note": None},
        headers=auth_headers(token),
    )

    owner_constraints = client.get(f"/api/profiles/{owner['id']}/dietary-constraints", headers=auth_headers(token)).json()
    dependent_constraints = client.get(
        f"/api/profiles/{dependent['id']}/dietary-constraints", headers=auth_headers(token)
    ).json()
    assert len(owner_constraints) == 1
    assert len(dependent_constraints) == 0


def test_create_dietary_constraint_rejects_unknown_tag(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "allergy", "tag": "kryptonite", "severity": "hard_exclude"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_create_dietary_constraint_rejects_duplicate(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    body = {"category": "allergy", "tag": "peanut", "severity": "hard_exclude"}
    client.post(f"/api/profiles/{owner['id']}/dietary-constraints", json=body, headers=auth_headers(token))
    res = client.post(f"/api/profiles/{owner['id']}/dietary-constraints", json=body, headers=auth_headers(token))
    assert res.status_code == 409


def test_medical_constraint_must_have_null_tag(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    res = client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "medical", "tag": "peanut", "severity": None, "note": "diabetes"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422

    res_ok = client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "medical", "tag": None, "severity": None, "note": "diabetes"},
        headers=auth_headers(token),
    )
    assert res_ok.status_code == 201


def test_delete_dietary_constraint_scoped_to_owning_account(client):
    token_a = register_and_token(client, "a@example.com")
    token_b = register_and_token(client, "b@example.com")
    owner_a = owner_profile(client, token_a)
    created = client.post(
        f"/api/profiles/{owner_a['id']}/dietary-constraints",
        json={"category": "allergy", "tag": "peanut", "severity": "hard_exclude"},
        headers=auth_headers(token_a),
    ).json()

    res = client.delete(
        f"/api/profiles/{owner_a['id']}/dietary-constraints/{created['id']}", headers=auth_headers(token_b)
    )
    assert res.status_code == 404

    res_ok = client.delete(
        f"/api/profiles/{owner_a['id']}/dietary-constraints/{created['id']}", headers=auth_headers(token_a)
    )
    assert res_ok.status_code == 204


def test_account_currency_round_trips(client):
    token = register_and_token(client, "a@example.com")
    res = client.put("/api/account", json={"currency": "gbp"}, headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["currency"] == "GBP"

    res2 = client.get("/api/account", headers=auth_headers(token))
    assert res2.json()["currency"] == "GBP"


def test_account_currency_rejects_malformed_code(client):
    token = register_and_token(client, "a@example.com")
    res = client.put("/api/account", json={"currency": "US$"}, headers=auth_headers(token))
    assert res.status_code == 422


def test_account_currency_clears_back_to_browser_default(client):
    token = register_and_token(client, "a@example.com")
    client.put("/api/account", json={"currency": "JPY"}, headers=auth_headers(token))
    res = client.put("/api/account", json={"currency": None}, headers=auth_headers(token))
    assert res.json()["currency"] is None
