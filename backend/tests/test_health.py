"""Tests for /api/health and /api/ready — operational-hardening prompt 5."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.routers import health as health_router


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
    app.dependency_overrides[health_router.get_database_url] = lambda: "sqlite:///:memory:"

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_liveness_returns_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readiness_succeeds_when_db_reachable_and_at_head(client, monkeypatch):
    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("abc123", "abc123"))
    res = client.get("/api/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}


def test_readiness_fails_when_db_unavailable(monkeypatch):
    def _broken_get_db():
        class _BrokenSession:
            def execute(self, *a, **kw):
                raise RuntimeError("connection refused")

        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_get_db
    app.dependency_overrides[health_router.get_database_url] = lambda: "sqlite:///:memory:"
    try:
        res = TestClient(app).get("/api/ready")
        assert res.status_code == 503
        assert "database unavailable" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_readiness_fails_when_migration_revision_is_behind_head(client, monkeypatch):
    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("old_revision", "new_revision"))
    res = client.get("/api/ready")
    assert res.status_code == 503
    assert "not at migration head" in res.json()["detail"]
    assert "old_revision" in res.json()["detail"]
    assert "new_revision" in res.json()["detail"]


def test_health_endpoints_do_not_leak_secrets(client, monkeypatch):
    """Neither endpoint's response body, in any outcome, contains a
    database URL's credentials or anything resembling a JWT secret."""
    secret_database_url = "postgresql://nutrimatic:supersecretpassword@internal-host:5432/nutrimatic"
    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("a", "b"))
    app.dependency_overrides[health_router.get_database_url] = lambda: secret_database_url

    ok_body = client.get("/api/health").text
    assert "supersecretpassword" not in ok_body

    ready_body = client.get("/api/ready").text
    assert "supersecretpassword" not in ready_body
    assert "internal-host" not in ready_body


def test_readiness_when_alembic_version_table_missing(client, monkeypatch):
    """A genuinely fresh/never-migrated database — current revision is
    None, not an exception. Must still report a clean 503, not a 500."""
    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: (None, "some_head"))
    res = client.get("/api/ready")
    assert res.status_code == 503


def test_readiness_logs_a_slow_db_check(client, monkeypatch, caplog):
    """Public-launch hardening prompt 6: database latency signal —
    threshold monkeypatched down to 0 so the test doesn't need a real
    slow database to trigger it."""
    import logging

    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("abc123", "abc123"))
    monkeypatch.setattr(health_router, "SLOW_READINESS_CHECK_THRESHOLD_MS", 0)

    with caplog.at_level(logging.WARNING, logger="app.health"):
        res = client.get("/api/ready")
    assert res.status_code == 200
    records = [r for r in caplog.records if r.message == "slow_readiness_db_check"]
    assert len(records) == 1
    assert hasattr(records[0], "duration_ms")


def test_readiness_does_not_log_when_db_check_is_fast(client, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("abc123", "abc123"))

    with caplog.at_level(logging.WARNING, logger="app.health"):
        res = client.get("/api/ready")
    assert res.status_code == 200
    assert [r for r in caplog.records if r.message == "slow_readiness_db_check"] == []
