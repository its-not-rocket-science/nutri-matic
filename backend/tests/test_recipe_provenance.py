"""API-level tests for RecipeOut.educational_note — prompt section 6/7:
the frontend needs to tell a structured-data import, an ordinary
manually-curated recipe, and a deliberately adapted/composited recipe
(e.g. prompt section 7's generic muesli stand-in) apart, and
educational_note is the signal that drives that distinction. See
recipes/[id]/+page.svelte's `provenance` derived value."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Food, Recipe, RecipeIngredient, User
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    system_user = User(email="stock-recipes@nutrimatic.system", password_hash=hash_password("unguessable"), is_system=True)
    db.add(system_user)
    db.flush()

    food = Food(id=1, name="Onions, raw", protein_g_per_100g=1.1, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    db.add(food)
    db.flush()

    def make_recipe(name, slug, **kwargs):
        recipe = Recipe(
            user_id=system_user.id, name=name, servings=2, is_public=True, import_slug=slug,
            stock_status="imported", **kwargs,
        )
        db.add(recipe)
        db.flush()
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=100))
        return recipe

    imported = make_recipe(
        "Scraped Recipe", "scraped_test", source_name="schema_org", source_url="https://example.com/r",
    )
    manual_with_link = make_recipe(
        "Manual Recipe With Link", "manual_link_test", source_name="manual", source_url="https://example.com/inspiration",
    )
    manual_no_link = make_recipe("Manual Recipe No Link", "manual_no_link_test", source_name="manual", source_url=None)
    adapted = make_recipe(
        "Generic Muesli", "adapted_muesli_test", source_name="manual", source_url=None,
        educational_note="A generic composite of rolled oats, dried fruit, mixed nuts and seeds, built to "
                          "represent muesli generically rather than transcribe one specific product.",
    )

    db.commit()
    ids = {
        "imported": imported.id, "manual_with_link": manual_with_link.id,
        "manual_no_link": manual_no_link.id, "adapted": adapted.id,
    }
    db.close()

    test_client = TestClient(app)
    test_client.recipe_ids = ids
    yield test_client
    app.dependency_overrides.clear()


def _token(client, email):
    res = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def test_structured_import_has_no_educational_note(client):
    token = _token(client, "u1@example.com")
    res = client.get(f"/api/recipes/{client.recipe_ids['imported']}", headers={"Authorization": f"Bearer {token}"})
    body = res.json()
    assert body["source_name"] == "schema_org"
    assert body["educational_note"] is None


def test_manual_recipe_with_link_has_no_educational_note(client):
    token = _token(client, "u2@example.com")
    res = client.get(
        f"/api/recipes/{client.recipe_ids['manual_with_link']}", headers={"Authorization": f"Bearer {token}"}
    )
    body = res.json()
    assert body["source_name"] == "manual"
    assert body["source_url"] == "https://example.com/inspiration"
    assert body["educational_note"] is None


def test_adapted_composite_exposes_educational_note(client):
    token = _token(client, "u3@example.com")
    res = client.get(f"/api/recipes/{client.recipe_ids['adapted']}", headers={"Authorization": f"Bearer {token}"})
    body = res.json()
    assert body["source_name"] == "manual"
    assert body["educational_note"] is not None
    assert "muesli" in body["educational_note"].lower()


def test_ordinary_user_recipe_has_no_educational_note(client):
    token = _token(client, "u4@example.com")
    create_res = client.post(
        "/api/recipes",
        json={"name": "My Own Recipe", "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = create_res.json()
    assert body["is_stock"] is False
    assert body["educational_note"] is None
