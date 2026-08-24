"""Tests for /api/health, /api/ready, and /api/ready/licence-policy-coverage
— operational-hardening prompt 5, plus PROMPT 13."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import CompoundObservation
from app.routers import health as health_router
from app.source_licence_policy import SURFACE_ENTERPRISE_BATCH, SURFACE_PERSONAL_FREE_UI


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

    test_client = TestClient(app)
    test_client.session_factory = TestSession  # lets tests seed rows on the same in-memory DB
    yield test_client
    app.dependency_overrides.clear()


def _observation(**overrides):
    defaults = dict(
        compound="phytate", original_value=100.0, original_unit="mg",
        original_basis="per_100g_edible_portion", original_value_text="100.0", value_qualifier="measured",
        original_value_provenance="source_reported", source_food_description="Test food",
        source_dataset_name="PhyFoodComp1.0", source_dataset_citation="citation",
        source_dataset_version="1.0", source_access_date=date(2026, 8, 21),
        match_relationship="needs_review", source_row_identifier="1",
    )
    defaults.update(overrides)
    return CompoundObservation(**defaults)


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


def test_readiness_checks_redis_only_when_configured(client, monkeypatch):
    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("a", "a"))
    monkeypatch.setattr(health_router, "REDIS_URL", None)
    res = client.get("/api/ready")
    assert res.status_code == 200  # no Redis configured — not checked, not a failure


def test_readiness_fails_when_redis_configured_but_unreachable(client, monkeypatch):
    from app.redis_rate_limit import RateLimitStoreError

    class _BrokenLimiter:
        def ping(self):
            raise RateLimitStoreError("Error 111 connecting to internal-redis-host:6379. Connection refused.")

    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("a", "a"))
    monkeypatch.setattr(health_router, "REDIS_URL", "redis://internal-redis-host:6379/0")
    monkeypatch.setattr(health_router, "get_redis_rate_limiter", lambda: _BrokenLimiter())

    res = client.get("/api/ready")
    assert res.status_code == 503


def test_readiness_does_not_leak_redis_connection_details_when_unreachable(client, monkeypatch):
    """PR review: redis-py connection errors commonly embed the internal
    host/port — this unauthenticated endpoint must never echo that back,
    same sanitised convention the database check already follows (type
    name only, full detail stays server-side in the log)."""
    from app.redis_rate_limit import RateLimitStoreError

    class _BrokenLimiter:
        def ping(self):
            raise RateLimitStoreError("Error 111 connecting to internal-redis-host:6379. Connection refused.")

    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("a", "a"))
    monkeypatch.setattr(health_router, "REDIS_URL", "redis://internal-redis-host:6379/0")
    monkeypatch.setattr(health_router, "get_redis_rate_limiter", lambda: _BrokenLimiter())

    body = client.get("/api/ready").text
    assert "internal-redis-host" not in body
    assert "6379" not in body
    assert "Connection refused" not in body


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
    # ERROR, not WARNING: LoggingIntegration's event_level=ERROR is what
    # actually turns this into a Sentry event rather than a breadcrumb.
    assert records[0].levelno == logging.ERROR


def test_readiness_does_not_log_when_db_check_is_fast(client, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(health_router, "alembic_head_and_current", lambda url: ("abc123", "abc123"))

    with caplog.at_level(logging.WARNING, logger="app.health"):
        res = client.get("/api/ready")
    assert res.status_code == 200
    assert [r for r in caplog.records if r.message == "slow_readiness_db_check"] == []


# ---- /api/ready/licence-policy-coverage (PROMPT 13) ------------------------

_OPS_TOKEN = "test-ops-diagnostic-token"


def _authed_get(client, monkeypatch, path):
    monkeypatch.setenv(health_router.OPS_DIAGNOSTIC_TOKEN_ENV_VAR, _OPS_TOKEN)
    return client.get(path, headers={"X-Ops-Diagnostic-Token": _OPS_TOKEN})


def test_licence_coverage_healthy_for_registered_phyfoodcomp_data_on_permitted_profile(client, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_PERSONAL_FREE_UI)
    db = client.session_factory()
    db.add(_observation())
    db.commit()
    db.close()

    res = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}


def test_licence_coverage_unhealthy_for_unknown_compound(client, monkeypatch):
    db = client.session_factory()
    db.add(_observation(compound="totally_unregistered_compound"))
    db.commit()
    db.close()

    res = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")
    assert res.status_code == 503
    assert "totally_unregistered_compound" in res.json()["detail"]


def test_licence_coverage_unhealthy_for_known_compound_unknown_source_dataset_name(client, monkeypatch):
    db = client.session_factory()
    db.add(_observation(source_dataset_name="SomeOtherPhytateDataset"))
    db.commit()
    db.close()

    res = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")
    assert res.status_code == 503
    assert "SomeOtherPhytateDataset" in res.json()["detail"]


def test_licence_coverage_evaluates_second_source_for_same_compound_separately(client, monkeypatch):
    db = client.session_factory()
    db.add(_observation(source_row_identifier="1"))  # registered
    db.add(_observation(source_row_identifier="2", source_dataset_name="SecondPhytateSource"))
    db.commit()
    db.close()

    res = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")
    assert res.status_code == 503
    assert "SecondPhytateSource" in res.json()["detail"]
    assert "PhyFoodComp1.0" not in res.json()["detail"]  # the registered pair is not itself a problem


def test_licence_coverage_unhealthy_when_deployment_profile_exposes_prohibited_surface(client, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PERMITTED_SURFACES", SURFACE_ENTERPRISE_BATCH)
    db = client.session_factory()
    db.add(_observation())
    db.commit()
    db.close()

    res = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")
    assert res.status_code == 503
    assert SURFACE_ENTERPRISE_BATCH in res.json()["detail"]


def test_licence_coverage_unhealthy_when_a_registered_source_key_has_no_policy(client, monkeypatch):
    """Bot-review P2 on PR #61: a COMPOUND_SOURCE_KEYS entry pointing at
    an unregistered source_key must be reported as a coverage problem,
    not misreported as "database unavailable" by the endpoint's blanket
    exception handler."""
    import app.source_licence_policy as policy_module

    monkeypatch.setitem(policy_module.COMPOUND_SOURCE_KEYS, ("phytate", "PhyFoodComp1.0"), "orphaned_source_key")
    db = client.session_factory()
    db.add(_observation())
    db.commit()
    db.close()

    res = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")
    assert res.status_code == 503
    assert "orphaned_source_key" in res.json()["detail"]
    assert "database unavailable" not in res.json()["detail"]


def test_licence_coverage_fails_readiness_not_import_when_db_unavailable(monkeypatch):
    def _broken_get_db():
        class _BrokenSession:
            def query(self, *a, **kw):
                raise RuntimeError("connection refused")

        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_get_db
    monkeypatch.setenv(health_router.OPS_DIAGNOSTIC_TOKEN_ENV_VAR, _OPS_TOKEN)
    try:
        res = TestClient(app).get(
            "/api/ready/licence-policy-coverage", headers={"X-Ops-Diagnostic-Token": _OPS_TOKEN},
        )
        assert res.status_code == 503
        assert "database unavailable" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---- require_ops_diagnostic_token: the P1 fix on PR #61 --------------------

def test_licence_coverage_requires_auth_when_token_unset(client, monkeypatch):
    monkeypatch.delenv(health_router.OPS_DIAGNOSTIC_TOKEN_ENV_VAR, raising=False)
    res = client.get("/api/ready/licence-policy-coverage", headers={"X-Ops-Diagnostic-Token": "anything"})
    assert res.status_code == 401


def test_licence_coverage_requires_auth_when_no_header_supplied(client, monkeypatch):
    monkeypatch.setenv(health_router.OPS_DIAGNOSTIC_TOKEN_ENV_VAR, _OPS_TOKEN)
    res = client.get("/api/ready/licence-policy-coverage")
    assert res.status_code == 401


def test_licence_coverage_requires_auth_when_wrong_token_supplied(client, monkeypatch):
    monkeypatch.setenv(health_router.OPS_DIAGNOSTIC_TOKEN_ENV_VAR, _OPS_TOKEN)
    res = client.get("/api/ready/licence-policy-coverage", headers={"X-Ops-Diagnostic-Token": "wrong-token"})
    assert res.status_code == 401


def test_licence_coverage_wrong_token_never_touches_the_database(client, monkeypatch):
    """The auth dependency must reject before the (potentially expensive,
    growing) DISTINCT query ever runs -- not just before the response is
    returned."""
    monkeypatch.setenv(health_router.OPS_DIAGNOSTIC_TOKEN_ENV_VAR, _OPS_TOKEN)

    def _query_that_must_not_be_called(*a, **kw):
        raise AssertionError("DB was queried despite failed auth")

    db = client.session_factory()
    monkeypatch.setattr(db, "query", _query_that_must_not_be_called)

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        res = client.get("/api/ready/licence-policy-coverage", headers={"X-Ops-Diagnostic-Token": "wrong-token"})
        assert res.status_code == 401
    finally:
        db.close()


def test_licence_coverage_logs_a_structured_warning_on_unhealthy(client, monkeypatch, caplog):
    import logging

    db = client.session_factory()
    db.add(_observation(compound="totally_unregistered_compound"))
    db.commit()
    db.close()

    with caplog.at_level(logging.WARNING, logger="app.health"):
        _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage")

    records = [r for r in caplog.records if r.message == "licence_policy_coverage_unhealthy"]
    assert len(records) == 1
    assert records[0].problem_count == 1


def test_licence_coverage_does_not_leak_secrets(client, monkeypatch):
    secret_database_url = "postgresql://nutrimatic:supersecretpassword@internal-host:5432/nutrimatic"
    app.dependency_overrides[health_router.get_database_url] = lambda: secret_database_url
    db = client.session_factory()
    db.add(_observation(compound="totally_unregistered_compound"))
    db.commit()
    db.close()

    body = _authed_get(client, monkeypatch, "/api/ready/licence-policy-coverage").text
    assert "supersecretpassword" not in body
    assert "internal-host" not in body
