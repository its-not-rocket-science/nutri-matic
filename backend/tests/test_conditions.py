"""Prompt 3.1: profile-level health/dietary conditions. Reuses
DietaryConstraint (and dietary_filter.py's existing exclusion logic)
exactly as-is — no new table, no new filtering codepath. A condition is
a curated, labelled shortcut onto that same mechanism."""

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
    db.add_all(
        [
            Food(id=1, name="Milk, whole", protein_g_per_100g=3.4, amino_acids=dict.fromkeys(AMINO_ACIDS, 15)),
            Food(id=2, name="Rice, white, cooked", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS, 10)),
            Food(id=3, name="Bread, wheat", protein_g_per_100g=9.0, amino_acids=dict.fromkeys(AMINO_ACIDS, 12)),
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


def owner_profile(client, token):
    profiles = client.get("/api/profiles", headers=auth_headers(token)).json()
    return next(p for p in profiles if p["is_account_owner"])


def test_dietary_vocabulary_includes_conditions(client):
    res = client.get("/api/profiles/dietary-vocabulary")
    assert res.status_code == 200
    conditions = {c["key"]: c for c in res.json()["conditions"]}
    assert conditions["lactose_intolerance"]["maps_to_tag"] == "milk"
    assert conditions["lactose_intolerance"]["default_severity"] == "avoid"
    assert conditions["gluten_intolerance"]["maps_to_tag"] == "wheat_gluten"
    assert conditions["gluten_intolerance"]["default_severity"] == "hard_exclude"
    assert conditions["type_2_diabetes"]["maps_to_tag"] is None
    assert conditions["type_2_diabetes"]["default_severity"] is None


def test_add_lactose_intolerance_creates_intolerance_constraint_on_milk_tag(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    res = client.post(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))
    assert res.status_code == 201
    body = res.json()
    assert body["category"] == "intolerance"
    assert body["tag"] == "milk"
    assert body["severity"] == "avoid"

    listed = client.get(f"/api/profiles/{owner['id']}/dietary-constraints", headers=auth_headers(token)).json()
    assert any(c["tag"] == "milk" and c["category"] == "intolerance" for c in listed)


def test_add_gluten_intolerance_defaults_to_hard_exclude(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    res = client.post(f"/api/profiles/{owner['id']}/conditions/gluten_intolerance", headers=auth_headers(token))
    assert res.status_code == 201
    assert res.json()["tag"] == "wheat_gluten"
    assert res.json()["severity"] == "hard_exclude"


def test_add_informational_condition_creates_medical_note_never_enforced(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    res = client.post(f"/api/profiles/{owner['id']}/conditions/type_2_diabetes", headers=auth_headers(token))
    assert res.status_code == 201
    body = res.json()
    assert body["category"] == "medical"
    assert body["tag"] is None
    assert body["severity"] is None
    assert body["note"] == "Type 2 diabetes"


def test_add_unknown_condition_key_returns_422(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    res = client.post(f"/api/profiles/{owner['id']}/conditions/gout", headers=auth_headers(token))
    assert res.status_code == 422


def test_add_condition_twice_returns_409(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    client.post(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))
    res = client.post(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))
    assert res.status_code == 409


def test_add_informational_condition_twice_returns_409(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    client.post(f"/api/profiles/{owner['id']}/conditions/type_2_diabetes", headers=auth_headers(token))
    res = client.post(f"/api/profiles/{owner['id']}/conditions/type_2_diabetes", headers=auth_headers(token))
    assert res.status_code == 409


def test_remove_condition_deletes_the_underlying_constraint(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    client.post(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))

    res = client.delete(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))
    assert res.status_code == 204

    listed = client.get(f"/api/profiles/{owner['id']}/dietary-constraints", headers=auth_headers(token)).json()
    assert listed == []


def test_remove_condition_never_set_is_a_no_op_not_an_error(client):
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    res = client.delete(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))
    assert res.status_code == 204


def test_condition_that_was_already_added_via_the_generic_constraint_form_is_detected_as_a_duplicate(client):
    """A user who separately added milk under category=intolerance via the
    plain allergy form (not through the conditions endpoint) still counts
    as having "lactose intolerance" set — the match is on category+tag,
    not on which endpoint created the row."""
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "intolerance", "tag": "milk", "severity": "avoid", "note": None},
        headers=auth_headers(token),
    )

    res = client.post(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))
    assert res.status_code == 409


def test_lactose_intolerance_flags_milk_as_avoid_in_food_search(client):
    """Confirms this isn't just a labelled row sitting inert — it flows
    through the SAME dietary_filter.py status logic an allergy tag does,
    with zero new filtering code. "avoid" (lactose intolerance's default
    severity — tolerance is commonly dose-dependent) flags rather than
    hides, unlike gluten intolerance's stricter "hard_exclude" below."""
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    client.post(f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(token))

    res = client.get("/api/foods/search-by-name?q=milk", headers=auth_headers(token))
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 1
    assert results[0]["dietary_status"]["status"] == "avoid"


def test_gluten_intolerance_hard_excludes_wheat_from_food_search(client):
    """Contrast with lactose intolerance above — "hard_exclude" actually
    removes the result, not just flags it."""
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)
    client.post(f"/api/profiles/{owner['id']}/conditions/gluten_intolerance", headers=auth_headers(token))

    res = client.get("/api/foods/search-by-name?q=bread", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json() == []

    unaffected = client.get("/api/foods/search-by-name?q=rice", headers=auth_headers(token))
    assert [f["name"] for f in unaffected.json()] == ["Rice, white, cooked"]


def test_conditions_scoped_to_owning_account(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    owner = owner_profile(client, token)

    res = client.post(
        f"/api/profiles/{owner['id']}/conditions/lactose_intolerance", headers=auth_headers(other_token)
    )
    assert res.status_code == 404


def test_two_informational_conditions_plus_a_free_text_medical_note_all_coexist(client):
    """PR review's exact reproduction: selecting two informational
    conditions (each creates a category=medical, tag=None row), then
    using the adjacent free-text medical-note form for something not in
    the curated list. Before the fix, the second condition already
    409'd against the first via create_dietary_constraint's stale
    category+tag dedup, and a third medical row (from either source)
    made that same dedup query raise MultipleResultsFound (500)."""
    token = register_and_token(client, "a@example.com")
    owner = owner_profile(client, token)

    res1 = client.post(f"/api/profiles/{owner['id']}/conditions/type_2_diabetes", headers=auth_headers(token))
    assert res1.status_code == 201
    res2 = client.post(f"/api/profiles/{owner['id']}/conditions/hypertension", headers=auth_headers(token))
    assert res2.status_code == 201

    res3 = client.post(
        f"/api/profiles/{owner['id']}/dietary-constraints",
        json={"category": "medical", "tag": None, "severity": None, "note": "Sleep apnoea"},
        headers=auth_headers(token),
    )
    assert res3.status_code == 201

    listed = client.get(f"/api/profiles/{owner['id']}/dietary-constraints", headers=auth_headers(token)).json()
    assert {c["note"] for c in listed} == {"Type 2 diabetes", "Hypertension / high blood pressure", "Sleep apnoea"}
