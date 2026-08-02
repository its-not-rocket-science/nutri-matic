"""Tests for app/monitoring.py — operational-hardening prompt 5."""

import importlib

import pytest

from app import monitoring


@pytest.fixture(autouse=True)
def _reset_monitoring_state(monkeypatch):
    """Every test starts from a clean slate: no SENTRY_DSN, and the
    module's own `_initialized` flag reset. `sentry_sdk.init()` is a
    process-global side effect (a global client, not scoped to this
    module or this test) — left active, it would make every other test
    file's WARNING+ log calls (e.g. recommendation_safety.py's
    "recommendation_disabled") attempt a real network send to the fake
    DSN used below, slowing or flaking unrelated tests. Explicitly
    re-initialising with dsn=None after every test tears that global
    state back down."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monitoring._initialized = False
    yield
    monitoring._initialized = False
    import sentry_sdk

    sentry_sdk.init(dsn=None)


def test_init_monitoring_is_a_noop_without_sentry_dsn():
    """Missing monitoring credentials must never break local
    development — the whole point of gating on SENTRY_DSN."""
    result = monitoring.init_monitoring()
    assert result is False
    assert monitoring.is_initialized() is False


def test_init_monitoring_initialises_when_dsn_is_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://abc123@o0.ingest.sentry.io/123")
    result = monitoring.init_monitoring()
    assert result is True
    assert monitoring.is_initialized() is True


class TestValidateMonitoringConfig:
    """Operational-hardening prompt 4, requirement 1."""

    def test_logs_loud_error_when_production_and_no_dsn(self, monkeypatch, caplog):
        monkeypatch.setenv("APP_ENV", "production")
        monitoring.init_monitoring()  # no DSN — stays uninitialised
        with caplog.at_level("ERROR", logger="app.monitoring"):
            monitoring.validate_monitoring_config()
        assert any(r.message == "monitoring_not_configured" for r in caplog.records)

    def test_never_raises_even_in_production_with_no_dsn(self, monkeypatch):
        """Deliberately a warning, not the hard-fail-at-import pattern
        JWT_SECRET/REDIS_URL use — see validate_monitoring_config's own
        docstring for why missing observability shouldn't block startup
        the same way missing security/rate-limit config does."""
        monkeypatch.setenv("APP_ENV", "production")
        monitoring.init_monitoring()
        monitoring.validate_monitoring_config()  # must not raise

    def test_silent_when_monitoring_is_actually_initialised(self, monkeypatch, caplog):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SENTRY_DSN", "https://abc123@o0.ingest.sentry.io/123")
        monitoring.init_monitoring()
        with caplog.at_level("ERROR", logger="app.monitoring"):
            monitoring.validate_monitoring_config()
        assert not any(r.message == "monitoring_not_configured" for r in caplog.records)

    def test_silent_outside_production_with_no_dsn(self, monkeypatch, caplog):
        """development (the default) with no SENTRY_DSN is the normal,
        expected local/CI state — must never warn."""
        monitoring.init_monitoring()
        with caplog.at_level("ERROR", logger="app.monitoring"):
            monitoring.validate_monitoring_config()
        assert not any(r.message == "monitoring_not_configured" for r in caplog.records)

    def test_warns_via_pythons_own_last_resort_handler_with_no_configured_handler(self, monkeypatch, capsys):
        """The log call must actually be visible in container/CI stderr
        even though nothing in this app calls logging.basicConfig() or
        otherwise attaches a handler before this point — Python's own
        fallback (logging.lastResort) is what makes that true, checked
        here directly rather than assumed. Uses a real subprocess (not
        just the in-process caplog capture above) so pytest's own log
        capture handler — attached to the root logger for the rest of
        this test suite — can't mask whether a handler would genuinely
        be present in a real, undecorated run."""
        import os
        import subprocess
        import sys

        child_env = {**os.environ, "APP_ENV": "production"}
        child_env.pop("SENTRY_DSN", None)
        result = subprocess.run(
            [sys.executable, "-c", "from app import monitoring; monitoring.validate_monitoring_config()"],
            cwd=str(monitoring.BACKEND_DIR),
            env=child_env,
            capture_output=True, text=True,
        )
        assert "monitoring_not_configured" in result.stderr


def test_captures_uncaught_exceptions_via_the_auto_enabled_fastapi_integration(monkeypatch):
    """Public-launch hardening prompt 6's pre-flight check found that
    monitoring.py only ever explicitly wires LoggingIntegration — an
    actual unhandled 500 (as opposed to a logged WARNING/ERROR) was
    never *verified* to reach Sentry at all. sentry_sdk's own
    auto_enabling_integrations (on by default, not disabled here)
    detects installed starlette/fastapi and enables their integrations
    automatically — confirmed here by actually raising an uncaught
    exception through a live FastAPI app and checking it reaches
    before_send, not just by reading sentry_sdk's source."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    captured_events = []
    original_scrub = monitoring.scrub_event

    def spy_scrub(event, hint):
        captured_events.append(event)
        return original_scrub(event, hint)

    monkeypatch.setattr(monitoring, "scrub_event", spy_scrub)
    monkeypatch.setenv("SENTRY_DSN", "https://abc123@o0.ingest.sentry.io/123")
    monitoring.init_monitoring()

    test_app = FastAPI()

    @test_app.get("/boom")
    def boom():
        raise RuntimeError("kaboom-test-uncaught-exception")

    client = TestClient(test_app, raise_server_exceptions=False)
    res = client.get("/boom")

    assert res.status_code == 500
    assert captured_events, "no event reached before_send for an uncaught exception"
    exception_messages = [
        v.get("value", "")
        for event in captured_events
        for v in event.get("exception", {}).get("values", [])
    ]
    assert any("kaboom-test-uncaught-exception" in msg for msg in exception_messages)


def test_importing_the_app_does_not_require_sentry_dsn(monkeypatch):
    """The app must import and construct cleanly with no monitoring
    configuration at all — reload app.main fresh, with SENTRY_DSN
    deliberately absent, and confirm no exception."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    from app import main as main_module

    importlib.reload(main_module)
    assert main_module.app is not None


class TestScrubbing:
    def test_authorization_header_is_scrubbed(self):
        event = {"request": {"headers": {"Authorization": "Bearer real-token-value", "Accept": "application/json"}}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["request"]["headers"]["Authorization"] == "[Scrubbed]"
        assert scrubbed["request"]["headers"]["Accept"] == "application/json"  # non-sensitive headers untouched

    def test_cookies_are_scrubbed(self):
        event = {"request": {"cookies": {"session": "real-session-id"}}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["request"]["cookies"] == "[Scrubbed]"

    def test_password_and_token_fields_in_request_data_are_scrubbed(self):
        event = {"request": {"data": {"password": "hunter2", "access_token": "real-jwt", "email": "a@example.com"}}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["request"]["data"]["password"] == "[Scrubbed]"
        assert scrubbed["request"]["data"]["access_token"] == "[Scrubbed]"
        # Public-launch hardening prompt 6: emails are explicitly named
        # alongside tokens/passwords — superseding operational-hardening
        # prompt 5's original policy (which deliberately left email
        # unscrubbed, on the reasoning that it's this app's own
        # identifier rather than a secret). Redacted by pattern, not key
        # name, since "email" here isn't even the key it's under.
        assert scrubbed["request"]["data"]["email"] == "[redacted-email]"

    def test_email_is_redacted_by_pattern_regardless_of_which_key_it_is_under(self):
        event = {"request": {"data": {"message": "contact a@example.com for details"}}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["request"]["data"]["message"] == "contact [redacted-email] for details"

    def test_nested_dict_values_are_scrubbed_recursively(self):
        event = {"request": {"data": {"user": {"email": "nested@example.com", "id": 7}}}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["request"]["data"]["user"]["email"] == "[redacted-email]"
        assert scrubbed["request"]["data"]["user"]["id"] == 7

    def test_list_values_are_scrubbed(self):
        event = {"extra": {"emails": ["a@example.com", "b@example.com"]}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["extra"]["emails"] == ["[redacted-email]", "[redacted-email]"]

    def test_medical_and_dietary_note_fields_are_scrubbed(self):
        event = {"request": {"data": {"note": "renal diet, low potassium", "category": "medical"}}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["request"]["data"]["note"] == "[Scrubbed]"
        assert scrubbed["request"]["data"]["category"] == "medical"  # a category label, not free text

    def test_extra_context_is_scrubbed(self):
        event = {"extra": {"database_url": "postgresql://nutrimatic:supersecret@localhost/db", "profile_id": 7}}
        scrubbed = monitoring.scrub_event(event, {})
        assert "supersecret" not in scrubbed["extra"]["database_url"]
        assert scrubbed["extra"]["profile_id"] == 7

    def test_breadcrumb_data_is_scrubbed(self):
        event = {"breadcrumbs": {"values": [{"message": "x", "data": {"jwt": "real-token"}}]}}
        scrubbed = monitoring.scrub_event(event, {})
        assert scrubbed["breadcrumbs"]["values"][0]["data"]["jwt"] == "[Scrubbed]"
