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


def register_and_token(client, email="a@example.com", password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_preset(client):
    token = register_and_token(client)
    res = client.post(
        "/api/presets",
        json={"name": "high fibre", "scope": "food", "filters": [{"key": "fiber_total", "op": "gte", "value": 5}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    preset = res.json()
    assert preset["name"] == "high fibre"
    assert preset["filters"] == [{"key": "fiber_total", "op": "gte", "value": 5}]

    listed = client.get("/api/presets", headers=auth_headers(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_create_preset_rejects_unknown_key(client):
    token = register_and_token(client)
    res = client.post(
        "/api/presets",
        json={"name": "bad", "scope": "food", "filters": [{"key": "not_a_real_key", "op": "gte", "value": 1}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_create_preset_rejects_food_only_key_for_recipe_scope(client):
    token = register_and_token(client)
    res = client.post(
        "/api/presets",
        json={
            "name": "bad scope",
            "scope": "recipe",
            "filters": [{"key": "protein_g_per_100g", "op": "gte", "value": 10}],
        },
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_presets_scoped_by_query_param(client):
    token = register_and_token(client)
    client.post(
        "/api/presets",
        json={"name": "food preset", "scope": "food", "filters": [{"key": "fiber_total", "op": "gte", "value": 5}]},
        headers=auth_headers(token),
    )
    client.post(
        "/api/presets",
        json={"name": "recipe preset", "scope": "recipe", "filters": [{"key": "energy", "op": "lte", "value": 300}]},
        headers=auth_headers(token),
    )

    food_only = client.get("/api/presets?scope=food", headers=auth_headers(token))
    assert [p["name"] for p in food_only.json()] == ["food preset"]


def test_presets_are_isolated_per_user(client):
    token_a = register_and_token(client, email="a@example.com")
    token_b = register_and_token(client, email="b@example.com")

    client.post(
        "/api/presets",
        json={"name": "mine", "scope": "food", "filters": []},
        headers=auth_headers(token_a),
    )

    b_list = client.get("/api/presets", headers=auth_headers(token_b))
    assert b_list.json() == []


def test_delete_preset_requires_ownership(client):
    token_a = register_and_token(client, email="a@example.com")
    token_b = register_and_token(client, email="b@example.com")

    created = client.post(
        "/api/presets", json={"name": "mine", "scope": "food", "filters": []}, headers=auth_headers(token_a)
    ).json()

    denied = client.delete(f"/api/presets/{created['id']}", headers=auth_headers(token_b))
    assert denied.status_code == 404

    allowed = client.delete(f"/api/presets/{created['id']}", headers=auth_headers(token_a))
    assert allowed.status_code == 204


def test_presets_require_auth(client):
    res = client.get("/api/presets")
    assert res.status_code == 403
