from app import rate_limit as rate_limit_module
from app.rate_limit import SlidingWindowRateLimiter


def test_allows_up_to_the_limit_then_blocks():
    limiter = SlidingWindowRateLimiter()
    for _ in range(3):
        allowed, retry_after = limiter.hit("a", limit=3, window_seconds=3600)
        assert allowed is True
        assert retry_after == 0

    allowed, retry_after = limiter.hit("a", limit=3, window_seconds=3600)
    assert allowed is False
    assert retry_after > 0


def test_different_keys_have_independent_budgets():
    limiter = SlidingWindowRateLimiter()
    assert limiter.hit("a", limit=1, window_seconds=3600) == (True, 0)
    assert limiter.hit("a", limit=1, window_seconds=3600)[0] is False
    # A different key must not be affected by "a" having exhausted its budget.
    assert limiter.hit("b", limit=1, window_seconds=3600) == (True, 0)


def test_hits_age_out_of_the_window(monkeypatch):
    limiter = SlidingWindowRateLimiter()
    now = [1000.0]
    monkeypatch.setattr(rate_limit_module.time, "monotonic", lambda: now[0])

    assert limiter.hit("a", limit=1, window_seconds=60) == (True, 0)
    assert limiter.hit("a", limit=1, window_seconds=60)[0] is False

    now[0] += 61  # past the window
    assert limiter.hit("a", limit=1, window_seconds=60) == (True, 0)


def test_tracked_keys_are_bounded_to_prevent_unbounded_memory_growth():
    """A flood of one-off keys (e.g. spoofed/enumerated source IPs, each
    hit exactly once) must not grow the internal bucket dict forever —
    least-recently-used keys are evicted once the cap is hit."""
    limiter = SlidingWindowRateLimiter(max_tracked_keys=3)
    for i in range(1000):
        limiter.hit(f"key-{i}", limit=5, window_seconds=3600)
    assert len(limiter._buckets) <= 3


def test_eviction_is_least_recently_used():
    limiter = SlidingWindowRateLimiter(max_tracked_keys=2)
    limiter.hit("a", limit=5, window_seconds=3600)
    limiter.hit("b", limit=5, window_seconds=3600)
    limiter.hit("a", limit=5, window_seconds=3600)  # "a" is now most-recently-used
    limiter.hit("c", limit=5, window_seconds=3600)  # forces an eviction

    assert "b" not in limiter._buckets  # least-recently-used, evicted
    assert "a" in limiter._buckets
    assert "c" in limiter._buckets


def test_reset_clears_all_keys():
    limiter = SlidingWindowRateLimiter()
    limiter.hit("a", limit=1, window_seconds=3600)
    limiter.hit("b", limit=1, window_seconds=3600)
    limiter.reset()
    assert limiter.hit("a", limit=1, window_seconds=3600) == (True, 0)
    assert limiter.hit("b", limit=1, window_seconds=3600) == (True, 0)
