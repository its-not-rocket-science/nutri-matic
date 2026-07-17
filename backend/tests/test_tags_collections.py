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


def share(client, owner_token, recipe_id, email):
    res = client.post(f"/api/recipes/{recipe_id}/shares", json={"email": email}, headers=auth_headers(owner_token))
    assert res.status_code == 201


# --- tags ---

def test_add_tag_and_it_appears_on_recipe(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)

    res = client.post(f"/api/recipes/{recipe['id']}/tags", json={"tag": "Quick"}, headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["tags"] == ["quick"]  # normalized to lowercase


def test_add_tag_is_idempotent(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    client.post(f"/api/recipes/{recipe['id']}/tags", json={"tag": "quick"}, headers=auth_headers(token))
    res = client.post(f"/api/recipes/{recipe['id']}/tags", json={"tag": "quick"}, headers=auth_headers(token))
    assert res.json()["tags"] == ["quick"]


def test_remove_tag(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    client.post(f"/api/recipes/{recipe['id']}/tags", json={"tag": "quick"}, headers=auth_headers(token))
    res = client.delete(f"/api/recipes/{recipe['id']}/tags/quick", headers=auth_headers(token))
    assert res.json()["tags"] == []


def test_tag_management_requires_ownership(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)
    share(client, owner_token, recipe["id"], "other@example.com")

    res = client.post(f"/api/recipes/{recipe['id']}/tags", json={"tag": "hack"}, headers=auth_headers(other_token))
    assert res.status_code == 404


def test_list_recipes_filtered_by_tag(client):
    token = register_and_token(client, "owner@example.com")
    tagged = create_recipe(client, token, name="tagged")
    untagged = create_recipe(client, token, name="untagged")
    client.post(f"/api/recipes/{tagged['id']}/tags", json={"tag": "quick"}, headers=auth_headers(token))

    res = client.get("/api/recipes?tag=quick", headers=auth_headers(token))
    assert [r["name"] for r in res.json()] == ["tagged"]

    all_res = client.get("/api/recipes", headers=auth_headers(token))
    assert {r["name"] for r in all_res.json()} == {"tagged", "untagged"}


def test_list_my_tags_distinct(client):
    token = register_and_token(client, "owner@example.com")
    r1 = create_recipe(client, token, name="a")
    r2 = create_recipe(client, token, name="b")
    client.post(f"/api/recipes/{r1['id']}/tags", json={"tag": "quick"}, headers=auth_headers(token))
    client.post(f"/api/recipes/{r2['id']}/tags", json={"tag": "quick"}, headers=auth_headers(token))
    client.post(f"/api/recipes/{r2['id']}/tags", json={"tag": "vegetarian"}, headers=auth_headers(token))

    res = client.get("/api/recipes/tags", headers=auth_headers(token))
    assert res.json() == ["quick", "vegetarian"]


# --- collections ---

def test_create_and_list_collections(client):
    token = register_and_token(client, "owner@example.com")
    res = client.post("/api/collections", json={"name": "Meal Prep"}, headers=auth_headers(token))
    assert res.status_code == 201
    assert res.json() == {
        "id": 1,
        "name": "Meal Prep",
        "recipe_count": 0,
        "owner_email": "owner@example.com",
        "is_owner": True,
        "is_public": False,
    }

    listed = client.get("/api/collections", headers=auth_headers(token))
    assert listed.json() == [
        {
            "id": 1,
            "name": "Meal Prep",
            "recipe_count": 0,
            "owner_email": "owner@example.com",
            "is_owner": True,
            "is_public": False,
        }
    ]


def test_add_and_remove_recipe_from_collection(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    collection = client.post("/api/collections", json={"name": "Favs"}, headers=auth_headers(token)).json()

    add_res = client.post(
        f"/api/collections/{collection['id']}/recipes", json={"recipe_id": recipe["id"]}, headers=auth_headers(token)
    )
    assert add_res.status_code == 201
    assert [r["id"] for r in add_res.json()["recipes"]] == [recipe["id"]]

    listed = client.get("/api/collections", headers=auth_headers(token))
    assert listed.json()[0]["recipe_count"] == 1

    remove_res = client.delete(
        f"/api/collections/{collection['id']}/recipes/{recipe['id']}", headers=auth_headers(token)
    )
    assert remove_res.json()["recipes"] == []


def test_add_recipe_to_collection_is_idempotent(client):
    token = register_and_token(client, "owner@example.com")
    recipe = create_recipe(client, token)
    collection = client.post("/api/collections", json={"name": "Favs"}, headers=auth_headers(token)).json()

    client.post(f"/api/collections/{collection['id']}/recipes", json={"recipe_id": recipe["id"]}, headers=auth_headers(token))
    client.post(f"/api/collections/{collection['id']}/recipes", json={"recipe_id": recipe["id"]}, headers=auth_headers(token))

    listed = client.get("/api/collections", headers=auth_headers(token))
    assert listed.json()[0]["recipe_count"] == 1


def test_can_add_shared_recipe_to_own_collection(client):
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = create_recipe(client, owner_token)
    share(client, owner_token, recipe["id"], "other@example.com")

    collection = client.post("/api/collections", json={"name": "Saved"}, headers=auth_headers(other_token)).json()
    res = client.post(
        f"/api/collections/{collection['id']}/recipes",
        json={"recipe_id": recipe["id"]},
        headers=auth_headers(other_token),
    )
    assert res.status_code == 201
    assert res.json()["recipes"][0]["id"] == recipe["id"]


def test_cannot_add_invisible_recipe_to_collection(client):
    owner_token = register_and_token(client, "owner@example.com")
    stranger_token = register_and_token(client, "stranger@example.com")
    recipe = create_recipe(client, owner_token)

    collection = client.post("/api/collections", json={"name": "Saved"}, headers=auth_headers(stranger_token)).json()
    res = client.post(
        f"/api/collections/{collection['id']}/recipes",
        json={"recipe_id": recipe["id"]},
        headers=auth_headers(stranger_token),
    )
    assert res.status_code == 404


def test_collections_are_isolated_and_owner_only(client):
    token_a = register_and_token(client, "a@example.com")
    token_b = register_and_token(client, "b@example.com")
    collection = client.post("/api/collections", json={"name": "A's"}, headers=auth_headers(token_a)).json()

    b_list = client.get("/api/collections", headers=auth_headers(token_b))
    assert b_list.json() == []

    b_get = client.get(f"/api/collections/{collection['id']}", headers=auth_headers(token_b))
    assert b_get.status_code == 404

    b_delete = client.delete(f"/api/collections/{collection['id']}", headers=auth_headers(token_b))
    assert b_delete.status_code == 404


def test_delete_collection(client):
    token = register_and_token(client, "owner@example.com")
    collection = client.post("/api/collections", json={"name": "Temp"}, headers=auth_headers(token)).json()
    res = client.delete(f"/api/collections/{collection['id']}", headers=auth_headers(token))
    assert res.status_code == 204
    assert client.get(f"/api/collections/{collection['id']}", headers=auth_headers(token)).status_code == 404
