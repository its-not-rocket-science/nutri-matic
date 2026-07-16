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
            Food(
                id=1, name="Chicken, broilers or fryers, breast, meat only, cooked, roasted",
                protein_g_per_100g=31, amino_acids=dict.fromkeys(AMINO_ACIDS, 20), data_type="sr_legacy_food",
            ),
            Food(
                id=2, name="Rice, white, long-grain, regular, cooked", protein_g_per_100g=2.7,
                amino_acids=dict.fromkeys(AMINO_ACIDS, 5), data_type="sr_legacy_food",
            ),
            Food(
                id=3, name="Lentils, mature seeds, cooked, boiled, without salt", protein_g_per_100g=9,
                amino_acids=dict.fromkeys(AMINO_ACIDS, 10), data_type="sr_legacy_food",
            ),
        ]
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_demo_returns_a_usable_token(client):
    res = client.post("/api/auth/demo")
    assert res.status_code == 201
    token = res.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"].endswith("@demo.nutrimatic.local")


def test_demo_account_has_seeded_diary_entries(client):
    token = client.post("/api/auth/demo").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    from datetime import date

    res = client.get(f"/api/diary?entry_date={date.today().isoformat()}", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["entries"]) > 0


def test_demo_account_has_a_seeded_recipe(client):
    token = client.post("/api/auth/demo").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/recipes", headers=headers)
    assert res.status_code == 200
    assert any(r["name"] == "Chicken & rice bowl" for r in res.json())


def test_demo_account_has_a_profile_set(client):
    token = client.post("/api/auth/demo").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/profile", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sex"] == "female"
    assert body["weight_kg"] == 65.0


def test_two_demo_calls_create_two_independent_accounts(client):
    token_a = client.post("/api/auth/demo").json()["access_token"]
    token_b = client.post("/api/auth/demo").json()["access_token"]
    assert token_a != token_b

    email_a = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"}).json()["email"]
    email_b = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_b}"}).json()["email"]
    assert email_a != email_b


def test_demo_account_tolerates_missing_foods(client):
    """This fixture only seeds 3 of the 6 DEMO_FOOD_SEARCH_TERMS (chicken,
    rice, lentils — no egg/broccoli/yogurt), so this also exercises the
    no-match path for the other three terms. Should still succeed, not
    500, in an environment with a food-poor catalog (e.g. before any FDC
    ingest)."""
    res = client.post("/api/auth/demo")
    assert res.status_code == 201
