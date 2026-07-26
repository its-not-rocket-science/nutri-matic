"""Abuse protection for `POST /api/auth/demo` (public-launch hardening
prompt 1) — the one endpoint on this API that creates a real, seeded
account for an unauthenticated caller, with no verification step at all.
Left unprotected, it's a trivial way to flood the users table and the
food-seeding queries behind it.

Two independent limits, both in-process sliding windows (see
app/rate_limit.py):

- Per-IP: stops a single scripted client from hammering the endpoint.
- Global: a circuit breaker capping total demo creation across every
  caller in the window, so a distributed/spoofed-IP flood still can't
  create unbounded accounts even if no single IP trips its own limit.

Both return the same generic 429 message regardless of which limit
tripped — there's nothing about which budget is exhausted that a caller
needs to know, and distinguishing them would just make it easier to
probe for the exact thresholds.
"""

import logging
import os

from fastapi import HTTPException, Request

from .rate_limit import SlidingWindowRateLimiter

_demo_logger = logging.getLogger("app.demo")

# Defaults are deliberately tight — this is a demo sandbox, not a feature
# real users are expected to hit often, or more than a handful of times
# an hour from one machine. Override via environment for a deployment
# that needs different values; see DEPLOYMENT.md.
DEMO_PER_IP_LIMIT = int(os.environ.get("DEMO_RATE_LIMIT_PER_IP", "5"))
DEMO_PER_IP_WINDOW_SECONDS = int(os.environ.get("DEMO_RATE_LIMIT_PER_IP_WINDOW_SECONDS", "3600"))
DEMO_GLOBAL_LIMIT = int(os.environ.get("DEMO_RATE_LIMIT_GLOBAL", "300"))
DEMO_GLOBAL_WINDOW_SECONDS = int(os.environ.get("DEMO_RATE_LIMIT_GLOBAL_WINDOW_SECONDS", "3600"))

_GLOBAL_KEY = "global"

_per_ip_limiter = SlidingWindowRateLimiter()
_global_limiter = SlidingWindowRateLimiter()

_RATE_LIMIT_DETAIL = "Too many demo accounts requested. Try again later."


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def enforce_demo_rate_limit(request: Request) -> None:
    """Raises HTTPException(429) if either limit is exceeded; otherwise
    records the hit against both windows and returns. Per-IP is checked
    first so an already-blocked IP never consumes global budget."""
    ip = _client_ip(request)

    ip_allowed, ip_retry_after = _per_ip_limiter.hit(ip, DEMO_PER_IP_LIMIT, DEMO_PER_IP_WINDOW_SECONDS)
    if not ip_allowed:
        _demo_logger.warning("demo_rate_limited", extra={"scope": "ip", "retry_after_seconds": ip_retry_after})
        raise HTTPException(
            status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": str(ip_retry_after)}
        )

    global_allowed, global_retry_after = _global_limiter.hit(
        _GLOBAL_KEY, DEMO_GLOBAL_LIMIT, DEMO_GLOBAL_WINDOW_SECONDS
    )
    if not global_allowed:
        _demo_logger.warning(
            "demo_rate_limited", extra={"scope": "global", "retry_after_seconds": global_retry_after}
        )
        raise HTTPException(
            status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": str(global_retry_after)}
        )


def reset_demo_rate_limits() -> None:
    """Test-only: clears both limiters' recorded state."""
    _per_ip_limiter.reset()
    _global_limiter.reset()
