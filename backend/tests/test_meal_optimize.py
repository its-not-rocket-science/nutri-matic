import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS


def _add_food(client, food_id, name, iron, energy, protein=25):
    """Adds one more Food/FoodNutrient row to this test's isolated in-memory
    db — kept out of the shared `client` fixture so it doesn't change the
    candidate pool (and expected suggestion counts) for unrelated tests."""
    db = next(app.dependency_overrides[get_db]())
    db.add(Food(id=food_id, name=name, protein_g_per_100g=protein, amino_acids=dict.fromkeys(AMINO_ACIDS, None)))
    db.flush()
    db.add(FoodNutrient(food_id=food_id, nutrient_key="iron", amount_per_100g=iron))
    db.add(FoodNutrient(food_id=food_id, nutrient_key="energy", amount_per_100g=energy))
    db.commit()
    db.close()


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
    rice_white = Food(id=1, name="Rice, white, cooked", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    rice_brown = Food(id=2, name="Rice, brown, cooked", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    spinach = Food(id=3, name="Spinach, raw", protein_g_per_100g=3, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add_all([rice_white, rice_brown, spinach])
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=1.0),
            FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
            FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=2.0),
            FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=130.0),
            FoodNutrient(food_id=3, nutrient_key="iron", amount_per_100g=3.0),
            FoodNutrient(food_id=3, nutrient_key="energy", amount_per_100g=20.0),
        ]
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_meal_optimize_returns_ranked_suggestions(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["meal"] == "lunch"
    assert body["target_nutrient_key"] == "iron"
    # swap (rice white -> brown), add spinach, and add brown rice (a
    # genuinely different action from the swap — keep the white rice AND
    # add brown rice, vs. replace it) are all real, distinct, computed
    # improvements
    assert len(body["suggestions"]) == 3

    swap = next(s for s in body["suggestions"] if s["action"] == "swap")
    assert swap["food_name"] == "Rice, brown, cooked"
    assert swap["replaces_food_name"] == "Rice, white, cooked"

    add_spinach = next(s for s in body["suggestions"] if s["action"] == "add" and s["food_name"] == "Spinach, raw")
    assert add_spinach["quantity_g"] == pytest.approx(30.0)

    # the food already in this meal (white rice) is never suggested as an
    # "add" candidate — that's just "log more of what you already have"
    assert all(
        not (s["action"] == "add" and s["food_name"] == "Rice, white, cooked") for s in body["suggestions"]
    )

    # swap has no calorie cost (same energy), so it should rank above the add
    assert body["suggestions"][0]["action"] == "swap"


def test_meal_optimize_includes_real_cost_when_priced(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.put(
        "/api/food-prices/3",
        json={"package_price": 1.0, "package_quantity_g": 100.0},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    body = res.json()
    add_spinach = next(s for s in body["suggestions"] if s["action"] == "add" and s["food_name"] == "Spinach, raw")
    # 1.00/100g * 30g trial quantity = 0.30
    assert add_spinach["estimated_cost"] == pytest.approx(0.30)
    assert "rationale" in add_spinach and len(add_spinach["rationale"]) > 0


def test_meal_optimize_max_additional_cost_filters_suggestions(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.put(
        "/api/food-prices/3",
        json={"package_price": 100.0, "package_quantity_g": 100.0},  # very expensive spinach
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch&max_additional_cost=1.0",
        headers=auth_headers(token),
    )
    body = res.json()
    assert all(s["food_name"] != "Spinach, raw" for s in body["suggestions"])


def test_meal_optimize_none_when_meal_empty(client):
    token = register_and_token(client, "a@example.com")
    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    assert res.status_code == 200
    assert res.json() is None


def test_meal_optimize_suggests_adding_a_recipe(client):
    _add_food(client, 4, "Liver, cooked", iron=10.0, energy=130.0)
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    recipe_res = client.post(
        "/api/recipes",
        json={"name": "Liver bowl", "servings": 2, "ingredients": [{"food_id": 4, "quantity_g": 200}]},
        headers=auth_headers(token),
    )
    recipe_id = recipe_res.json()["id"]

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    body = res.json()
    add_recipe = next(s for s in body["suggestions"] if s["action"] == "add_recipe")
    assert add_recipe["recipe_id"] == recipe_id
    assert add_recipe["food_name"] == "Liver bowl"
    assert add_recipe["quantity_servings"] == pytest.approx(1.0)
    assert add_recipe["food_id"] is None
    assert add_recipe["quantity_g"] is None
    # 1 serving = 100g liver -> +10mg iron = the strongest single suggestion
    assert body["suggestions"][0]["action"] == "add_recipe"


def test_meal_optimize_recipe_suggestion_excludes_already_logged_recipe(client):
    _add_food(client, 4, "Liver, cooked", iron=10.0, energy=130.0)
    token = register_and_token(client, "a@example.com")
    recipe_res = client.post(
        "/api/recipes",
        json={"name": "Liver bowl", "servings": 2, "ingredients": [{"food_id": 4, "quantity_g": 200}]},
        headers=auth_headers(token),
    )
    recipe_id = recipe_res.json()["id"]
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "recipe_id": recipe_id, "quantity_servings": 1},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(token)
    )
    body = res.json()
    assert body is None or all(s["action"] != "add_recipe" for s in body["suggestions"])


def test_meal_optimize_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-13&meal=lunch", headers=auth_headers(other_token)
    )
    assert res.json() is None
