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


def test_register_and_login_round_trip(client):
    res = client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert res.status_code == 201
    assert "access_token" in res.json()

    res_login = client.post("/api/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert res_login.status_code == 200


def test_register_rejects_duplicate_email(client):
    client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    res = client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert res.status_code == 409


def test_register_rejects_short_password(client):
    res = client.post("/api/auth/register", json={"email": "a@example.com", "password": "short"})
    assert res.status_code == 422


def test_register_rejects_email_without_at_sign(client):
    res = client.post("/api/auth/register", json={"email": "not-an-email", "password": "password123"})
    assert res.status_code == 422


def test_register_rejects_empty_email(client):
    res = client.post("/api/auth/register", json={"email": "", "password": "password123"})
    assert res.status_code == 422


def test_login_rejects_wrong_password(client):
    client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    res = client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrongpassword"})
    assert res.status_code == 401


def test_login_rejects_unknown_email(client):
    res = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "password123"})
    assert res.status_code == 401
