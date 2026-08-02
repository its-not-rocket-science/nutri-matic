"""Tests for redis_rate_limit.py's config-validation/wiring logic —
operational-hardening prompt 2, requirement 10. Pure config/plumbing
tests, no real Redis connection needed (unlike test_redis_rate_limit.py,
which exercises the real atomic-limiter behaviour) — get_redis_rate_
limiter() constructs a client lazily and never connects until hit()/
ping() is actually called."""

import pytest

import app.redis_rate_limit as redis_rate_limit_module
from app.redis_rate_limit import (
    RedisSlidingWindowRateLimiter,
    get_redis_rate_limiter,
    hash_rate_limit_key,
    validate_rate_limit_config,
)


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """The module caches one client per process (see get_redis_rate_
    limiter's own docstring) — must not leak between tests that flip
    REDIS_URL on and off."""
    monkeypatch.setattr(redis_rate_limit_module, "_client_singleton", None)
    yield
    monkeypatch.setattr(redis_rate_limit_module, "_client_singleton", None)


def test_get_redis_rate_limiter_returns_none_without_redis_url(monkeypatch):
    monkeypatch.setattr(redis_rate_limit_module, "REDIS_URL", None)
    assert get_redis_rate_limiter() is None


def test_get_redis_rate_limiter_returns_a_limiter_when_configured(monkeypatch):
    monkeypatch.setattr(redis_rate_limit_module, "REDIS_URL", "redis://localhost:6379/0")
    limiter = get_redis_rate_limiter()
    assert isinstance(limiter, RedisSlidingWindowRateLimiter)


def test_validate_rate_limit_config_passes_when_redis_url_set(monkeypatch):
    monkeypatch.setattr(redis_rate_limit_module, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("APP_ENV", "production")
    validate_rate_limit_config()  # no exception


def test_validate_rate_limit_config_raises_when_production_and_no_redis_url(monkeypatch):
    monkeypatch.setattr(redis_rate_limit_module, "REDIS_URL", None)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        validate_rate_limit_config()


def test_validate_rate_limit_config_allows_missing_redis_url_outside_production(monkeypatch):
    monkeypatch.setattr(redis_rate_limit_module, "REDIS_URL", None)
    monkeypatch.setenv("APP_ENV", "development")
    validate_rate_limit_config()  # no exception — the local/test fallback is fine here


def test_hash_rate_limit_key_never_returns_the_raw_input():
    for raw in ("203.0.113.42", "::1", "global", ""):
        assert hash_rate_limit_key(raw) != raw
