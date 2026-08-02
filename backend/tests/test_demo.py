import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.demo_protection import reset_demo_rate_limits
from app.main import app
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


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

    test_client = TestClient(app, raise_server_exceptions=False)
    test_client.db_engine = engine
    yield test_client
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

    res = client.get("/api/profiles", headers=headers)
    assert res.status_code == 200
    profiles = res.json()
    assert len(profiles) == 1
    assert profiles[0]["is_account_owner"] is True
    assert profiles[0]["sex"] == "female"
    assert profiles[0]["weight_kg"] == 65.0


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


def test_demo_rejects_requests_over_the_per_ip_limit(client, monkeypatch):
    import app.demo_protection as demo_protection

    monkeypatch.setattr(demo_protection, "DEMO_PER_IP_LIMIT", 3)

    for _ in range(3):
        assert client.post("/api/auth/demo").status_code == 201

    res = client.post("/api/auth/demo")
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    # Generic message — must not reveal which limit (per-IP vs. global)
    # tripped, or any count/threshold.
    assert "5" not in res.json()["detail"]
    assert "3" not in res.json()["detail"]


def test_demo_global_circuit_breaker_trips_before_per_ip_limit(client, monkeypatch):
    import app.demo_protection as demo_protection

    monkeypatch.setattr(demo_protection, "DEMO_PER_IP_LIMIT", 1000)
    monkeypatch.setattr(demo_protection, "DEMO_GLOBAL_LIMIT", 2)

    assert client.post("/api/auth/demo").status_code == 201
    assert client.post("/api/auth/demo").status_code == 201

    res = client.post("/api/auth/demo")
    assert res.status_code == 429


def test_demo_returns_503_not_a_silent_bypass_when_the_shared_store_errors(client, monkeypatch):
    """requirement 7: this endpoint fails CLOSED, not open, when the
    shared rate-limit store is configured but unreachable — a store
    outage must never become "unlimited account creation". Simulated by
    making get_redis_rate_limiter return a limiter whose hit() always
    raises, regardless of whether a real Redis is available to this test
    run — this is about demo_protection.py's own failure-handling code,
    not Redis itself (see test_redis_rate_limit.py for the real-Redis
    coverage)."""
    import app.demo_protection as demo_protection
    from app.redis_rate_limit import RateLimitStoreError

    class _AlwaysBrokenLimiter:
        def hit(self, key, limit, window_seconds):
            raise RateLimitStoreError("simulated store outage")

    monkeypatch.setattr(demo_protection, "get_redis_rate_limiter", lambda: _AlwaysBrokenLimiter())

    res = client.post("/api/auth/demo")
    assert res.status_code == 503
    assert res.json()["detail"] == "Demo accounts are temporarily unavailable. Try again shortly."


def test_demo_rate_limit_logs_never_include_the_raw_client_ip(client, monkeypatch, caplog):
    """requirement 4/9: telemetry is counts/scope only, never the raw
    client address — checked against the real log records emitted for
    both a rate-limit trip and a store error, not just inferred from
    reading the source."""
    import app.demo_protection as demo_protection
    from app.redis_rate_limit import RateLimitStoreError

    monkeypatch.setattr(demo_protection, "DEMO_PER_IP_LIMIT", 1)
    with caplog.at_level("WARNING", logger="app.demo"):
        assert client.post("/api/auth/demo").status_code == 201
        assert client.post("/api/auth/demo").status_code == 429
    assert any(r.message == "demo_rate_limited" for r in caplog.records)

    class _AlwaysBrokenLimiter:
        def hit(self, key, limit, window_seconds):
            raise RateLimitStoreError("simulated store outage")

    monkeypatch.setattr(demo_protection, "get_redis_rate_limiter", lambda: _AlwaysBrokenLimiter())
    with caplog.at_level("ERROR", logger="app.demo"):
        client.post("/api/auth/demo")
    assert any(r.message == "demo_rate_limit_store_error" for r in caplog.records)

    # TestClient's synthetic client host/any real IP shape — never in the
    # log text at all, for either event type
    assert "testclient" not in caplog.text
    for record in caplog.records:
        assert not hasattr(record, "ip")
        assert not hasattr(record, "client_ip")


def test_demo_creation_failure_leaves_no_partial_account(client, monkeypatch):
    """create_demo_account does all its work in one session, committed
    once at the end — an exception partway through must leave zero rows
    behind (get_db's session.close() rolls back an uncommitted
    transaction), not a half-seeded account."""
    import app.demo_data as demo_data
    from app.models import User

    real_create_owner_profile = demo_data.create_owner_profile

    def boom(db, user):
        real_create_owner_profile(db, user)
        raise RuntimeError("simulated failure after the user row is added")

    monkeypatch.setattr(demo_data, "create_owner_profile", boom)

    res = client.post("/api/auth/demo")
    assert res.status_code == 500

    db = sessionmaker(bind=client.db_engine)()
    assert db.query(User).count() == 0
    db.close()
