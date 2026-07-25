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
        assert scrubbed["request"]["data"]["email"] == "a@example.com"  # not sensitive by this policy

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
