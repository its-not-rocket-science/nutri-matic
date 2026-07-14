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


def test_log_weight_creates_entry(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token)
    )
    assert res.status_code == 201
    assert res.json()["weight_kg"] == 80.5


def test_log_weight_same_date_overwrites(client):
    token = register_and_token(client, "a@example.com")
    client.post("/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token))
    client.post("/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 81.0}, headers=auth_headers(token))

    logs = client.get(
        "/api/weight-logs?start_date=2026-07-01&end_date=2026-07-31", headers=auth_headers(token)
    ).json()
    assert len(logs) == 1
    assert logs[0]["weight_kg"] == 81.0


def test_latest_log_syncs_profile_weight(client):
    token = register_and_token(client, "a@example.com")
    client.post("/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token))

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    assert profile["weight_kg"] == 80.5


def test_backfilling_earlier_date_does_not_override_profile(client):
    token = register_and_token(client, "a@example.com")
    client.post("/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token))
    # backfill an earlier day after the fact
    client.post("/api/weight-logs", json={"log_date": "2026-07-10", "weight_kg": 82.0}, headers=auth_headers(token))

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    assert profile["weight_kg"] == 80.5


def test_newer_log_after_initial_updates_profile(client):
    token = register_and_token(client, "a@example.com")
    client.post("/api/weight-logs", json={"log_date": "2026-07-10", "weight_kg": 82.0}, headers=auth_headers(token))
    client.post("/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token))

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    assert profile["weight_kg"] == 80.5


def test_delete_does_not_reset_profile_weight(client):
    token = register_and_token(client, "a@example.com")
    log = client.post(
        "/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token)
    ).json()

    res = client.delete(f"/api/weight-logs/{log['id']}", headers=auth_headers(token))
    assert res.status_code == 204

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    assert profile["weight_kg"] == 80.5

    logs = client.get(
        "/api/weight-logs?start_date=2026-07-01&end_date=2026-07-31", headers=auth_headers(token)
    ).json()
    assert logs == []


def test_weight_logs_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post("/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token))

    other_logs = client.get(
        "/api/weight-logs?start_date=2026-07-01&end_date=2026-07-31", headers=auth_headers(other_token)
    ).json()
    assert other_logs == []


def test_cannot_delete_other_users_log(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    log = client.post(
        "/api/weight-logs", json={"log_date": "2026-07-13", "weight_kg": 80.5}, headers=auth_headers(token)
    ).json()

    res = client.delete(f"/api/weight-logs/{log['id']}", headers=auth_headers(other_token))
    assert res.status_code == 404
