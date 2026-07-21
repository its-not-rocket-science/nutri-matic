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


def test_new_user_defaults_to_free_plan(client):
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/entitlements", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["plan"] == "free"
    assert body["effective_plan"] == "free"
    assert body["plan_expires_at"] is None


def test_entitlements_requires_auth(client):
    res = client.get("/api/entitlements")
    assert res.status_code == 403


def test_profile_response_includes_plan(client):
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/account", headers=auth_headers(token))
    assert res.json()["plan"] == "free"
