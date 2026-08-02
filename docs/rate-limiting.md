# Rate limiting

**Public-launch hardening prompt 1; made shared/durable by operational-
hardening prompt 2.** `POST /api/auth/demo` is the one endpoint on this
API that creates a real, seeded account for a completely unauthenticated
caller — no email verification, no CAPTCHA, nothing to stop a script
from calling it in a loop. Two independent limits protect it
(`backend/app/demo_protection.py`):

| Limit | Env var | Default | Purpose |
|---|---|---|---|
| Per-IP | `DEMO_RATE_LIMIT_PER_IP` | 5 per hour | Stops one scripted client from hammering the endpoint. |
| Per-IP window | `DEMO_RATE_LIMIT_PER_IP_WINDOW_SECONDS` | 3600 | — |
| Global | `DEMO_RATE_LIMIT_GLOBAL` | 300 per hour | Circuit breaker on total demo creation across every caller, so a distributed or spoofed-IP flood can't create unbounded accounts even if no single IP trips its own limit. |
| Global window | `DEMO_RATE_LIMIT_GLOBAL_WINDOW_SECONDS` | 3600 | — |

Both limits return the same generic `429` (`"Too many demo accounts
requested. Try again later."`) with a `Retry-After` header — the
response never reveals which of the two limits tripped, or its
threshold, so there's nothing to probe for. **Burst behaviour**: a
sliding-window log, not a fixed-window counter — a caller's budget is
however many hits fall in the trailing `window_seconds` at the moment of
the request, so there's no "reset boundary" a caller could time requests
around to get double the effective rate.

## Backend: Redis when configured, in-process fallback otherwise

`app/redis_rate_limit.py` (new, operational-hardening prompt 2) provides
a genuinely shared, durable, atomic limiter backed by Redis
(`REDIS_URL`) — `app/rate_limit.py`'s original in-process
`SlidingWindowRateLimiter` remains as the local/test fallback when
`REDIS_URL` isn't set. `demo_protection.py` picks whichever is
configured; both implement the identical `hit(key, limit,
window_seconds) -> (allowed, retry_after)` interface, so which one is
active never changes call-site code.

**Why Redis, not something else already in this stack**: there is no
existing shared/edge service to reuse here — no cache, session store, or
CDN/WAF configuration tracked in this repository. The only other shared
resource is Postgres itself, which this limiter's whole job is to
protect from a flood — using the protected resource to also do the
protecting, on the hot path of the endpoint most likely to be attacked,
is the wrong trade. Redis is the smallest dependable, purpose-built tool
for atomic-counter-with-expiry rate limiting.

**Atomicity**: one Lua script per `hit()` call (`EVAL`), not separate
read-then-write round trips — a sliding-window-log via a Redis sorted
set (`ZADD`/`ZREMRANGEBYSCORE`/`ZCARD`), the same algorithm the
in-process fallback already uses, so behaviour doesn't change shape
depending on which backend is active. Verified against a real Redis in
`backend/tests/test_redis_rate_limit.py::test_atomic_concurrent_hits_never_exceed_the_limit`
(100 real threads hammering one key) and
`::test_shared_across_two_simulated_app_instances` (two separate limiter
objects, same Redis, one combined budget).

**Privacy**: the Redis key is never a raw IP —
`redis_rate_limit.hash_rate_limit_key` (keyed HMAC-SHA256, truncated to
128 bits, reusing `JWT_SECRET` as the HMAC key rather than requiring a
second secret to configure) hashes it first. A plain hash of a small
IPv4 address space would be trivially reversible by brute force; a keyed
one isn't. **Retention**: each bucket's own Redis key carries an
`EXPIRE` of `window_seconds` + a small buffer — a hashed-IP-keyed bucket
is never retained longer than the window it's protecting needs it for.

**Trusted-proxy policy**: `_client_ip` in `demo_protection.py` uses the
raw socket peer (`request.client.host`) by default —
`TRUSTED_PROXY_HOP_COUNT` (default `0`, meaning "trust nothing") must be
explicitly set to a positive integer before `X-Forwarded-For` is ever
consulted at all, and even then only the specific entry that many hops
from the right is trusted (the value the nearest *trusted* proxy itself
appended) — never an arbitrary, earlier, client-suppliable entry. A
missing or too-short header falls back to the raw socket peer rather
than guessing. **This repository has no reverse-proxy/CDN configuration
tracked in it** — if the actual deployment puts one in front (nginx/
Caddy on the host, Cloudflare, etc.), an operator must set
`TRUSTED_PROXY_HOP_COUNT` to match how many hops it represents, or every
request will appear to originate from the proxy's own address, silently
collapsing the per-IP limit into a global-only one. See
`backend/tests/test_demo_protection.py` for the IPv4/IPv6/multi-hop/
malformed-header cases this is tested against.

**Fail-closed, not fail-open, for this specific endpoint**: if Redis is
configured but unreachable, `enforce_demo_rate_limit` returns `503`
(`"Demo accounts are temporarily unavailable. Try again shortly."`), not
a silent bypass. This endpoint creates a full real account with zero
verification — a store outage becoming "unlimited account creation" is
a worse outcome than the endpoint being briefly unavailable. This is a
choice `demo_protection.py` makes as the caller, not a property of
`redis_rate_limit.py` itself — a different, lower-risk endpoint could
reasonably choose to fail open on the same `RateLimitStoreError`
instead.

**Config validation**: `redis_rate_limit.validate_rate_limit_config()`
(called at app startup, `main.py`) refuses to start at all when
`APP_ENV=production` and `REDIS_URL` isn't set — the same fail-fast-at-
import pattern `auth.py`'s `_resolve_jwt_secret` already uses for
`JWT_SECRET`. A lightweight local/test fallback (the in-process limiter)
is fine outside production; production silently degrading to it is not.
`GET /api/ready` also checks live Redis reachability once `REDIS_URL` is
set (not otherwise — a dev/CI environment with no Redis at all is a
legitimate, explicitly-selected fallback, not something readiness should
fail for).

**Not yet extended to `invite_protection.py`** — the analogous
per-account/global limiter guarding outbound clinician-invite emails
uses the same in-process `SlidingWindowRateLimiter` and carries the same
documented single-process/reset-on-restart caveat, but that endpoint
requires authentication already (a materially different abuse profile:
a real, identified account, not an anonymous caller creating one from
nothing) and this prompt's explicit scope was the demo endpoint.
`redis_rate_limit.py` is written generically enough that wiring
`invite_protection.py` onto it later would be a small, natural follow-up
if the same durability/sharing properties are ever wanted there too.

## Observability

`app.demo` logger emits:

- `demo_rate_limited` (WARNING) — `extra={"scope": "ip"|"global", "retry_after_seconds": N}` — every time either limit trips.
- `demo_rate_limit_store_error` (ERROR) — `extra={"scope": "ip"|"global", "error": "..."}` — when the shared store (Redis) is configured but unreachable; distinct from `demo_rate_limited` so "real abuse" and "infrastructure problem" are never conflated in monitoring.
- `demo_created` (INFO) — on every successful demo account creation.
- `demo_creation_failed` (ERROR, with traceback) — if `create_demo_account` raises after passing the rate-limit check.

None of these ever include the raw client IP or account email — counts,
scopes, and error strings only. Checked directly, not just by
inspection, in `backend/tests/test_demo.py::test_demo_rate_limit_logs_never_include_the_raw_client_ip`.

## Atomicity of account creation itself

`create_demo_account` (`backend/app/demo_data.py`) does all of its work
— user row, profile, diary entries, recipe, meal plan entry, price,
weight logs — in one `Session`, with a single `db.commit()` at the end.
An exception partway through never reaches that commit; `get_db`'s
`finally: db.close()` rolls back whatever was pending, so a failure
leaves zero rows behind rather than a half-seeded account. Verified by
`test_demo_creation_failure_leaves_no_partial_account` in
`backend/tests/test_demo.py`, which forces a failure partway through
seeding and asserts the `users` table is empty afterward.

## What this prompt deliberately left out of scope

- **Request body size limiting**: `POST /api/auth/demo` takes no request
  body at all (no Pydantic model — just `request: Request, db`), so
  there's nothing to bound here specifically; ASGI/uvicorn's own default
  limits already apply at the transport layer regardless.
- **Preventing "concurrent duplicate creation"**: not applicable to this
  endpoint — every successful call is meant to create an independent new
  account (there's no idempotency key or duplicate concept for anonymous
  demo creation to guard against).
- **A separate "outstanding demo accounts" cap**: no such mechanism
  exists in this codebase today (checked, not assumed) — that would be a
  demo-account-*lifecycle* feature (alongside expiry/purge, see
  `docs/demo-lifecycle.md`), not a rate-limiting one, and is out of this
  prompt's scope.
- **Cost asymmetry** ("cheaper to reject than to fulfil"): already true
  by construction — the rate-limit check (one Redis `EVAL` round trip,
  or an in-process dict lookup) runs before any database write, and is
  trivially cheaper than `create_demo_account`'s multi-row seeded
  creation.
