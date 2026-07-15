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


def test_create_api_key_returns_raw_key_once(client):
    token = register_and_token(client, "a@example.com")
    res = client.post("/api/api-keys", json={"name": "my integration"}, headers=auth_headers(token))
    assert res.status_code == 201
    body = res.json()
    assert body["key"].startswith("nm_")
    assert body["key_prefix"] == body["key"][:12]
    assert body["requests_this_period"] == 0
    assert body["revoked_at"] is None


def test_list_api_keys_never_includes_raw_key(client):
    token = register_and_token(client, "a@example.com")
    client.post("/api/api-keys", json={"name": "key one"}, headers=auth_headers(token))
    res = client.get("/api/api-keys", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert "key" not in body[0]
    assert body[0]["key_prefix"].startswith("nm_")


def test_list_api_keys_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post("/api/api-keys", json={"name": "mine"}, headers=auth_headers(token))

    res = client.get("/api/api-keys", headers=auth_headers(other_token))
    assert res.json() == []


def test_revoke_api_key(client):
    token = register_and_token(client, "a@example.com")
    created = client.post("/api/api-keys", json={"name": "to revoke"}, headers=auth_headers(token)).json()

    res = client.delete(f"/api/api-keys/{created['id']}", headers=auth_headers(token))
    assert res.status_code == 204

    listed = client.get("/api/api-keys", headers=auth_headers(token)).json()
    assert listed[0]["revoked_at"] is not None


def test_revoke_api_key_scoped_to_owner(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    created = client.post("/api/api-keys", json={"name": "mine"}, headers=auth_headers(token)).json()

    res = client.delete(f"/api/api-keys/{created['id']}", headers=auth_headers(other_token))
    assert res.status_code == 404


def test_create_api_key_requires_auth(client):
    res = client.post("/api/api-keys", json={"name": "no auth"})
    assert res.status_code == 403


def test_new_key_quota_matches_free_plan_default(client):
    from app.entitlements import API_QUOTA_BY_PLAN, PLAN_FREE

    token = register_and_token(client, "a@example.com")
    res = client.post("/api/api-keys", json={"name": "free tier key"}, headers=auth_headers(token))
    assert res.json()["quota_limit"] == API_QUOTA_BY_PLAN[PLAN_FREE]
