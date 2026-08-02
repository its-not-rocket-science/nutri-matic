"""Tests for redis_rate_limit.py — operational-hardening prompt 2. Runs
against a real, disposable Redis (REDIS_URL), same skip-locally-but-
must-run-in-CI convention as tests/test_verify_pre_alembic_schema.py
uses for its own real-Postgres dependency — the whole point is
verifying real atomicity/expiry behaviour a fake/mocked client couldn't
meaningfully exercise."""

import os
import threading

import pytest

pytest.importorskip("redis")

import redis as redis_lib  # noqa: E402

from app.redis_rate_limit import (  # noqa: E402
    RateLimitStoreError,
    RedisSlidingWindowRateLimiter,
    hash_rate_limit_key,
)

REDIS_URL = os.environ.get("REDIS_URL")


def _redis_reachable() -> bool:
    if not REDIS_URL:
        return False
    try:
        client = redis_lib.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return True
    except Exception:
        return False


_HAS_REDIS = _redis_reachable()

if not _HAS_REDIS and os.environ.get("CI"):
    raise RuntimeError(
        "test_redis_rate_limit tests cannot run in CI: no Redis reachable via REDIS_URL — "
        "check the Redis service configuration in .github/workflows/ci.yml rather than "
        "letting these tests silently skip."
    )

pytestmark = pytest.mark.skipif(not _HAS_REDIS, reason="no Redis reachable via REDIS_URL for redis_rate_limit tests")


@pytest.fixture
def client():
    c = redis_lib.from_url(REDIS_URL)
    c.flushdb()
    yield c
    c.flushdb()
    c.close()


@pytest.fixture
def limiter(client):
    return RedisSlidingWindowRateLimiter(client)


def test_allows_up_to_the_limit_then_blocks(limiter):
    for _ in range(3):
        allowed, retry_after = limiter.hit("a", limit=3, window_seconds=3600)
        assert allowed is True
        assert retry_after == 0

    allowed, retry_after = limiter.hit("a", limit=3, window_seconds=3600)
    assert allowed is False
    assert retry_after > 0


def test_different_keys_have_independent_budgets(limiter):
    assert limiter.hit("a", limit=1, window_seconds=3600) == (True, 0)
    assert limiter.hit("a", limit=1, window_seconds=3600)[0] is False
    assert limiter.hit("b", limit=1, window_seconds=3600) == (True, 0)


def test_hits_age_out_of_the_window(limiter):
    """Deterministic via the `now` override (see hit()'s own docstring),
    not a real sleep."""
    assert limiter.hit("a", limit=1, window_seconds=60, now=1000.0) == (True, 0)
    assert limiter.hit("a", limit=1, window_seconds=60, now=1000.0)[0] is False
    assert limiter.hit("a", limit=1, window_seconds=60, now=1061.0) == (True, 0)  # past the window


def test_retry_after_reflects_when_the_oldest_hit_ages_out(limiter):
    limiter.hit("a", limit=1, window_seconds=60, now=1000.0)
    allowed, retry_after = limiter.hit("a", limit=1, window_seconds=60, now=1030.0)
    assert allowed is False
    assert retry_after == pytest.approx(31, abs=1)


def test_atomic_concurrent_hits_never_exceed_the_limit(limiter):
    """requirement 2/acceptance criteria: atomic concurrent requests
    cannot exceed the intended allowance — real threads hammering the
    same key through the same Lua-script-backed limiter, not a
    single-threaded simulation. Genuinely exercises the EVAL round trip
    being one atomic unit rather than a read-then-write race."""
    limit = 20
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        allowed, _ = limiter.hit("concurrent", limit=limit, window_seconds=3600)
        with lock:
            results.append(allowed)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == limit


def test_shared_across_two_simulated_app_instances(client):
    """requirement 1/acceptance criteria: limits are shared between at
    least two simulated app instances — two separate limiter objects
    (each its own Python-level "instance", same real Redis) enforcing
    one combined budget against the same key."""
    instance_a = RedisSlidingWindowRateLimiter(redis_lib.from_url(REDIS_URL))
    instance_b = RedisSlidingWindowRateLimiter(redis_lib.from_url(REDIS_URL))

    assert instance_a.hit("shared", limit=2, window_seconds=3600) == (True, 0)
    assert instance_b.hit("shared", limit=2, window_seconds=3600) == (True, 0)
    # the budget is exhausted from EITHER instance's perspective now —
    # neither has its own independent counter
    assert instance_a.hit("shared", limit=2, window_seconds=3600)[0] is False
    assert instance_b.hit("shared", limit=2, window_seconds=3600)[0] is False


def test_store_unreachable_raises_rate_limit_store_error():
    """requirement 7's documented bounded failure mode starts here — the
    caller (demo_protection.py) decides what to do with this exception;
    this module's own job is just to surface it rather than silently
    returning "allowed" or hanging."""
    unreachable = RedisSlidingWindowRateLimiter(
        redis_lib.from_url("redis://localhost:1/0", socket_connect_timeout=1, socket_timeout=1)
    )
    with pytest.raises(RateLimitStoreError):
        unreachable.hit("a", limit=1, window_seconds=3600)


def test_ping_raises_rate_limit_store_error_when_unreachable():
    unreachable = RedisSlidingWindowRateLimiter(
        redis_lib.from_url("redis://localhost:1/0", socket_connect_timeout=1, socket_timeout=1)
    )
    with pytest.raises(RateLimitStoreError):
        unreachable.ping()


def test_ping_succeeds_when_reachable(limiter):
    limiter.ping()  # no exception


def test_key_is_never_stored_raw_in_redis(client, limiter):
    """requirement 4: privacy-conscious keys — the caller is expected to
    hash before calling hit() (see hash_rate_limit_key/demo_protection.
    py), but this test confirms the raw value genuinely never appears as
    a Redis key name if the caller does that, closing the loop on the
    actual stored artefact, not just the function that computes it."""
    raw_ip = "203.0.113.42"
    hashed = hash_rate_limit_key(raw_ip)
    assert hashed != raw_ip
    limiter.hit(hashed, limit=5, window_seconds=3600)

    all_keys = [k.decode() if isinstance(k, bytes) else k for k in client.keys("*")]
    assert raw_ip not in all_keys
    assert hashed in all_keys


def test_hash_rate_limit_key_is_deterministic_and_keyed():
    assert hash_rate_limit_key("1.2.3.4") == hash_rate_limit_key("1.2.3.4")
    assert hash_rate_limit_key("1.2.3.4") != hash_rate_limit_key("1.2.3.5")
    assert hash_rate_limit_key("1.2.3.4") != "1.2.3.4"


def test_bucket_key_expires_rather_than_persisting_forever(client, limiter):
    """requirement 4's "documented retention/TTL" — the sorted set
    itself must carry a real Redis TTL, not live forever."""
    limiter.hit("ttl-check", limit=5, window_seconds=60)
    ttl = client.ttl("ttl-check")
    assert 0 < ttl <= 62
