"""API-level tests for the stock-recipe additions to routers/recipes.py and
routers/collections.py: the /robustness endpoint, is_stock/source
attribution fields, public visibility to an ordinary signed-in user, and
copy-to-my-recipes — the same visibility/ownership guarantees prompt
section 8 asks for, exercised through the real HTTP layer."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import (
    Collection,
    CollectionRecipe,
    Food,
    Recipe,
    RecipeIngredient,
    RecipeIngredientProvenance,
    RobustnessResult,
    User,
)
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

    recipe = Recipe(
        user_id=system_user.id, name="Stock Bean Chilli", servings=4, is_public=True,
        import_slug="bean_chilli_test", source_name="manual", source_url=None,
        match_coverage_lines=0.9, match_coverage_mass=0.85, unresolved_ingredients=["1 mystery spice mix"],
        stock_status="imported",
    )
    db.add(recipe)
    db.flush()
    ingredient = RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=100)
    db.add(ingredient)
    db.flush()
    db.add(RecipeIngredientProvenance(
        recipe_ingredient_id=ingredient.id, raw_text="1 onion, chopped",
        match_method="alias", match_confidence=0.95, match_relationship="exact",
    ))
    # a superseded historical analysis (prompt section 4) — must never be
    # what the /robustness endpoint returns, only the is_latest=True row
    db.add(RobustnessResult(
        recipe_id=recipe.id, model_version="0.9.0", simulation_count=100, random_seed=1, is_latest=False,
        metrics={"protein": {
            "baseline": 5.0, "median": 5.0, "p10": 4.0, "p90": 6.0, "cv": 0.1, "threshold": 4.0,
            "prob_above_threshold": 0.8, "top_influential": [], "optional_sensitivity": None,
            "unmatched_uncertainty_note": None, "display_rating": 2, "explanation": "stale",
            "not_calculated_reason": None,
        }},
        overall_rating=2, overall_explanation="Superseded analysis.",
    ))
    db.add(RobustnessResult(
        recipe_id=recipe.id, model_version="1.0.0", simulation_count=200, random_seed=42,
        metrics={"protein": {
            "baseline": 5.0, "median": 5.0, "p10": 4.5, "p90": 5.5, "cv": 0.05, "threshold": 4.0,
            "prob_above_threshold": 1.0, "top_influential": [], "optional_sensitivity": None,
            "unmatched_uncertainty_note": None, "display_rating": 5, "explanation": "stable",
            "not_calculated_reason": None,
        }},
        overall_rating=5, overall_explanation="Overall robustness is high.",
    ))

    collection = Collection(user_id=system_user.id, name="Budget Meals", is_public=True)
    db.add(collection)
    db.flush()
    db.add(CollectionRecipe(collection_id=collection.id, recipe_id=recipe.id, assignment_source="manual", approval_status="approved"))

    db.commit()
    recipe_id, collection_id = recipe.id, collection.id
    db.close()

    test_client = TestClient(app)
    test_client.stock_recipe_id = recipe_id
    test_client.stock_collection_id = collection_id
    yield test_client
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_stock_recipe_ingredient_exposes_match_provenance(client):
    """prompt section 8: alias/proxy confidence and relationship must be
    visible through the API, without this being read anywhere by
    aggregation.py (a separate assertion — see test_aggregation.py —
    that nothing in that module even looks at these fields)."""
    token = register_and_token(client, "user8@example.com")
    res = client.get(f"/api/recipes/{client.stock_recipe_id}", headers=auth_headers(token))
    ingredient = res.json()["ingredients"][0]
    assert ingredient["provenance"] == {
        "match_method": "alias", "match_confidence": 0.95, "match_relationship": "exact",
        "match_rationale": None, "match_preferred_fdc_id": None, "match_preferred_food_id": None,
        "match_used_fallback": None, "match_validation_warning": None,
    }


def test_ordinary_recipe_ingredient_has_no_provenance(client):
    token = register_and_token(client, "user9@example.com")
    create_res = client.post(
        "/api/recipes", json={"name": "My Own Recipe", "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    ingredient = create_res.json()["ingredients"][0]
    assert ingredient["provenance"] is None


def test_stock_recipe_visible_to_any_signed_in_user(client):
    token = register_and_token(client, "user1@example.com")
    res = client.get(f"/api/recipes/{client.stock_recipe_id}", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["is_stock"] is True
    assert body["is_owner"] is False
    assert body["is_public"] is True
    assert body["source_name"] == "manual"
    assert body["match_coverage_lines"] == 0.9
    assert body["unresolved_ingredients"] == ["1 mystery spice mix"]


def test_stock_recipe_appears_in_public_list(client):
    token = register_and_token(client, "user2@example.com")
    res = client.get("/api/recipes/public", headers=auth_headers(token))
    assert res.status_code == 200
    names = [r["name"] for r in res.json()]
    assert "Stock Bean Chilli" in names


def test_ordinary_user_cannot_mutate_stock_recipe(client):
    token = register_and_token(client, "user3@example.com")
    res = client.patch(
        f"/api/recipes/{client.stock_recipe_id}", json={"name": "Hacked"}, headers=auth_headers(token)
    )
    assert res.status_code == 404  # owner-only, and nobody but the system account owns it


def test_copy_to_my_recipes(client):
    token = register_and_token(client, "user4@example.com")
    res = client.post(f"/api/recipes/{client.stock_recipe_id}/copy", headers=auth_headers(token))
    assert res.status_code == 201
    body = res.json()
    assert body["is_owner"] is True
    assert body["is_stock"] is False  # the copy belongs to the ordinary user, not the system account
    assert body["name"] == "Stock Bean Chilli (copy)"
    assert len(body["ingredients"]) == 1


def test_robustness_endpoint_returns_analysis(client):
    token = register_and_token(client, "user5@example.com")
    res = client.get(f"/api/recipes/{client.stock_recipe_id}/robustness", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["overall_rating"] == 5
    assert body["metrics"]["protein"]["display_rating"] == 5
    assert body["model_version"] == "1.0.0"


def test_robustness_endpoint_null_for_unanalysed_recipe(client):
    token = register_and_token(client, "user6@example.com")
    create_res = client.post(
        "/api/recipes", json={"name": "My Own Recipe", "servings": 2, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    )
    recipe_id = create_res.json()["id"]

    res = client.get(f"/api/recipes/{recipe_id}/robustness", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json() is None


def test_stock_collection_visible_and_flagged(client):
    token = register_and_token(client, "user7@example.com")
    res = client.get(f"/api/collections/{client.stock_collection_id}", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["is_stock"] is True
    assert body["is_owner"] is False
    assert len(body["recipes"]) == 1


def test_system_account_cannot_log_in(client):
    res = client.post(
        "/api/auth/login", json={"email": "stock-recipes@nutrimatic.system", "password": "unguessable"}
    )
    assert res.status_code == 401
