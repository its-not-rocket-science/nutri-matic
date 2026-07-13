import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


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

    # seed a food to build recipes from
    db = TestSession()
    db.add(Food(id=1, name="test food", protein_g_per_100g=10, amino_acids=dict.fromkeys(AMINO_ACIDS, 20)))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_recipe(client, token, name="my recipe"):
    res = client.post(
        "/api/recipes",
        json={"name": name, "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    return res.json()


def test_owner_sees_is_owner_true_and_own_email(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    assert recipe["is_owner"] is True
    assert recipe["owner_email"] == "owner@example.com"


def test_non_shared_user_cannot_view_recipe(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)

    res = client.get(f"/api/recipes/{recipe['id']}", headers=auth_headers(other_token))
    assert res.status_code == 404


def test_share_grants_view_access(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)

    share_res = client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "other@example.com"}, headers=auth_headers(owner_token)
    )
    assert share_res.status_code == 201

    view_res = client.get(f"/api/recipes/{recipe['id']}", headers=auth_headers(other_token))
    assert view_res.status_code == 200
    assert view_res.json()["is_owner"] is False
    assert view_res.json()["owner_email"] == "owner@example.com"

    shared_list = client.get("/api/recipes/shared-with-me", headers=auth_headers(other_token))
    assert [r["id"] for r in shared_list.json()] == [recipe["id"]]


def test_shared_user_cannot_delete_or_manage_shares(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)
    client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "other@example.com"}, headers=auth_headers(owner_token)
    )

    delete_res = client.delete(f"/api/recipes/{recipe['id']}", headers=auth_headers(other_token))
    assert delete_res.status_code == 404

    shares_res = client.get(f"/api/recipes/{recipe['id']}/shares", headers=auth_headers(other_token))
    assert shares_res.status_code == 404

    new_share_res = client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "owner@example.com"}, headers=auth_headers(other_token)
    )
    assert new_share_res.status_code == 404


def test_share_with_self_rejected(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    res = client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "owner@example.com"}, headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_share_with_unknown_email_404(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    res = client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "nobody@example.com"}, headers=auth_headers(token)
    )
    assert res.status_code == 404


def test_duplicate_share_rejected(client):
    owner_token = register_and_token(client, "owner@example.com")
    register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)
    client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "other@example.com"}, headers=auth_headers(owner_token)
    )
    dup = client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "other@example.com"}, headers=auth_headers(owner_token)
    )
    assert dup.status_code == 409


def test_revoked_share_removes_access(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)
    share = client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "other@example.com"}, headers=auth_headers(owner_token)
    ).json()

    client.delete(f"/api/recipes/{recipe['id']}/shares/{share['id']}", headers=auth_headers(owner_token))

    res = client.get(f"/api/recipes/{recipe['id']}", headers=auth_headers(other_token))
    assert res.status_code == 404


def test_shared_user_can_copy_recipe_into_own_list(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token, name="original")
    client.post(
        f"/api/recipes/{recipe['id']}/shares", json={"email": "other@example.com"}, headers=auth_headers(owner_token)
    )

    copy_res = client.post(f"/api/recipes/{recipe['id']}/copy", headers=auth_headers(other_token))
    assert copy_res.status_code == 201
    copy = copy_res.json()
    assert copy["is_owner"] is True
    assert copy["owner_email"] == "other@example.com"
    assert copy["name"] == "original (copy)"
    assert copy["ingredients"] == recipe["ingredients"]

    # the copy is fully independent — other user can delete their own copy
    delete_res = client.delete(f"/api/recipes/{copy['id']}", headers=auth_headers(other_token))
    assert delete_res.status_code == 204


def test_copy_requires_view_access(client):
    owner_token = register_and_token(client, "owner@example.com")
    stranger_token = register_and_token(client, "stranger@example.com")
    recipe = create_recipe(client, owner_token)

    res = client.post(f"/api/recipes/{recipe['id']}/copy", headers=auth_headers(stranger_token))
    assert res.status_code == 404
