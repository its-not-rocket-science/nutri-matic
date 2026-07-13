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
    db.add(Food(id=1, name="chicken", protein_g_per_100g=25, amino_acids=dict.fromkeys(AMINO_ACIDS, 20)))
    db.add(Food(id=2, name="rice", protein_g_per_100g=7, amino_acids=dict.fromkeys(AMINO_ACIDS, 5)))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_recipe(client, token):
    res = client.post(
        "/api/recipes",
        json={
            "name": "chicken and rice",
            "servings": 2,
            "ingredients": [
                {"food_id": 1, "quantity_g": 200},
                {"food_id": 2, "quantity_g": 100},
            ],
        },
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    return res.json()


def test_create_food_entry(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["food_name"] == "chicken"
    assert body["recipe_id"] is None


def test_create_recipe_entry(client):
    token = register_and_token(client, "a@example.com")
    recipe = create_recipe(client, token)
    res = client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "dinner", "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["recipe_name"] == "chicken and rice"
    assert body["food_id"] is None


def test_rejects_both_food_and_recipe(client):
    token = register_and_token(client, "a@example.com")
    recipe = create_recipe(client, token)
    res = client.post(
        "/api/meal-plan",
        json={
            "plan_date": "2026-07-13",
            "meal": "dinner",
            "food_id": 1,
            "quantity_g": 100,
            "recipe_id": recipe["id"],
            "quantity_servings": 1,
        },
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_rejects_neither_food_nor_recipe(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/meal-plan", json={"plan_date": "2026-07-13", "meal": "dinner"}, headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_list_filters_by_date_range_and_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-20", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(other_token),
    )

    res = client.get(
        "/api/meal-plan?start_date=2026-07-10&end_date=2026-07-16", headers=auth_headers(token)
    )
    assert res.status_code == 200
    entries = res.json()
    assert len(entries) == 1
    assert entries[0]["plan_date"] == "2026-07-13"


def test_delete_entry(client):
    token = register_and_token(client, "a@example.com")
    created = client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    ).json()

    res = client.delete(f"/api/meal-plan/{created['id']}", headers=auth_headers(token))
    assert res.status_code == 204

    remaining = client.get(
        "/api/meal-plan?start_date=2026-07-01&end_date=2026-07-31", headers=auth_headers(token)
    ).json()
    assert remaining == []


def test_shopping_list_aggregates_food_and_recipe_entries(client):
    token = register_and_token(client, "a@example.com")
    recipe = create_recipe(client, token)  # 200g chicken + 100g rice per 2 servings -> 100g/50g per serving

    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-14", "meal": "dinner", "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/meal-plan/shopping-list?start_date=2026-07-10&end_date=2026-07-16", headers=auth_headers(token)
    )
    assert res.status_code == 200
    items = {i["food_name"]: i["quantity_g"] for i in res.json()["items"]}
    assert items["chicken"] == pytest.approx(150 + 100)  # 150g direct + 100g from 1 serving of recipe
    assert items["rice"] == pytest.approx(50)  # 1 serving of recipe's 100g/2 servings


def test_mark_eaten_creates_diary_entry_and_removes_plan_entry(client):
    token = register_and_token(client, "a@example.com")
    created = client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    ).json()

    res = client.post(f"/api/meal-plan/{created['id']}/mark-eaten", headers=auth_headers(token))
    assert res.status_code == 201
    diary_entry = res.json()
    assert diary_entry["entry_date"] == "2026-07-13"
    assert diary_entry["food_name"] == "chicken"
    assert diary_entry["quantity_g"] == 150

    day = client.get("/api/diary?entry_date=2026-07-13", headers=auth_headers(token)).json()
    assert len(day["entries"]) == 1

    remaining = client.get(
        "/api/meal-plan?start_date=2026-07-01&end_date=2026-07-31", headers=auth_headers(token)
    ).json()
    assert remaining == []


def test_cannot_access_other_users_entry(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    created = client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    ).json()

    res = client.delete(f"/api/meal-plan/{created['id']}", headers=auth_headers(other_token))
    assert res.status_code == 404

    res = client.post(f"/api/meal-plan/{created['id']}/mark-eaten", headers=auth_headers(other_token))
    assert res.status_code == 404
