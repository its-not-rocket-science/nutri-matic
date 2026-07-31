"""Prompt 6.1: ranked best sources of one nutrient, across ingredients and
recipes — reuses diary.py's _rank_foods_by_nutrient/_rank_recipes_by_nutrient
(same pool gap-suggestions/meal-optimize/plan-optimize already draw from),
plus Hardening Prompt 4's practicality filter for food results."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS


def _food(id_, name, data_type=None):
    return Food(id=id_, name=name, protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS, None), data_type=data_type)


@pytest.fixture
def seeded():
    """Yields (client, seed) — seed(rows) takes (id, name, iron_amount, data_type)
    tuples and commits Food + an "iron" FoodNutrient row for each."""
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

    def seed(rows):
        db = TestSession()
        for id_, name, _iron, data_type in rows:
            db.add(_food(id_, name, data_type))
        db.flush()
        for id_, _name, iron, _data_type in rows:
            db.add(FoodNutrient(food_id=id_, nutrient_key="iron", amount_per_100g=iron))
        db.commit()
        db.close()

    yield TestClient(app), seed
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def set_dietary_pattern(client, token, dietary_pattern):
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    owner = next(p for p in profiles if p["is_account_owner"])
    client.put(
        f"/api/profiles/{owner['id']}",
        json={
            "name": owner["name"], "sex": None, "birth_year": None, "activity_level": None,
            "is_pregnant": False, "is_lactating": False, "weight_kg": None, "height_cm": None,
            "dietary_pattern": dietary_pattern,
        },
        headers=auth_headers(token),
    )


def test_unknown_nutrient_key_is_rejected(seeded):
    client, _seed = seeded
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/search/nutrient-sources?nutrient_key=not_a_real_nutrient", headers=auth_headers(token))
    assert res.status_code == 422


def test_ranks_curated_foods_by_amount(seeded):
    client, seed = seeded
    # "spinach, raw" and "broccoli, raw" are both curated (suitable for
    # direct suggestion) — see candidate_metadata.CURATED_FOODS.
    seed([
        (1, "Spinach, raw", 3.0, None),
        (2, "Broccoli, raw", 1.0, None),
    ])

    token = register_and_token(client, "a@example.com")
    res = client.get("/api/search/nutrient-sources?nutrient_key=iron", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    names = [s["name"] for s in body["foods"]]
    assert names.index("Spinach, raw") < names.index("Broccoli, raw")
    assert body["foods"][0]["kind"] == "food"
    assert body["foods"][0]["per"] == "100g"
    assert body["foods"][0]["unit"] == "mg"


def test_excludes_branded_foods(seeded):
    client, seed = seeded
    seed([
        (1, "Spinach, raw", 3.0, None),
        (2, "Generic Brand Iron Blend 9000", 500.0, "branded_food"),
    ])

    token = register_and_token(client, "a@example.com")
    res = client.get("/api/search/nutrient-sources?nutrient_key=iron", headers=auth_headers(token))
    names = [s["name"] for s in res.json()["foods"]]
    assert "Generic Brand Iron Blend 9000" not in names


def test_excludes_impractical_foods(seeded):
    client, seed = seeded
    seed([
        (1, "Spinach, raw", 3.0, None),
        # matches candidate_metadata.EXCLUDED_KEYWORDS ("baking powder") —
        # mathematically iron-dense, never a real standalone suggestion.
        (2, "Baking powder, double acting", 500.0, None),
    ])

    token = register_and_token(client, "a@example.com")
    res = client.get("/api/search/nutrient-sources?nutrient_key=iron", headers=auth_headers(token))
    names = [s["name"] for s in res.json()["foods"]]
    assert "Baking powder, double acting" not in names


def test_respects_dietary_exclusions(seeded):
    client, seed = seeded
    seed([
        (1, "Spinach, raw", 3.0, None),
        (2, "Chicken breast", 5.0, None),  # curated, but "poultry" is a vegan exclusion
    ])

    token = register_and_token(client, "a@example.com")
    set_dietary_pattern(client, token, "vegan")
    res = client.get("/api/search/nutrient-sources?nutrient_key=iron", headers=auth_headers(token))
    names = [s["name"] for s in res.json()["foods"]]
    assert "Chicken breast" not in names
    assert "Spinach, raw" in names


def test_avoid_severity_constraint_is_retained_but_flagged(seeded):
    """filter_excluded_foods only ever drops a hard exclusion — an "avoid"-
    severity preference is deliberately retained (dietary_filter.py's own
    distinction), same as existing food/recipe search. It must still carry
    a dietary_status here rather than rendering identically to a fully
    unconstrained result."""
    client, seed = seeded
    seed([(1, "Almonds", 3.0, None)])  # curated; "almond" matches the tree_nut tag

    token = register_and_token(client, "a@example.com")
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    owner = next(p for p in profiles if p["is_account_owner"])
    res = client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "preference", "tag": "tree_nut", "severity": "avoid"},
        headers=auth_headers(token),
    )
    assert res.status_code == 201

    res = client.get("/api/search/nutrient-sources?nutrient_key=iron", headers=auth_headers(token))
    body = res.json()
    almonds = next(s for s in body["foods"] if s["name"] == "Almonds")
    assert almonds["dietary_status"] is not None
    assert almonds["dietary_status"]["status"] == "avoid"


def test_includes_recipes(seeded):
    client, seed = seeded
    seed([(1, "Spinach, raw", 3.0, None)])

    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "Iron-rich bowl", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=auth_headers(token),
    ).json()

    res = client.get("/api/search/nutrient-sources?nutrient_key=iron", headers=auth_headers(token))
    body = res.json()
    recipe_result = next((s for s in body["recipes"] if s["kind"] == "recipe"), None)
    assert recipe_result is not None
    assert recipe_result["recipe_id"] == recipe["id"]
    assert recipe_result["per"] == "serving"
    # 200g of spinach (3mg/100g) at 1 serving of a 1-serving recipe = 6mg
    assert recipe_result["amount"] == pytest.approx(6.0)


def test_limit_is_respected(seeded):
    client, seed = seeded
    seed([
        (1, "Spinach, raw", 5.0, None),
        (2, "Broccoli, raw", 4.0, None),
        (3, "Carrots, raw", 3.0, None),
    ])

    token = register_and_token(client, "a@example.com")
    res = client.get("/api/search/nutrient-sources?nutrient_key=iron&limit=2", headers=auth_headers(token))
    assert res.status_code == 200
    assert len(res.json()["foods"]) == 2
