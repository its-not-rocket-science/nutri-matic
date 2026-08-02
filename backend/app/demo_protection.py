"""Abuse protection for `POST /api/auth/demo` (public-launch hardening
prompt 1, made distributed/durable by operational-hardening prompt 2) —
the one endpoint on this API that creates a real, seeded account for an
unauthenticated caller, with no verification step at all. Left
unprotected, it's a trivial way to flood the users table and the
food-seeding queries behind it.

Two independent limits:

- Per-IP: stops a single scripted client from hammering the endpoint.
- Global: a circuit breaker capping total demo creation across every
  caller in the window, so a distributed/spoofed-IP flood still can't
  create unbounded accounts even if no single IP trips its own limit.

Both return the same generic 429 message regardless of which limit
tripped — there's nothing about which budget is exhausted that a caller
needs to know, and distinguishing them would just make it easier to
probe for the exact thresholds.

BACKEND SELECTION: `redis_rate_limit.get_redis_rate_limiter()` returns a
real, shared, durable limiter when `REDIS_URL` is configured; `None`
otherwise, in which case this falls back to `rate_limit.
SlidingWindowRateLimiter` — in-process, per-instance, reset on restart
(see that module's own docstring for the honest limits of the fallback).
`redis_rate_limit.validate_rate_limit_config()` (called at app startup,
see main.py) refuses to start with the fallback at all when
`APP_ENV=production` — see docs/rate-limiting.md."""

import logging
import os

from fastapi import HTTPException, Request

from .rate_limit import SlidingWindowRateLimiter
from .redis_rate_limit import RateLimitStoreError, get_redis_rate_limiter, hash_rate_limit_key

_demo_logger = logging.getLogger("app.demo")

# Defaults are deliberately tight — this is a demo sandbox, not a feature
# real users are expected to hit often, or more than a handful of times
# an hour from one machine. Override via environment for a deployment
# that needs different values; see DEPLOYMENT.md.
DEMO_PER_IP_LIMIT = int(os.environ.get("DEMO_RATE_LIMIT_PER_IP", "5"))
DEMO_PER_IP_WINDOW_SECONDS = int(os.environ.get("DEMO_RATE_LIMIT_PER_IP_WINDOW_SECONDS", "3600"))
DEMO_GLOBAL_LIMIT = int(os.environ.get("DEMO_RATE_LIMIT_GLOBAL", "300"))
DEMO_GLOBAL_WINDOW_SECONDS = int(os.environ.get("DEMO_RATE_LIMIT_GLOBAL_WINDOW_SECONDS", "3600"))

# How many reverse-proxy hops in front of this app are trusted to have
# set/overwritten X-Forwarded-For with the real client address, as their
# nearest hop's own observed peer — the standard "trust N proxy hops"
# policy (same idea Django's SECURE_PROXY_SSL_HEADER-adjacent settings
# and Express's `trust proxy` numeric mode use). Defaults to 0: trust
# NOTHING, use the raw socket peer address (`request.client.host`) —
# safe by default, immune to a spoofed header, but wrong if a real proxy
# sits in front and this is left unconfigured (every request then
# appears to come from the proxy's own address, collapsing the per-IP
# limit into a global-only one in practice). This repository has no
# reverse-proxy/CDN configuration tracked in it — if one exists in the
# actual deployment (nginx/Caddy on the host, Cloudflare, etc.), an
# operator must set this explicitly; see DEPLOYMENT.md.
TRUSTED_PROXY_HOP_COUNT = int(os.environ.get("TRUSTED_PROXY_HOP_COUNT", "0"))

_GLOBAL_KEY = "global"

_per_ip_limiter = SlidingWindowRateLimiter()
_global_limiter = SlidingWindowRateLimiter()

_RATE_LIMIT_DETAIL = "Too many demo accounts requested. Try again later."
_STORE_UNAVAILABLE_DETAIL = "Demo accounts are temporarily unavailable. Try again shortly."


def _client_ip(request: Request) -> str:
    """The raw socket peer by default (TRUSTED_PROXY_HOP_COUNT=0) — only
    consults X-Forwarded-For when explicitly configured to trust a
    specific number of proxy hops, and only trusts the specific hop that
    many entries from the right (the value the nearest *trusted* proxy
    itself appended/observed, never an arbitrary earlier entry a client
    could have supplied itself). Malformed/short headers (fewer entries
    than the configured hop count) fall back to the raw socket peer
    rather than guessing — same safe-default direction as trusting
    nothing at all."""
    if TRUSTED_PROXY_HOP_COUNT > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if len(hops) >= TRUSTED_PROXY_HOP_COUNT:
                return hops[-TRUSTED_PROXY_HOP_COUNT]
    return request.client.host if request.client is not None else "unknown"


def enforce_demo_rate_limit(request: Request) -> None:
    """Raises HTTPException(429) if either limit is exceeded, or 503 if
    the shared store (when configured) can't be reached — see module
    docstring's "BACKEND SELECTION" and redis_rate_limit.py's own
    "FAIL-CLOSED" section for why this endpoint specifically refuses
    rather than silently allowing unlimited creation during a store
    outage. Otherwise records the hit against both windows and returns.

    Per-IP is checked (and recorded) before global, so a single already-
    blocked IP repeatedly hammering the endpoint never keeps consuming
    shared global budget on every rejected request. On the Redis backend
    specifically, that ordering is preceded by a read-only `peek` at the
    global bucket (PR review): without it, a distributed/many-IP flood
    could create a fresh, persistent per-IP Redis key on every single
    request — even once global is already exhausted and every one of
    those requests is doomed to a 429 anyway — with no cardinality bound
    at all, unlike the in-process fallback's own DEFAULT_MAX_TRACKED_KEYS
    cap. Peeking first means no new per-IP state is ever created once
    the shared budget is already closed, while the *real* global
    increment still only happens after per-IP passes, preserving the
    original single-IP protection too."""
    redis_limiter = get_redis_rate_limiter()
    ip = _client_ip(request)
    ip_key = hash_rate_limit_key(ip) if redis_limiter is not None else ip
    global_key = hash_rate_limit_key(_GLOBAL_KEY) if redis_limiter is not None else _GLOBAL_KEY

    try:
        if redis_limiter is not None:
            if not redis_limiter.peek(global_key, DEMO_GLOBAL_LIMIT, DEMO_GLOBAL_WINDOW_SECONDS):
                _demo_logger.warning("demo_rate_limited", extra={"scope": "global", "retry_after_seconds": 1})
                raise HTTPException(
                    status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": "1"}
                )
            ip_allowed, ip_retry_after = redis_limiter.hit(ip_key, DEMO_PER_IP_LIMIT, DEMO_PER_IP_WINDOW_SECONDS)
        else:
            ip_allowed, ip_retry_after = _per_ip_limiter.hit(ip_key, DEMO_PER_IP_LIMIT, DEMO_PER_IP_WINDOW_SECONDS)
    except RateLimitStoreError as exc:
        _demo_logger.error("demo_rate_limit_store_error", extra={"scope": "ip", "error": str(exc)})
        raise HTTPException(status_code=503, detail=_STORE_UNAVAILABLE_DETAIL) from exc

    if not ip_allowed:
        _demo_logger.warning("demo_rate_limited", extra={"scope": "ip", "retry_after_seconds": ip_retry_after})
        raise HTTPException(
            status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": str(ip_retry_after)}
        )

    try:
        if redis_limiter is not None:
            global_allowed, global_retry_after = redis_limiter.hit(
                global_key, DEMO_GLOBAL_LIMIT, DEMO_GLOBAL_WINDOW_SECONDS
            )
        else:
            global_allowed, global_retry_after = _global_limiter.hit(
                global_key, DEMO_GLOBAL_LIMIT, DEMO_GLOBAL_WINDOW_SECONDS
            )
    except RateLimitStoreError as exc:
        _demo_logger.error("demo_rate_limit_store_error", extra={"scope": "global", "error": str(exc)})
        raise HTTPException(status_code=503, detail=_STORE_UNAVAILABLE_DETAIL) from exc

    if not global_allowed:
        _demo_logger.warning(
            "demo_rate_limited", extra={"scope": "global", "retry_after_seconds": global_retry_after}
        )
        raise HTTPException(
            status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": str(global_retry_after)}
        )


def reset_demo_rate_limits() -> None:
    """Test-only: clears the in-process fallback limiters' recorded
    state, AND flushes Redis when REDIS_URL is configured. Both, not one
    or the other — CI runs the whole backend suite with a real Redis
    service present (REDIS_URL set), which means every existing test
    that calls this (most of them via the `client` fixture in
    test_demo.py and friends) is actually exercising the Redis-backed
    path end to end, not just the fallback; without also flushing Redis
    here, those tests would keep sharing rate-limit state across the
    whole suite's run and eventually start failing with real 429s that
    have nothing to do with what each test is actually checking."""
    _per_ip_limiter.reset()
    _global_limiter.reset()
    redis_limiter = get_redis_rate_limiter()
    if redis_limiter is not None:
        redis_limiter.flush_all_test_only()
