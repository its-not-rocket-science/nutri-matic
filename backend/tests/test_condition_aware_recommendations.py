"""Prompt 3.2: gap-suggestions, meal-optimize, and plan-optimize become
condition-aware in two distinct ways —

1. A profile with an unacknowledged medical dietary constraint (including
   one of prompt 3.1's informational conditions, e.g. type 2 diabetes)
   gets every one of these three endpoints disabled by default, reusing
   the EXACT SAME guardrail /api/recommendations/* already enforces
   (recommendation_safety.assess_eligibility) rather than a new one.
2. A lactose/gluten condition excludes/flags the relevant foods from
   candidate ranking the same way an allergy already does — this was
   already true structurally (both conditions create ordinary
   DietaryConstraint rows that dietary_filter.py enforces regardless of
   category), confirmed here end-to-end rather than assumed.

Type 2 diabetes glycaemic-load weighting is investigated and NOT
implemented — USDA FoodData Central carries no glycaemic-index/load data
for the large majority of foods, the same data gap documented for the
"longevity"/goal-library work (goal_nutrient_priorities.py) and the
methodology page's Goals section."""

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
    beef = Food(id=1, name="Beef, ground, cooked", protein_g_per_100g=26, amino_acids=dict.fromkeys(AMINO_ACIDS, 20))
    milk = Food(id=2, name="Milk, whole", protein_g_per_100g=3.4, amino_acids=dict.fromkeys(AMINO_ACIDS, 15))
    db.add_all([beef, milk])
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=2.6),
            FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=10.0),
            FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=0.03),
            FoodNutrient(food_id=2, nutrient_key="calcium", amount_per_100g=125.0),
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


def owner_profile_id(client, token):
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    return next(p for p in profiles if p["is_account_owner"])["id"]


def log_beef(client, token, entry_date="2026-07-20"):
    client.post(
        "/api/diary",
        json={"entry_date": entry_date, "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )


# --- medical-constraint guardrail (requirement 1) -----------------------


def test_gap_suggestions_disabled_by_unacknowledged_medical_condition(client):
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)
    log_beef(client, token)
    client.post(f"/api/profiles/{profile_id}/conditions/type_2_diabetes", headers=auth_headers(token))

    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-20", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["disabled_reason_code"] == "unacknowledged_medical_constraint"
    assert body["nutrient_key"] is None
    assert body["foods"] == []


def test_meal_optimize_disabled_by_unacknowledged_medical_condition(client):
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)
    log_beef(client, token)
    client.post(f"/api/profiles/{profile_id}/conditions/type_2_diabetes", headers=auth_headers(token))

    res = client.get(
        "/api/diary/meal-optimize?entry_date=2026-07-20&meal=breakfast", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["disabled_reason_code"] == "unacknowledged_medical_constraint"
    assert body["meal"] == "breakfast"
    assert body["target_nutrient_key"] is None
    assert body["suggestions"] == []


def test_plan_optimize_disabled_by_unacknowledged_medical_condition(client):
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(f"/api/profiles/{profile_id}/conditions/type_2_diabetes", headers=auth_headers(token))

    res = client.get(
        "/api/meal-plan/optimize?start_date=2026-07-13&end_date=2026-07-19", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["disabled_reason_code"] == "unacknowledged_medical_constraint"
    assert body["target_nutrient_key"] is None
    assert body["suggestions"] == []


def test_gap_suggestions_re_enabled_after_acknowledging(client):
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)
    log_beef(client, token)
    client.post(f"/api/profiles/{profile_id}/conditions/type_2_diabetes", headers=auth_headers(token))
    client.post(f"/api/profiles/{profile_id}/medical-acknowledgement", headers=auth_headers(token))

    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-20", headers=auth_headers(token))
    body = res.json()
    assert body is not None
    assert body["disabled_reason_code"] is None
    assert body["nutrient_key"] is not None


def test_gap_suggestions_unaffected_by_a_hard_exclusion_condition(client):
    """A tag-mapped condition (gluten/lactose) is a DietaryConstraint like
    any allergy — it never triggers the medical-only guardrail above."""
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)
    log_beef(client, token)
    client.post(f"/api/profiles/{profile_id}/conditions/lactose_intolerance", headers=auth_headers(token))

    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-20", headers=auth_headers(token))
    body = res.json()
    assert body is not None
    assert body["disabled_reason_code"] is None


# --- exclusion/flagging (requirement 2) ----------------------------------


def test_gap_suggestions_still_offers_avoid_severity_food_for_lactose_intolerance(client):
    """Lactose intolerance is "avoid" severity, not "hard_exclude" —
    confirms it flags rather than over-excludes: milk still ranks as a
    candidate for calcium (the day's worst gap; beef alone has none)."""
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)
    log_beef(client, token)
    client.post(f"/api/profiles/{profile_id}/conditions/lactose_intolerance", headers=auth_headers(token))

    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-20", headers=auth_headers(token))
    body = res.json()
    assert body is not None
    food_names = [f["food_name"] for f in body["foods"]]
    assert "Milk, whole" in food_names


def test_gap_suggestions_hard_excludes_food_for_gluten_intolerance(client):
    token = register_and_token(client, "a@example.com")
    profile_id = owner_profile_id(client, token)

    db = next(app.dependency_overrides[get_db]())
    bread = Food(id=3, name="Bread, wheat", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS, 12))
    db.add(bread)
    db.flush()
    db.add(FoodNutrient(food_id=3, nutrient_key="calcium", amount_per_100g=200.0))
    db.commit()
    db.close()

    log_beef(client, token)
    client.post(f"/api/profiles/{profile_id}/conditions/gluten_intolerance", headers=auth_headers(token))

    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-20", headers=auth_headers(token))
    body = res.json()
    assert body is not None
    food_names = [f["food_name"] for f in body["foods"]]
    assert "Bread, wheat" not in food_names
    assert "Milk, whole" in food_names  # unrelated, unaffected
