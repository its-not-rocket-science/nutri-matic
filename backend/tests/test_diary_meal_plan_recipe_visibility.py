"""Hardening prompt 6 regression: logging a recipe to the diary or meal
plan used to require outright ownership (`recipe.user_id ==
current_user.id`), so a suggested public/stock or explicitly shared
recipe could never actually be logged even though it was fully visible
to the caller everywhere else in the app. Fixed by routing all three
create-time checks (diary create_entry, diary copy_day,
meal_plan._validate_food_or_recipe) through the same
recipe_access.is_recipe_visible rule used for read access. These tests
prove: (1) public/shared recipes now work, (2) a private recipe
belonging to someone else, not shared, is still rejected."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, Recipe
from app.reference_patterns import AMINO_ACIDS

FOOD_ID = 1


@pytest.fixture
def client_and_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSessionLocal()
    db.add(Food(id=FOOD_ID, name="Lentils, cooked", protein_g_per_100g=9, amino_acids=dict.fromkeys(AMINO_ACIDS, 20)))
    db.commit()
    db.close()

    yield TestClient(app), TestSessionLocal
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def make_recipe(client, token, name="Owner's recipe"):
    return client.post(
        "/api/recipes",
        json={"name": name, "servings": 1, "ingredients": [{"food_id": FOOD_ID, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()


def flip_public(session_factory, recipe_id):
    db = session_factory()
    recipe = db.get(Recipe, recipe_id)
    recipe.is_public = True
    db.commit()
    db.close()


@pytest.mark.parametrize(
    "path, entry_payload",
    [
        ("/api/diary", {"entry_date": "2026-07-20", "meal": "breakfast"}),
        ("/api/meal-plan", {"plan_date": "2026-07-20", "meal": "breakfast"}),
    ],
)
def test_public_recipe_can_be_logged_by_a_non_owner(client_and_session, path, entry_payload):
    client, Session = client_and_session
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = make_recipe(client, owner_token)
    flip_public(Session, recipe["id"])

    res = client.post(
        path,
        json={**entry_payload, "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(other_token),
    )
    assert res.status_code == 201, res.json()


@pytest.mark.parametrize(
    "path, entry_payload",
    [
        ("/api/diary", {"entry_date": "2026-07-20", "meal": "breakfast"}),
        ("/api/meal-plan", {"plan_date": "2026-07-20", "meal": "breakfast"}),
    ],
)
def test_shared_recipe_can_be_logged_by_the_recipient(client_and_session, path, entry_payload):
    client, Session = client_and_session
    owner_token = register_and_token(client, "owner@example.com")
    recipient_token = register_and_token(client, "recipient@example.com")
    recipe = make_recipe(client, owner_token)
    client.post(
        f"/api/recipes/{recipe['id']}/shares",
        json={"email": "recipient@example.com"},
        headers=auth_headers(owner_token),
    )

    res = client.post(
        path,
        json={**entry_payload, "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(recipient_token),
    )
    assert res.status_code == 201, res.json()


@pytest.mark.parametrize(
    "path, entry_payload",
    [
        ("/api/diary", {"entry_date": "2026-07-20", "meal": "breakfast"}),
        ("/api/meal-plan", {"plan_date": "2026-07-20", "meal": "breakfast"}),
    ],
)
def test_private_unshared_recipe_still_rejected_for_a_stranger(client_and_session, path, entry_payload):
    client, Session = client_and_session
    owner_token = register_and_token(client, "owner@example.com")
    stranger_token = register_and_token(client, "stranger@example.com")
    recipe = make_recipe(client, owner_token)

    res = client.post(
        path,
        json={**entry_payload, "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(stranger_token),
    )
    assert res.status_code == 422


def test_copy_day_carries_over_a_public_recipe_owned_by_someone_else(client_and_session):
    client, Session = client_and_session
    owner_token = register_and_token(client, "owner@example.com")
    other_token = register_and_token(client, "other@example.com")
    recipe = make_recipe(client, owner_token)
    flip_public(Session, recipe["id"])

    client.post(
        "/api/diary",
        json={
            "entry_date": "2026-07-20",
            "meal": "breakfast",
            "recipe_id": recipe["id"],
            "quantity_servings": 1,
        },
        headers=auth_headers(other_token),
    )

    res = client.post(
        "/api/diary/copy-day?source_date=2026-07-20&target_date=2026-07-21",
        headers=auth_headers(other_token),
    )
    assert res.status_code == 201
    assert len(res.json()) == 1

    target_day = client.get("/api/diary?entry_date=2026-07-21", headers=auth_headers(other_token)).json()
    assert len(target_day["entries"]) == 1
    assert target_day["entries"][0]["recipe_id"] == recipe["id"]
