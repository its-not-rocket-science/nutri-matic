from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import demo_lifecycle
from app.database import Base, get_db
from app.demo_lifecycle import demo_expiry_from, is_expired_demo
from app.demo_protection import reset_demo_rate_limits
from app.main import app
from app.models import User


def make_user(**overrides) -> User:
    defaults = dict(email="u@example.com", password_hash="x", is_demo=False, expires_at=None)
    defaults.update(overrides)
    return User(**defaults)


def test_demo_expiry_is_created_at_plus_configured_lifetime(monkeypatch):
    monkeypatch.setattr(demo_lifecycle, "DEMO_LIFETIME_HOURS", 24.0)
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert demo_expiry_from(created_at) == created_at + timedelta(hours=24)


def test_non_demo_user_never_expires_regardless_of_expires_at():
    user = make_user(is_demo=False, expires_at=datetime.now(timezone.utc) - timedelta(days=999))
    assert is_expired_demo(user) is False


def test_demo_user_with_no_expiry_set_is_not_expired():
    user = make_user(is_demo=True, expires_at=None)
    assert is_expired_demo(user) is False


def test_active_demo_user_is_not_expired():
    user = make_user(is_demo=True, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert is_expired_demo(user) is False


def test_expired_demo_user_is_expired():
    user = make_user(is_demo=True, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert is_expired_demo(user) is True


def test_expiry_boundary_is_inclusive():
    now = datetime.now(timezone.utc)
    user = make_user(is_demo=True, expires_at=now)
    assert is_expired_demo(user, now=now) is True


def test_handles_a_naive_expires_at_as_utc():
    """SQLite (this test suite's usual engine) doesn't actually preserve
    tzinfo through a round trip even for a DateTime(timezone=True)
    column — a value read back after a commit/reload can come back
    naive. Every expires_at this app ever writes is UTC (demo_expiry_from
    only ever operates on aware UTC datetimes), so naive must be treated
    as UTC here, not raise or silently miscompare."""
    naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    user = make_user(is_demo=True, expires_at=naive_past)
    assert is_expired_demo(user) is True


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


def test_new_demo_account_is_marked_demo_with_an_expiry_in_the_future(client):
    res = client.post("/api/auth/demo")
    assert res.status_code == 201
    token = res.json()["access_token"]

    db = sessionmaker(bind=client.db_engine)()
    user = db.query(User).one()
    assert user.is_demo is True
    assert user.expires_at is not None
    assert user.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    db.close()

    # and it's usable right away
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_expired_demo_account_cannot_authenticate(client):
    token = client.post("/api/auth/demo").json()["access_token"]

    db = sessionmaker(bind=client.db_engine)()
    user = db.query(User).filter(User.is_demo.is_(True)).one()
    user.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    # same generic message any other invalid/expired token gets — no
    # distinguishing detail that would confirm "this was specifically a
    # demo account" to the caller.
    assert res.json()["detail"] == "Invalid or expired token"


def test_expired_demo_treated_as_anonymous_on_optional_auth_endpoints(client):
    """/api/foods/search-by-name accepts an optional bearer token (dietary
    constraints apply if logged in) — an expired demo here must behave
    like any other expired token: silently anonymous, not a 401."""
    token = client.post("/api/auth/demo").json()["access_token"]

    db = sessionmaker(bind=client.db_engine)()
    user = db.query(User).filter(User.is_demo.is_(True)).one()
    user.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()

    res = client.get("/api/foods/search-by-name?q=chicken", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_ordinary_registered_user_is_never_marked_demo_or_given_an_expiry(client):
    res = client.post("/api/auth/register", json={"email": "real@example.com", "password": "password123"})
    token = res.json()["access_token"]

    db = sessionmaker(bind=client.db_engine)()
    user = db.query(User).filter(User.email == "real@example.com").one()
    assert user.is_demo is False
    assert user.expires_at is None
    db.close()

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
