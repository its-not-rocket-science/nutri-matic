"""Table-driven API parameter validation tests for /api/recommendations/*
— hardening prompt 2. Mostly asserts 422 (FastAPI/Pydantic's own
Query(...) constraints reject before the endpoint body runs at all for
type/range violations; the handful of semantic checks — scope
combinations, unknown nutrient keys, date-range internal consistency —
are raised explicitly by the endpoint, still before any entry-loading
database work, see recommendation_params.py)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
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
    rice = Food(
        id=1, name="White rice, cooked", protein_g_per_100g=2.7,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add(rice)
    db.flush()
    db.add(FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def token(client):
    return register_and_token(client, "a@example.com")


# --- servings (recipe_id scope) --------------------------------------------

@pytest.mark.parametrize("servings", [0, -1, -0.5, 21, 1000, float("nan"), float("inf")])
def test_invalid_servings_rejected(client, token, servings):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"recipe_id": 1, "servings": servings},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


@pytest.mark.parametrize("servings", [0.5, 1, 1.0, 20])
def test_valid_servings_accepted(client, token, servings):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"recipe_id": 999999, "servings": servings},  # nonexistent recipe -> 404, not a servings rejection
        headers=auth_headers(token),
    )
    assert res.status_code == 404  # proves servings itself passed validation


# --- max_suggestions --------------------------------------------------------

@pytest.mark.parametrize("max_suggestions", [0, -1, 11, 1000])
def test_excessive_or_invalid_max_suggestions_rejected(client, token, max_suggestions):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "max_suggestions": max_suggestions},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


@pytest.mark.parametrize("max_suggestions", [1, 5, 10])
def test_valid_max_suggestions_accepted(client, token, max_suggestions):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "max_suggestions": max_suggestions},
        headers=auth_headers(token),
    )
    assert res.status_code == 200


# --- max_additional_energy ---------------------------------------------------

@pytest.mark.parametrize("energy", [-1, -0.01, float("nan"), float("inf"), 5001, 1_000_000])
def test_invalid_energy_values_rejected(client, token, energy):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "max_additional_energy": energy},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


@pytest.mark.parametrize("energy", [0, 50, 200, 5000])
def test_valid_energy_values_accepted(client, token, energy):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "max_additional_energy": energy},
        headers=auth_headers(token),
    )
    assert res.status_code == 200


# --- date ranges -------------------------------------------------------------

def test_reversed_date_range_rejected(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"start_date": "2026-01-10", "end_date": "2026-01-01", "source": "meal_plan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_oversized_date_range_rejected(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"start_date": "2026-01-01", "end_date": "2026-12-31", "source": "meal_plan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-01-01"},  # end_date missing
        {"end_date": "2026-01-10"},  # start_date missing
    ],
)
def test_incomplete_date_pair_rejected(client, token, params):
    res = client.get(
        "/api/recommendations/ingredients",
        params={**params, "source": "meal_plan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_valid_date_range_accepted(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"start_date": "2026-01-01", "end_date": "2026-01-07", "source": "meal_plan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200


# --- incompatible scope combinations ----------------------------------------

@pytest.mark.parametrize(
    "params",
    [
        {},  # no scope at all
        {"entry_date": "2026-01-01", "recipe_id": 1},  # two scopes
        {"entry_date": "2026-01-01", "start_date": "2026-01-01", "end_date": "2026-01-05", "source": "meal_plan"},
        {"recipe_id": 1, "meal": "lunch"},  # meal incompatible with recipe_id
        {"start_date": "2026-01-01", "end_date": "2026-01-05", "meal": "lunch", "source": "meal_plan"},
        {"start_date": "2026-01-01", "end_date": "2026-01-05", "source": "diary"},  # range requires meal_plan
    ],
)
def test_incompatible_scope_combinations_rejected(client, token, params):
    res = client.get("/api/recommendations/ingredients", params=params, headers=auth_headers(token))
    assert res.status_code == 422


# --- priority_nutrients -------------------------------------------------------

def test_unknown_nutrient_key_rejected(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "priority_nutrients": "iron,not_a_real_nutrient"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422
    assert "not_a_real_nutrient" in res.json()["detail"]


def test_duplicate_and_whitespace_heavy_nutrient_input_accepted(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "priority_nutrients": " iron , iron,  folate ,,"},
        headers=auth_headers(token),
    )
    assert res.status_code == 200


def test_too_many_priority_nutrients_rejected(client, token):
    many = ",".join(f"fake_{i}" for i in range(30))
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "priority_nutrients": many},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


# --- meal/source/goal enums --------------------------------------------------

def test_invalid_meal_rejected(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "meal": "brunch"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_invalid_source_rejected(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"entry_date": "2026-01-01", "source": "not_a_real_source"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_invalid_goal_rejected(client, token):
    res = client.get(
        "/api/recommendations/recipes",
        params={"entry_date": "2026-01-01", "goal": "not_a_real_goal"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


# --- identifiers must be positive integers -----------------------------------

@pytest.mark.parametrize("recipe_id", [0, -1, -100])
def test_non_positive_recipe_id_rejected(client, token, recipe_id):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"recipe_id": recipe_id},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


@pytest.mark.parametrize("entry_id", [0, -1])
def test_non_positive_entry_id_rejected(client, token, entry_id):
    res = client.get(
        "/api/recommendations/substitutions",
        params={"entry_id": entry_id},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_non_integer_recipe_id_rejected(client, token):
    res = client.get(
        "/api/recommendations/ingredients",
        params={"recipe_id": "not-a-number"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


# --- basic shape validation happens before database work --------------------

def test_invalid_scope_never_reaches_eligibility_check(client, token, monkeypatch):
    """A request that fails basic shape/semantic validation (here: a
    reversed date range) must never reach assess_eligibility — the first
    real database query the endpoint itself makes (auth/profile
    resolution is a separate, unavoidable dependency layer, not what this
    claim is about)."""
    import app.routers.recommendations as recommendations_module

    def _boom(*a, **k):
        raise AssertionError("assess_eligibility was called before validation completed")

    monkeypatch.setattr(recommendations_module, "assess_eligibility", _boom)
    res = client.get(
        "/api/recommendations/ingredients",
        params={"start_date": "2026-01-10", "end_date": "2026-01-01", "source": "meal_plan"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422
