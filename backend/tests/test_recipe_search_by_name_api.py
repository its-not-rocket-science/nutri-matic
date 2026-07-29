"""Prompt 1.1: GET /api/recipes/search-by-name — the endpoint behind the
meal-plan/diary "Search recipes" box. Previously that box only ever called
GET /api/recipes (the current user's own recipes) and filtered client-side,
so a demo account or any user with few personal recipes found nothing no
matter what was typed. These tests confirm the fixed endpoint actually
surfaces public/stock recipes and shared recipes, not just the caller's
own, and never leaks another user's private recipe."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Food, Recipe, User
from app.reference_patterns import AMINO_ACIDS


def _make_client():
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

    db = TestSession()
    db.add(Food(id=1, name="test food", protein_g_per_100g=10, amino_acids=dict.fromkeys(AMINO_ACIDS, 20)))
    db.add(User(id=100, email="stock@system.local", password_hash=hash_password("unguessable"), is_system=True))
    db.add(Recipe(id=1, user_id=100, name="Chickpea Curry", servings=4, is_public=True))
    db.commit()
    db.close()

    return TestClient(app)


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_recipe(client, token, name):
    res = client.post(
        "/api/recipes",
        json={"name": name, "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    return res.json()


def test_search_by_name_surfaces_stock_recipe_for_user_with_no_own_recipes():
    client = _make_client()
    token = register_and_token(client, "demo@example.com")

    res = client.get("/api/recipes/search-by-name?q=chickpea", headers=auth_headers(token))
    assert res.status_code == 200
    names = [r["name"] for r in res.json()]
    assert names == ["Chickpea Curry"]
    assert res.json()[0]["is_owner"] is False
    assert res.json()[0]["is_stock"] is True

    app.dependency_overrides.clear()


def test_search_by_name_finds_own_recipe():
    client = _make_client()
    token = register_and_token(client, "user@example.com")
    create_recipe(client, token, "Lentil Soup")

    res = client.get("/api/recipes/search-by-name?q=lentil", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert [r["name"] for r in body] == ["Lentil Soup"]
    assert body[0]["is_owner"] is True

    app.dependency_overrides.clear()


def test_search_by_name_excludes_other_users_private_recipe():
    client = _make_client()
    owner_token = register_and_token(client, "owner@example.com")
    create_recipe(client, owner_token, "Secret Stew")

    other_token = register_and_token(client, "other@example.com")
    res = client.get("/api/recipes/search-by-name?q=secret", headers=auth_headers(other_token))
    assert res.status_code == 200
    assert res.json() == []

    app.dependency_overrides.clear()


def test_search_by_name_requires_auth():
    client = _make_client()
    res = client.get("/api/recipes/search-by-name?q=chickpea")
    assert res.status_code == 403

    app.dependency_overrides.clear()
