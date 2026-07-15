import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.methodology import DRV_METHODOLOGY_VERSION, SCORING_METHODOLOGY_VERSION
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
    db.add(beef)
    db.flush()
    db.add(FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=2.0))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_snapshot_none_before_taken(client):
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json() is None


def test_create_snapshot_freezes_current_live_computation(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    live = client.get("/api/diary?entry_date=2026-07-13", headers=auth_headers(token)).json()

    res = client.post("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))
    assert res.status_code == 201
    body = res.json()
    assert body["entry_date"] == "2026-07-13"
    assert body["drv_methodology_version"] == DRV_METHODOLOGY_VERSION
    assert body["scoring_methodology_version"] == SCORING_METHODOLOGY_VERSION
    assert body["summary"] == live

    fetched = client.get("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))
    assert fetched.status_code == 200
    assert fetched.json()["summary"] == live


def test_create_snapshot_rejects_empty_day(client):
    token = register_and_token(client, "a@example.com")
    res = client.post("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))
    assert res.status_code == 422


def test_create_snapshot_is_immutable(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    first = client.post("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))
    assert first.status_code == 201

    # log more food after snapshotting — the snapshot must not change
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "dinner", "food_id": 1, "quantity_g": 200},
        headers=auth_headers(token),
    )
    second_attempt = client.post("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))
    assert second_attempt.status_code == 409

    snapshot = client.get("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token)).json()
    assert len(snapshot["summary"]["entries"]) == 1  # still just the original lunch entry

    live_now = client.get("/api/diary?entry_date=2026-07-13", headers=auth_headers(token)).json()
    assert len(live_now["entries"]) == 2  # live mode reflects both entries


def test_free_tier_snapshot_limit_enforced(client):
    token = register_and_token(client, "a@example.com")
    dates = [f"2026-07-{d:02d}" for d in range(1, 8)]
    for d in dates:
        client.post(
            "/api/diary", json={"entry_date": d, "meal": "lunch", "food_id": 1, "quantity_g": 100},
            headers=auth_headers(token),
        )

    for d in dates[:5]:
        res = client.post(f"/api/diary/snapshot?entry_date={d}", headers=auth_headers(token))
        assert res.status_code == 201

    # 6th snapshot for a free-plan user is rejected
    res = client.post(f"/api/diary/snapshot?entry_date={dates[5]}", headers=auth_headers(token))
    assert res.status_code == 403


def test_snapshot_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(token))

    res = client.get("/api/diary/snapshot?entry_date=2026-07-13", headers=auth_headers(other_token))
    assert res.json() is None
