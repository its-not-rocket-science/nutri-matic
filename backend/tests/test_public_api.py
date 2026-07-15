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
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = session_factory()
    food = Food(
        id=1, name="grain", protein_g_per_100g=20, amino_acids=_aa(lysine=20),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9), digestibility_diaas_source="measured",
    )
    legume = Food(
        id=2, name="legume", protein_g_per_100g=20, amino_acids=_aa(lysine=200),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 0.9), digestibility_diaas_source="measured",
    )
    beef = Food(id=3, name="Beef, ground, cooked", protein_g_per_100g=26, amino_acids=dict.fromkeys(AMINO_ACIDS, 20))
    db.add_all([food, legume, beef])
    db.flush()
    db.add(FoodNutrient(food_id=3, nutrient_key="iron", amount_per_100g=2.0))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_key(client, token):
    res = client.post("/api/api-keys", json={"name": "test key"}, headers=auth_headers(token))
    return res.json()["key"], res.json()["id"]


def api_key_headers(key):
    return {"X-API-Key": key}


def test_v1_score_with_valid_api_key(client):
    token = register_and_token(client, "a@example.com")
    key, _ = create_key(client, token)

    res = client.get("/api/v1/foods/1/score?method=diaas", headers=api_key_headers(key))
    assert res.status_code == 200
    body = res.json()
    assert body["method"] == "diaas"
    assert "methodology_version" in body


def test_v1_rejects_missing_api_key(client):
    res = client.get("/api/v1/foods/1/score?method=diaas")
    assert res.status_code == 422  # FastAPI's required-header validation


def test_v1_rejects_invalid_api_key(client):
    res = client.get("/api/v1/foods/1/score?method=diaas", headers=api_key_headers("nm_not-a-real-key"))
    assert res.status_code == 401


def test_v1_rejects_revoked_api_key(client):
    token = register_and_token(client, "a@example.com")
    key, key_id = create_key(client, token)
    client.delete(f"/api/api-keys/{key_id}", headers=auth_headers(token))

    res = client.get("/api/v1/foods/1/score?method=diaas", headers=api_key_headers(key))
    assert res.status_code == 401


def test_v1_complement_returns_real_pairing(client):
    token = register_and_token(client, "a@example.com")
    key, _ = create_key(client, token)

    res = client.get("/api/v1/foods/1/complement?method=diaas", headers=api_key_headers(key))
    assert res.status_code == 200
    body = res.json()
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["food_name"] == "legume"


def test_v1_iron_bioavailability_real_computation(client):
    token = register_and_token(client, "a@example.com")
    key, _ = create_key(client, token)

    res = client.post(
        "/api/v1/bioavailability/iron",
        json={"items": [{"food_id": 3, "quantity_g": 100}]},
        headers=api_key_headers(key),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["non_heme_iron_mg"] > 0 or body["heme_iron_mg"] > 0
    assert body["absorbed_total_mg"] > 0


def test_v1_iron_bioavailability_rejects_unknown_food(client):
    token = register_and_token(client, "a@example.com")
    key, _ = create_key(client, token)

    res = client.post(
        "/api/v1/bioavailability/iron",
        json={"items": [{"food_id": 9999, "quantity_g": 100}]},
        headers=api_key_headers(key),
    )
    assert res.status_code == 422


def test_v1_quota_enforced(client, session_factory):
    token = register_and_token(client, "a@example.com")
    key, key_id = create_key(client, token)

    # exhaust the quota directly via the DB rather than making 1000 real
    # requests
    from app.models import ApiKey

    db = session_factory()
    api_key_row = db.query(ApiKey).filter(ApiKey.id == key_id).one()
    api_key_row.requests_this_period = api_key_row.quota_limit
    db.commit()
    db.close()

    res = client.get("/api/v1/foods/1/score?method=diaas", headers=api_key_headers(key))
    assert res.status_code == 429
