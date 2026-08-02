"""Redis-backed sliding-window rate limiter — the shared/global
counterpart to `rate_limit.py`'s in-process `SlidingWindowRateLimiter`
(operational-hardening prompt 2).

WHY THIS EXISTS: `rate_limit.py`'s own docstring already documents its
limit honestly — correct for exactly one backend process, not a combined
budget across instances, and reset on every process restart (a redeploy
clears every counter — and this repo deploys often). This app's actual
current topology (`backend/Dockerfile`'s single `uvicorn` process,
`docker-compose.yml`'s single `backend` service, no reverse proxy or CDN
tracked in this repository) means "multiple instances" hasn't happened
yet, but "resets on every redeploy" is a REAL, CURRENT gap, not a
hypothetical future one — this app deploys routinely. A shared store
fixes both at once: genuinely combined across however many processes
ever run, and durable across any single process's restart.

WHY REDIS, NOT SOMETHING ELSE ALREADY IN THIS STACK: there is no
existing shared/edge service here to reuse — no cache, no session store,
no CDN/WAF config tracked in this repository. The only other shared
resource is Postgres itself, which this endpoint's whole point is to
protect from a flood — using the resource under protection to also do
the protecting, on the hot path of the exact endpoint most likely to be
attacked, is the wrong trade. Redis is the smallest dependable,
purpose-built tool for atomic-counter-with-expiry rate limiting, and is
what this prompt's own wording suggested as the reference design.

ATOMICITY: a single Lua script (`EVAL`), not separate read-then-write
round trips — Redis executes a script as one atomic unit, so two
concurrent requests hitting the same key can't both read a stale count
and both decide they're under the limit (the classic rate-limiter race).
Sliding-window-log via a sorted set (ZADD/ZREMRANGEBYSCORE/ZCARD),
deliberately the same algorithm `rate_limit.py`'s in-process limiter
already uses and this app's tests already exercise — matching semantics
between the fallback and the shared implementation, not introducing a
second, differently-shaped algorithm (e.g. a token bucket) at the same
time as making it distributed.

PRIVACY: the Redis key is never a raw IP — see `hash_rate_limit_key`.
The sorted set itself is bounded by Redis's own `EXPIRE`
(`window_seconds` + a small buffer), so a hashed-IP-keyed bucket is
never retained longer than the window it's protecting needs it for.

FAIL-CLOSED, NOT FAIL-OPEN, FOR THIS SPECIFIC ENDPOINT: if Redis is
unreachable, `RedisSlidingWindowRateLimiter.hit` raises
`RateLimitStoreError` rather than returning "allowed" — the caller
(`demo_protection.py`) turns that into a 503, not a silent bypass. This
endpoint creates a full real account with no verification at all; a
store outage silently becoming "unlimited account creation" is a worse
outcome than the endpoint being briefly unavailable. This is scoped
to THIS caller's decision, not a property of this module — a future
caller protecting a cheaper/lower-risk endpoint could reasonably choose
to fail open on the same exception instead."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time

_logger = logging.getLogger("app.rate_limit")

REDIS_URL = os.environ.get("REDIS_URL")

# Reuses JWT_SECRET as the HMAC key for hashing rate-limit keys (IPs)
# rather than requiring a second, separate secret to configure — a
# deliberate, documented shortcut: this hash has no security purpose
# JWT_SECRET's existing confidentiality doesn't already cover (it only
# needs to be non-invertible without the key, not cryptographically
# separated from an unrelated use of the same secret). Read lazily
# (inside hash_rate_limit_key, not at import time) so importing this
# module never depends on app.auth's own import-time JWT_SECRET
# resolution/validation order.
def _hash_key_secret() -> bytes:
    from .auth import JWT_SECRET
    return JWT_SECRET.encode("utf-8")


def hash_rate_limit_key(raw_key: str) -> str:
    """Keyed hash (HMAC-SHA256, truncated) of a raw limiter key (an IP
    address) — never store/transmit the raw value to Redis, where it
    would sit as a visible key name (via KEYS/SCAN/an RDB dump) for up
    to the window's TTL. A keyed hash, not a plain one, since a plain
    SHA256 of a small IPv4 address space is trivially reversible by
    brute force; truncated to 32 hex chars (128 bits) — still
    astronomically infeasible to reverse, no need for the full 64."""
    digest = hmac.new(_hash_key_secret(), raw_key.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:32]


class RateLimitStoreError(Exception):
    """Raised when the shared store (Redis) can't be reached or errors.
    Deliberately not an HTTPException itself — this module has no
    opinion on HTTP status codes; the caller decides the failure policy
    (see this module's own "FAIL-CLOSED" docstring section)."""


# Sliding-window-log, atomic via one EVAL round trip — see module
# docstring's "ATOMICITY" section. KEYS[1]=bucket key; ARGV: now (float
# seconds), window_seconds, limit, a client-generated unique member
# token (guards against two hits landing on the exact same float
# timestamp, however unlikely, colliding in the sorted set and being
# undercounted).
_LUA_SLIDING_WINDOW_HIT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_after = 1
  if oldest[2] then
    retry_after = math.max(1, math.floor(tonumber(oldest[2]) + window - now) + 1)
  end
  return {0, retry_after}
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window) + 1)
return {1, 0}
"""


class RedisSlidingWindowRateLimiter:
    """Same `hit(key, limit, window_seconds) -> (allowed, retry_after)`
    interface as `rate_limit.SlidingWindowRateLimiter` — a drop-in
    replacement for any existing caller, so switching between them (see
    `demo_protection.py`) never changes call-site code, only which
    instance gets constructed."""

    def __init__(self, client) -> None:
        self._client = client

    def hit(self, key: str, limit: int, window_seconds: float, *, now: float | None = None) -> tuple[bool, int]:
        """`now` defaults to the real clock; overridable for deterministic
        window-expiry tests (see test_redis_rate_limit.py), same
        testability seam rate_limit.SlidingWindowRateLimiter's own tests
        get via monkeypatching `time.monotonic` directly."""
        try:
            now = now if now is not None else time.time()
            member = f"{now:.6f}:{secrets.token_hex(4)}"
            allowed, retry_after = self._client.eval(
                _LUA_SLIDING_WINDOW_HIT, 1, key, now, window_seconds, limit, member,
            )
            return bool(allowed), int(retry_after)
        except Exception as exc:
            raise RateLimitStoreError(str(exc)) from exc

    def flush_all_test_only(self) -> None:
        """Test-only, same "Test-only:" convention as rate_limit.
        SlidingWindowRateLimiter.reset()/demo_protection.
        reset_demo_rate_limits() — a blanket FLUSHDB, safe here only
        because REDIS_URL in CI/local dev points at a dedicated,
        throwaway Redis service with nothing else stored in it. Never
        called from production code paths — see
        demo_protection.reset_demo_rate_limits, which calls this in
        addition to (not instead of) resetting the in-process fallback
        limiters, so the same test fixture keeps working regardless of
        which backend is actually active."""
        self._client.flushdb()

    def ping(self) -> None:
        """Raises RateLimitStoreError if the store isn't reachable —
        used by the readiness endpoint (see routers/health.py) and
        config-validation-at-startup, not by hit() itself."""
        try:
            self._client.ping()
        except Exception as exc:
            raise RateLimitStoreError(str(exc)) from exc


_client_singleton = None


def _build_client():
    import redis as redis_lib
    return redis_lib.from_url(
        REDIS_URL, decode_responses=False, socket_connect_timeout=2, socket_timeout=2,
    )


def get_redis_rate_limiter() -> RedisSlidingWindowRateLimiter | None:
    """None when REDIS_URL isn't configured — the caller decides what
    that means (local/test fallback to the in-process limiter, or a
    startup failure in production; see demo_protection.py and
    `validate_rate_limit_config`). Lazily constructs and reuses one
    client/connection pool per process, same convention as
    `database.py`'s module-level engine."""
    global _client_singleton
    if not REDIS_URL:
        return None
    if _client_singleton is None:
        _client_singleton = _build_client()
    return RedisSlidingWindowRateLimiter(_client_singleton)


def validate_rate_limit_config() -> None:
    """Operational-hardening prompt 2, requirement 10: production must
    not silently fall back to the process-local counter — call this at
    app startup (see main.py). Mirrors auth.py's `_resolve_jwt_secret`
    fail-fast-in-production pattern exactly: a lightweight local/test
    fallback (the in-process limiter) is fine when APP_ENV isn't
    "production", but production with no REDIS_URL configured refuses
    to start rather than quietly running with a per-process-only,
    reset-on-every-deploy limit protecting a real, unauthenticated,
    account-creating endpoint."""
    if REDIS_URL:
        return
    if os.environ.get("APP_ENV", "development") == "production":
        raise RuntimeError(
            "REDIS_URL is not set and APP_ENV=production — refusing to start with the "
            "process-local, reset-on-every-deploy rate limiter protecting POST /api/auth/demo. "
            "Set REDIS_URL. See DEPLOYMENT.md / docs/rate-limiting.md."
        )
