"""Tests for the /api/foods/{food_id}/phytate endpoint (prompts.txt
PROMPT 7 of the phytate/mineral-bioavailability extension) -- same
in-memory-SQLite + TestClient convention as test_foods.py."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import CompoundObservation, Food, User
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
    food = Food(id=1, name="Test food", protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS), fdc_id=111)
    food_no_data = Food(
        id=2, name="Food with no phytate data", protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS),
    )
    db.add_all([food, food_no_data])
    db.flush()
    db.add(CompoundObservation(
        compound="phytate", compound_fraction="PHYTCPPI", original_value=250.0, original_unit="mg",
        original_basis="per_100g_edible_portion", original_value_text="250.0", value_qualifier="measured",
        original_value_provenance="source_reported", source_food_description="Test food raw",
        source_preparation_state="raw", source_dataset_name="PhyFoodComp1.0",
        source_dataset_citation="FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0.",
        source_dataset_version="1.0", source_access_date=date(2026, 8, 21), analytical_method="indirect precipitation",
        source_row_identifier="1", match_relationship="close_analogue", match_confidence=0.8,
        matched_food_id=food.id,
    ))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register(client, email):
    res = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def _set_plan(email, plan):
    """Mutates the user's plan through the same overridden get_db session
    the app itself uses in this test, so the change is visible to the
    endpoint under test."""
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    user = db.query(User).filter(User.email == email).one()
    user.plan = plan
    db.commit()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---- basic shape ------------------------------------------------------

def test_404_for_unknown_food(client):
    res = client.get("/api/foods/999/phytate")
    assert res.status_code == 404


def test_selected_status_and_fields_for_food_with_data(client):
    res = client.get("/api/foods/1/phytate")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "selected"
    assert body["methodology_version"] == "phytate-selection-v1"
    assert len(body["observations"]) == 1
    obs = body["observations"][0]
    assert obs["compound_fraction"] == "PHYTCPPI"
    assert obs["value"] == 250.0
    assert obs["is_estimate"] is True  # close_analogue is never a source-verified identity match
    assert obs["source_dataset_citation"].startswith("FAO/INFOODS/IZiNCG")


def test_no_data_status_for_food_with_no_observations(client):
    res = client.get("/api/foods/2/phytate")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "no_data"
    assert body["observations"] == []


def test_preparation_query_param_is_passed_through(client):
    res = client.get("/api/foods/1/phytate?preparation=raw")
    assert res.json()["observations"][0]["preparation_compatible"] is True

    res = client.get("/api/foods/1/phytate?preparation=boiled")
    assert res.json()["observations"][0]["preparation_compatible"] is False


# ---- response-size cap (no bulk-reconstruction surface) -------------------

def test_observations_are_capped_at_max_observations_returned(client):
    from app.routers.phytate import MAX_OBSERVATIONS_RETURNED

    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    tags = ["PHYTCPPD", "PHYTCPP", "PHYTCA", "PHYTC-", "PPI", "PPD", "PP-", "IP3", "IP4", "IP5",
            "IP6", "IP5_A_IP6", "IP4_A_IP5_A_IP6", "IPSUM", "PHYT-", "PHYTCPPI2"]
    for i, tag in enumerate(tags):
        db.add(CompoundObservation(
            compound="phytate", compound_fraction=tag, original_value=float(i), original_unit="mg",
            original_basis="per_100g_edible_portion", original_value_text=str(float(i)), value_qualifier="measured",
            original_value_provenance="source_reported", source_food_description="Test food raw",
            source_dataset_name="PhyFoodComp1.0", source_dataset_citation="citation",
            source_dataset_version="1.0", source_access_date=date(2026, 8, 21),
            source_row_identifier=f"cap-{i}", match_relationship="close_analogue", match_confidence=0.8,
            matched_food_id=1,
        ))
    db.commit()

    res = client.get("/api/foods/1/phytate")
    body = res.json()
    assert len(body["observations"]) <= MAX_OBSERVATIONS_RETURNED
    if len(body["observations"]) == MAX_OBSERVATIONS_RETURNED:
        assert body["truncated"] is True


# ---- plan parity: identical response regardless of who's asking ---------

@pytest.mark.parametrize("plan", ["free", "trial", "paid", "professional", "enterprise"])
def test_response_is_identical_across_every_plan(client, plan):
    """Required by prompts.txt PROMPT 7: the personal phytate surface
    must respond identically to free, trial, paid, professional, and
    enterprise accounts -- this endpoint doesn't even read
    current_user/User.plan, so an authenticated call from every plan,
    and an entirely unauthenticated call, must all match byte-for-byte."""
    email = f"user-{plan}@example.com"
    token = register(client, email)
    _set_plan(email, plan)

    authenticated = client.get("/api/foods/1/phytate", headers=auth_headers(token))
    unauthenticated = client.get("/api/foods/1/phytate")

    assert authenticated.status_code == 200
    assert authenticated.json() == unauthenticated.json()


def test_all_plans_produce_the_same_response_as_each_other(client):
    responses = {}
    for plan in ("free", "trial", "paid", "professional", "enterprise"):
        email = f"parity-{plan}@example.com"
        token = register(client, email)
        _set_plan(email, plan)
        responses[plan] = client.get("/api/foods/1/phytate", headers=auth_headers(token)).json()

    values = list(responses.values())
    assert all(v == values[0] for v in values)
