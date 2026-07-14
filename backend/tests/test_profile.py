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
