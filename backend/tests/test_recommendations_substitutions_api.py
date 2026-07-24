"""API-level tests for /api/recommendations/substitutions — prompt 8."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, User
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
    rice = Food(id=1, name="White rice, cooked", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    lentils = Food(id=2, name="Lentils", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    db.add_all([rice, lentils])
    db.flush()
    db.add_all([
        FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
        FoodNutrient(food_id=1, nutrient_key="fiber_total", amount_per_100g=0.4),
        FoodNutrient(food_id=2, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=116.0),
    ])
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_substitution_suggestions_for_a_logged_recipe(client):
    token = register_and_token(client, "a@example.com")
    headers = auth_headers(token)

    # need the current user's own recipe to log via diary
    create_res = client.post(
        "/api/recipes", json={"name": "Rice Bowl", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 200}]},
        headers=headers,
    )
    recipe_id = create_res.json()["id"]
    client.post(
        "/api/recipes", json={"name": "Lentil Bowl", "servings": 1, "ingredients": [{"food_id": 2, "quantity_g": 224}]},
        headers=headers,
    )

    entry_res = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "recipe_id": recipe_id, "quantity_servings": 1},
        headers=headers,
    )
    entry_id = entry_res.json()["id"]

    res = client.get(
        "/api/recommendations/substitutions", params={"entry_id": entry_id}, headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["current_recipe_name"] == "Rice Bowl"


def test_plain_food_entry_cannot_be_substituted(client):
    token = register_and_token(client, "b@example.com")
    headers = auth_headers(token)
    entry_res = client.post(
        "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=headers,
    )
    entry_id = entry_res.json()["id"]

    res = client.get("/api/recommendations/substitutions", params={"entry_id": entry_id}, headers=headers)
    assert res.status_code == 422


def test_nonexistent_entry_404s(client):
    token = register_and_token(client, "c@example.com")
    res = client.get(
        "/api/recommendations/substitutions", params={"entry_id": 999999}, headers=auth_headers(token),
    )
    assert res.status_code == 404


def test_requires_authentication(client):
    res = client.get("/api/recommendations/substitutions", params={"entry_id": 1})
    assert res.status_code in (401, 403)


def _log_recipe_entry(client, headers, name, food_id, quantity_g, entry_date="2026-01-01"):
    recipe_id = client.post(
        "/api/recipes",
        json={"name": name, "servings": 1, "ingredients": [{"food_id": food_id, "quantity_g": quantity_g}]},
        headers=headers,
    ).json()["id"]
    entry = client.post(
        "/api/diary",
        json={"entry_date": entry_date, "meal": "lunch", "recipe_id": recipe_id, "quantity_servings": 1},
        headers=headers,
    ).json()
    return recipe_id, entry


class TestApplySubstitution:
    """Hardening prompt 6: POST /api/recommendations/substitutions/apply,
    the atomic replacement of a delete-then-recreate two-call pattern the
    frontend used to do itself."""

    def test_successful_atomic_replacement(self, client):
        token = register_and_token(client, "owner@example.com")
        headers = auth_headers(token)
        current_recipe_id, entry = _log_recipe_entry(client, headers, "Rice Bowl", 1, 200)
        replacement_recipe_id, _ = _log_recipe_entry(client, headers, "Lentil Bowl", 2, 224, entry_date="2026-01-02")

        res = client.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe_id,
                "replacement_recipe_id": replacement_recipe_id,
                "replacement_servings": 2,
            },
            headers=headers,
        )
        assert res.status_code == 200, res.json()
        body = res.json()
        assert body == {
            "entry_id": entry["id"], "source": "diary", "recipe_id": replacement_recipe_id,
            "recipe_name": "Lentil Bowl", "quantity_servings": 2,
        }

        day = client.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        updated = next(e for e in day["entries"] if e["id"] == entry["id"])
        assert updated["recipe_id"] == replacement_recipe_id
        assert updated["quantity_servings"] == 2

    def test_stale_expected_recipe_id_rejected_with_409(self, client):
        token = register_and_token(client, "owner2@example.com")
        headers = auth_headers(token)
        current_recipe_id, entry = _log_recipe_entry(client, headers, "Rice Bowl", 1, 200)
        replacement_recipe_id, _ = _log_recipe_entry(client, headers, "Lentil Bowl", 2, 224, entry_date="2026-01-02")

        res = client.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": replacement_recipe_id,  # wrong — entry is still current_recipe_id
                "replacement_recipe_id": replacement_recipe_id,
                "replacement_servings": 1,
            },
            headers=headers,
        )
        assert res.status_code == 409

        # original entry untouched
        day = client.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        untouched = next(e for e in day["entries"] if e["id"] == entry["id"])
        assert untouched["recipe_id"] == current_recipe_id

    def test_duplicate_apply_rejected_on_second_attempt(self, client):
        token = register_and_token(client, "owner3@example.com")
        headers = auth_headers(token)
        current_recipe_id, entry = _log_recipe_entry(client, headers, "Rice Bowl", 1, 200)
        replacement_recipe_id, _ = _log_recipe_entry(client, headers, "Lentil Bowl", 2, 224, entry_date="2026-01-02")

        payload = {
            "entry_id": entry["id"], "source": "diary",
            "expected_current_recipe_id": current_recipe_id,
            "replacement_recipe_id": replacement_recipe_id,
            "replacement_servings": 1,
        }
        first = client.post("/api/recommendations/substitutions/apply", json=payload, headers=headers)
        assert first.status_code == 200

        second = client.post("/api/recommendations/substitutions/apply", json=payload, headers=headers)
        assert second.status_code == 409

    def test_cannot_apply_to_another_users_entry(self, client):
        owner_token = register_and_token(client, "owner4@example.com")
        owner_headers = auth_headers(owner_token)
        attacker_token = register_and_token(client, "attacker@example.com")
        attacker_headers = auth_headers(attacker_token)

        current_recipe_id, entry = _log_recipe_entry(client, owner_headers, "Rice Bowl", 1, 200)
        replacement_recipe_id, _ = _log_recipe_entry(
            client, attacker_headers, "Lentil Bowl", 2, 224, entry_date="2026-01-02"
        )

        res = client.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe_id,
                "replacement_recipe_id": replacement_recipe_id,
                "replacement_servings": 1,
            },
            headers=attacker_headers,
        )
        assert res.status_code == 404  # attacker's own profile has no entry with this id

        day = client.get("/api/diary?entry_date=2026-01-01", headers=owner_headers).json()
        untouched = next(e for e in day["entries"] if e["id"] == entry["id"])
        assert untouched["recipe_id"] == current_recipe_id

    def test_inaccessible_replacement_recipe_rejected(self, client):
        token = register_and_token(client, "owner5@example.com")
        headers = auth_headers(token)
        other_token = register_and_token(client, "other@example.com")
        other_headers = auth_headers(other_token)

        current_recipe_id, entry = _log_recipe_entry(client, headers, "Rice Bowl", 1, 200)
        private_recipe_id = client.post(
            "/api/recipes",
            json={"name": "Other's Private Recipe", "servings": 1, "ingredients": [{"food_id": 2, "quantity_g": 100}]},
            headers=other_headers,
        ).json()["id"]

        res = client.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe_id,
                "replacement_recipe_id": private_recipe_id,
                "replacement_servings": 1,
            },
            headers=headers,
        )
        assert res.status_code == 404

        day = client.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        untouched = next(e for e in day["entries"] if e["id"] == entry["id"])
        assert untouched["recipe_id"] == current_recipe_id

    def test_plain_food_entry_cannot_be_substituted_via_apply(self, client):
        token = register_and_token(client, "owner6@example.com")
        headers = auth_headers(token)
        entry = client.post(
            "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
            headers=headers,
        ).json()
        replacement_recipe_id, _ = _log_recipe_entry(client, headers, "Lentil Bowl", 2, 224, entry_date="2026-01-02")

        res = client.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": replacement_recipe_id,
                "replacement_recipe_id": replacement_recipe_id,
                "replacement_servings": 1,
            },
            headers=headers,
        )
        assert res.status_code == 422

    def test_requires_authentication_for_apply(self, client):
        res = client.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": 1, "source": "diary",
                "expected_current_recipe_id": 1, "replacement_recipe_id": 2, "replacement_servings": 1,
            },
        )
        assert res.status_code in (401, 403)
