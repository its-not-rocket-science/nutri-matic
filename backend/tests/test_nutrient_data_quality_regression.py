"""Public-launch hardening prompt 3 regression suite.

Reproduces the exact reported production symptom (a diary day showing
"Biotin (B7) — 0% of target" when no food logged that day actually had
reliable biotin data) and the related plausibility-threshold gap (a
branded food at 991x the biotin DRV passing the old flat 1000x cutoff),
plus the surrounding cases prompt 3 explicitly asks to guard: a true
measured zero, a legitimately nutrient-dense whole food, and a
concentrated/branded outlier.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.demo_protection import reset_demo_rate_limits
from app.main import app
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS

TODAY = date.today().isoformat()


@pytest.fixture
def client():
    reset_demo_rate_limits()
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
    test_client = TestClient(app, raise_server_exceptions=False)
    test_client.db_engine = engine
    yield test_client
    app.dependency_overrides.clear()


def register_and_token(client, email="a@example.com", password="password123"):
    return client.post("/api/auth/register", json={"email": email, "password": password}).json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def seed_food(db, id_, name, **nutrients) -> Food:
    food = Food(id=id_, name=name, protein_g_per_100g=5.0, amino_acids=dict.fromkeys(AMINO_ACIDS, 5.0))
    db.add(food)
    db.flush()
    for key, amount in nutrients.items():
        db.add(FoodNutrient(food_id=id_, nutrient_key=key, amount_per_100g=amount))
    return food


def biotin_row(nutrients_out):
    return next(n for n in nutrients_out if n["key"] == "biotin")


def log_entry(client, token, food_id, quantity_g=100):
    res = client.post(
        "/api/diary",
        json={"entry_date": TODAY, "meal": "lunch", "food_id": food_id, "quantity_g": quantity_g},
        headers=auth_headers(token),
    )
    assert res.status_code == 201, res.text
    return res


def get_day(client, token):
    res = client.get(f"/api/diary?entry_date={TODAY}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return res.json()


def test_a_food_that_never_reports_biotin_does_not_read_as_0_percent(client):
    """The core reported bug: a nutrient only partially covered by the
    day's logged foods must never present as a confirmed 0% of target."""
    db = sessionmaker(bind=client.db_engine)()
    seed_food(db, 1, "Egg, whole, cooked", biotin=10.0)  # reports it
    seed_food(db, 2, "Yogurt, plain")  # never reports biotin at all
    db.commit()
    db.close()

    token = register_and_token(client)
    log_entry(client, token, 1, quantity_g=10)  # tiny mass share of the reporting food
    log_entry(client, token, 2, quantity_g=500)  # most of the day's mass has no biotin data

    row = biotin_row(get_day(client, token)["nutrients"])
    assert row["percent_drv"] is None
    assert row["insufficient_data_reason"] is not None
    assert row["coverage"] < 0.5


def test_the_live_demo_account_never_shows_biotin_as_0_percent(client):
    """The demo fixture itself (app/demo_data.py), end-to-end through the
    real API — the exact scenario the production bug was found in. Must
    become a permanent regression scenario: whatever the real ingested
    food catalog's actual biotin coverage turns out to be for these
    foods, it must never render as a confirmed 0%."""
    db = sessionmaker(bind=client.db_engine)()
    # A biotin-sparse subset, matching real USDA data's own sparse biotin
    # reporting for these food types — deliberately not seeding biotin at
    # all, the realistic case for a Foundation/SR Legacy ingest.
    seed_food(db, 1, "Chicken, broilers or fryers, breast, meat only, cooked, roasted")
    seed_food(db, 2, "Egg, whole, cooked, hard-boiled")
    seed_food(db, 3, "Rice, white, long-grain, regular, cooked")
    db.commit()
    db.close()

    token = client.post("/api/auth/demo").json()["access_token"]
    day = get_day(client, token)
    biotin_rows = [n for n in day["nutrients"] if n["key"] == "biotin"]
    for row in biotin_rows:
        assert row["percent_drv"] != 0 or row["insufficient_data_reason"] is not None, (
            "biotin must never show as a bare 0% of target"
        )


def test_a_true_fully_covered_zero_is_preserved_not_relabelled_insufficient(client):
    """Every food logged that day explicitly reports 0 for this nutrient
    — a genuine measured zero, not missing data. Must still show as a
    real 0%, not be hidden behind an insufficient-data label."""
    db = sessionmaker(bind=client.db_engine)()
    seed_food(db, 1, "Food A", biotin=0.0)
    seed_food(db, 2, "Food B", biotin=0.0)
    db.commit()
    db.close()

    token = register_and_token(client)
    log_entry(client, token, 1, quantity_g=200)
    log_entry(client, token, 2, quantity_g=200)

    row = biotin_row(get_day(client, token)["nutrients"])
    assert row["coverage"] == 1.0
    assert row["insufficient_data_reason"] is None
    assert row["percent_drv"] == 0.0


def test_high_coverage_partial_reporting_still_shows_a_real_percentage(client):
    """Most (not all) of the day's mass reports the nutrient — coverage
    above the 0.5 bar should still show a real percentage, not be
    suppressed just because coverage isn't perfect."""
    db = sessionmaker(bind=client.db_engine)()
    seed_food(db, 1, "Reports it", biotin=20.0)
    seed_food(db, 2, "Doesn't report it")
    db.commit()
    db.close()

    token = register_and_token(client)
    log_entry(client, token, 1, quantity_g=800)  # most of the day's mass
    log_entry(client, token, 2, quantity_g=100)

    row = biotin_row(get_day(client, token)["nutrients"])
    assert row["coverage"] >= 0.5
    assert row["insufficient_data_reason"] is None
    assert row["percent_drv"] is not None


def test_legitimately_nutrient_dense_whole_food_is_not_excluded(client):
    """Liver-level biotin (~100mcg/100g, ~3.3x the 30mcg DRV) is real and
    unremarkable — must count normally, not be excluded as implausible."""
    db = sessionmaker(bind=client.db_engine)()
    seed_food(db, 1, "Liver, beef, cooked", biotin=100.0)
    db.commit()
    db.close()

    token = register_and_token(client)
    log_entry(client, token, 1, quantity_g=100)

    row = biotin_row(get_day(client, token)["nutrients"])
    assert row["implausible_reason"] is None
    assert row["coverage"] == 1.0
    assert row["amount"] == pytest.approx(100.0)


def test_concentrated_branded_outlier_is_excluded_from_the_day_total(client):
    """The actual reported production value (29,733 mcg/100g biotin, 991x
    the DRV) — must be excluded from the day's total, not silently
    included because it slipped just under the old 1000x cutoff."""
    db = sessionmaker(bind=client.db_engine)()
    seed_food(db, 1, "Ordinary food", biotin=10.0)
    seed_food(db, 2, "Branded outlier", biotin=29733.0)
    db.commit()
    db.close()

    token = register_and_token(client)
    log_entry(client, token, 1, quantity_g=100)
    log_entry(client, token, 2, quantity_g=100)

    row = biotin_row(get_day(client, token)["nutrients"])
    # only the ordinary food's 10.0 contributes — the outlier is excluded
    assert row["amount"] == pytest.approx(10.0)
