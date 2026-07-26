# Rate limiting

**Public-launch hardening prompt 1.** `POST /api/auth/demo` is the one
endpoint on this API that creates a real, seeded account for a
completely unauthenticated caller — no email verification, no CAPTCHA,
nothing to stop a script from calling it in a loop. Two independent
in-process limits protect it (`backend/app/demo_protection.py`, built on
`backend/app/rate_limit.py`'s sliding-window counter):

| Limit | Env var | Default | Purpose |
|---|---|---|---|
| Per-IP | `DEMO_RATE_LIMIT_PER_IP` | 5 per hour | Stops one scripted client from hammering the endpoint. |
| Per-IP window | `DEMO_RATE_LIMIT_PER_IP_WINDOW_SECONDS` | 3600 | — |
| Global | `DEMO_RATE_LIMIT_GLOBAL` | 300 per hour | Circuit breaker on total demo creation across every caller, so a distributed or spoofed-IP flood can't create unbounded accounts even if no single IP trips its own limit. |
| Global window | `DEMO_RATE_LIMIT_GLOBAL_WINDOW_SECONDS` | 3600 | — |

Both limits return the same generic `429` (`"Too many demo accounts
requested. Try again later."`) with a `Retry-After` header — the
response never reveals which of the two limits tripped, or its
threshold, so there's nothing to probe for.

## Known limitation: single-process, in-memory

The limiter is a plain in-memory sliding window (`collections.deque` per
key, guarded by a `threading.Lock`) — there is no Redis or other shared
store in this repo yet. Total tracked keys are capped at
`DEFAULT_MAX_TRACKED_KEYS` (10,000, in `app/rate_limit.py`), evicting the
least-recently-used key once the cap is hit — this bounds memory even
against a flood of one-off keys (e.g. a distributed/spoofed-IP flood
that never repeats a source IP), which would otherwise grow the bucket
dict forever since a key is only pruned when it's hit again. Found by
an automated PR review during prompt 1, not anticipated up front — a
real gap, fixed before merge. This means:

- **Correct** for a single backend process/instance, which is this
  repo's actual current deployment shape (see `backend/Dockerfile` —
  one `uvicorn` process; `docker-compose.yml` — one backend container).
- **Not** a combined budget if the backend is ever scaled to multiple
  processes or instances behind a load balancer — each one enforces its
  own independent limit, so the *effective* global cap becomes
  `DEMO_RATE_LIMIT_GLOBAL × instance count`, not the configured value.
  Don't assume this document's numbers hold after such a change; add a
  shared store (Redis, or push the limit to an edge/infra layer —
  reverse proxy, CDN, WAF) instead of relying on this alone at that
  point.
- Resets on process restart — a redeploy clears every counter. Given
  the limits exist to blunt scripted abuse rather than provide hard
  guarantees, this is an accepted tradeoff, not a gap to fix.

## Observability

`app.demo` logger emits:

- `demo_rate_limited` (WARNING) — `extra={"scope": "ip"|"global", "retry_after_seconds": N}` — every time either limit trips.
- `demo_created` (INFO) — on every successful demo account creation.
- `demo_creation_failed` (ERROR, with traceback) — if `create_demo_account` raises after passing the rate-limit check.

## Atomicity

`create_demo_account` (`backend/app/demo_data.py`) does all of its work
— user row, profile, diary entries, recipe, meal plan entry, price,
weight logs — in one `Session`, with a single `db.commit()` at the end.
An exception partway through never reaches that commit; `get_db`'s
`finally: db.close()` rolls back whatever was pending, so a failure
leaves zero rows behind rather than a half-seeded account. This was
already true of the existing code before this prompt — verified (not
just assumed) by `test_demo_creation_failure_leaves_no_partial_account`
in `backend/tests/test_demo.py`, which forces a failure partway through
seeding and asserts the `users` table is empty afterward.
