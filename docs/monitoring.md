# Monitoring and alerting

## No error-tracking service (2026-11-15)

This app uses no third-party error tracker. Sentry was integrated on
both halves earlier but never provisioned (no DSN existed anywhere), and
was removed on 2026-11-15: `sentry-sdk` from the backend,
`@sentry/sveltekit` (and its source-map Vite plugin) from the frontend,
the Sentry ingest origin from the CSP, the release-annotation step from
`deploy.yml`, and the `SENTRY_*`/`PUBLIC_SENTRY_*`/`RELEASE_VERSION`/
`PUBLIC_RELEASE_VERSION` variables. Earlier records of that work remain
in `docs/operational-hardening.md` as history.

What remains is what this repository can do on its own:

- **Structured logs** from the backend (stdlib `logging`, read from the
  container logs on the server). The signals below log at `ERROR` so
  they stand out from routine output.
- **Health and readiness endpoints**: `/api/health`, `/api/ready`.
- **Uptime check**: `.github/workflows/uptime-check.yml` runs
  `app/smoke_check.py` against production every 15 minutes. A failing
  run is a red X on the workflow (plus email, depending on each
  watcher's GitHub notification settings).
- **Post-deploy smoke test** in `deploy.yml`.

Migration failures can't self-report: `Dockerfile`'s `CMD` is
`alembic upgrade head && uvicorn ...`, so if the migration fails the app
never starts. That has to be caught at the container level (exit code,
restart loop), not by this app's code.

## Log signals

- **`elevated_status_response`** (`app/main.py`) — an app-wide
  middleware logging for any 5xx response, on any route (the existing
  recommendation-specific middleware only ever covered `/api/
  recommendations/*`). Deliberately silent on success — logging every
  request at real traffic volume would be pure noise.
- **`recommendation_request`** (`app/main.py`) tags `mode` (ingredients/recipes/
  pairs/substitutions, parsed from the path) and escalates severity
  when the response is a 5xx, instead of always logging at `INFO`.
- **`auth_login_failed`** (`app/routers/auth.py`) — a reason code only
  (`invalid_credentials`), never the attempted email or password.
  Aggregate signal for brute-force/credential-stuffing detection.
  Deliberately *not* added to `get_current_user`'s per-request
  invalid/expired-token check — that fires on every ordinary token
  expiry (a normal, frequent, non-abusive event for any real user), and
  logging it would be noise, not signal.
- **`data_quality_flagged_in_aggregation`** (`app/aggregation.py`) —
  once per `aggregate_nutrients()` call that actually excludes an
  implausible row (never once per row — this function runs in hot
  paths, especially `recommend_ingredients.py`'s per-candidate trial
  loop, so per-row logging would flood). Silent when nothing's
  flagged, which should be the common case given the curated/
  non-branded candidate pool already in place.
- **`slow_readiness_db_check`** (`app/routers/health.py`) — `/api/ready`
  now times its own `SELECT 1` and logs if it takes ≥500ms
  (`SLOW_READINESS_CHECK_THRESHOLD_MS`), the closest signal this app can
  cheaply get for "database connection exhaustion/latency" without
  adding new scraping infrastructure — an orchestrator already polls
  `/api/ready` regularly, giving this a natural sampling cadence.

## Post-validation fixes (2026-08-03)

Prompt 5's final validation (see the published validation report)
found two live, confirmed gaps — both now closed:

- **Demo-purge SSH allowlist** — `/root/deploy-allowed-commands.sh`
  never had the `demo_purge` case branches added, so every invocation
  (scheduled or manual) was rejected at the SSH layer since the
  Prompt-1 rewrite. Added; verified with a reviewed manual dry-run (14
  expired accounts found, all matching the expected demo-account
  pattern) followed by a reviewed manual `--apply` run (14 accounts /
  211 dependent rows purged in 0.38s), then a follow-up dry-run
  confirming zero remaining backlog. The nightly schedule now runs for
  real.
- **`TRUSTED_PROXY_HOP_COUNT`** — wired through `docker-compose.yml`
  and set to `1` on the production server (Caddy is confirmed, via its
  own `Via` response header, to be the one proxy hop in front of the
  app). Per-IP demo-creation limiting was silently collapsing into a
  second global-only limit before this; real per-visitor limiting is
  now in effect.

## Post-deploy smoke check — `app/smoke_check.py`

```
python -m app.smoke_check --backend-url https://api.nutri-matic.uk --frontend-url https://nutri-matic.uk
```

Checks backend `/api/health`/`/api/ready`, the frontend's home/`/about`/
`/methodology` pages, and `robots.txt`/`sitemap.xml`/
`manifest.webmanifest` (content-checked, not just status-checked — e.g.
`robots.txt` must actually contain a `Sitemap:` line). Read-only by
default.

`--include-demo-flow` additionally creates one real demo account,
verifies `/me`+`/profiles` through it, then **immediately deletes
exactly that account** by reusing `demo_purge`'s own row-deletion logic
— but only runs at all if `--database-url` is also given; without it,
the check is skipped (not failed) rather than creating an account it
can't guarantee cleanup for. This is the literal "must not create
unbounded retained demo data" requirement, enforced structurally, not
just by intention.

**Two safety fixes, caught by PR review, before this was merged:**
1. The account's id is now read directly from the returned token's
   `sub` claim (no signature verification needed — it's the check's own
   freshly-issued token) rather than from a follow-up `/me` call, and
   cleanup runs in a `finally` block. Previously, a timeout/error on
   `/me` would skip identifying the account entirely and leave it
   behind — cleanup could not depend on the verification calls
   succeeding.
2. `_cleanup_demo_account` now **refuses to delete** anything that
   isn't actually a demo account (`is_demo` true and the email under
   `demo_data.py`'s reserved domain) before calling `demo_purge`'s
   deletion logic, which does not filter on `is_demo` itself. Without
   this, pointing `--database-url` at the wrong environment by mistake
   — one that happened to have an unrelated real user at the same
   numeric id — would have deleted that real account and its data. A
   refused or failed cleanup now also fails the overall `demo_flow`
   check, not just a passing result with a buried failure detail.

**Actually run against real production this round** (read-only checks
only — no `--database-url` available in this session, so
`--include-demo-flow` was correctly skipped, not attempted): every
check passed against `https://api.nutri-matic.uk` /
`https://nutri-matic.uk` as of this writing.

## Alerts, dashboards, alert ownership

**Not configured**: this section is the specification, not a record of
something live. No alerting integration exists anywhere in the codebase.

| Condition | Suggested threshold | Where the signal comes from |
|---|---|---|
| Sustained 5xx errors | >1% of requests over 5 minutes | `elevated_status_response` (any route) |
| Backend unavailable | `/api/health` fails for >1 minute | `.github/workflows/uptime-check.yml` — runs `app/smoke_check.py` against production every 15 minutes; a failed run is a red X on the workflow (plus email, depending on watcher notification settings) |
| Readiness failure | `/api/ready` returns 503 for >2 minutes | Same `uptime-check.yml` run |
| Migration failure | `alembic upgrade head` exits non-zero in `Dockerfile`'s `CMD` | **Infra-level only** — this app's own code never runs if this step fails; must be the container platform's own deploy-failure/crash-loop alert, not anything in this repo |
| Demo-creation abuse | Sustained `demo_rate_limited`/`no_eligible_candidates`-style rejection rate, or the global circuit breaker (`demo_protection.py`) tripping repeatedly | Existing prompt-1 telemetry |
| Purge failure / retained-demo backlog | `python -m app.demo_purge report`'s `expired_demo_accounts` count staying nonzero/growing across runs | Existing prompt-1 tooling — the scheduled run genuinely applies nightly (not dry-run-only, correcting a stale claim this row previously made). No dedicated alerting wraps a *silent* failure yet — a rejected/crashed run still shows as a red X on `.github/workflows/demo-purge.yml` itself, which is the real signal until something more specific is added. |
| Database connection exhaustion | `slow_readiness_db_check` firing repeatedly, or `/api/ready`'s "database unavailable" outcome, sustained | `app/routers/health.py` |
| Abnormal recommendation latency (by mode) | `recommendation_request`'s `duration_ms` p95 exceeds a baseline, per `mode` tag | Baseline must come from real production traffic once available — no synthetic number here would be honest |
| Sudden rise in substitution 409/422 | `substitution_apply_outcome` non-`200_success` rate spikes relative to a rolling baseline | Existing telemetry |
| Data-quality contamination | `data_quality_flagged_in_aggregation` firing at a rate above near-zero | `app/routers/health.py` |
| Failed production deployment | CI/deploy pipeline failure notification (platform-native) | — |

**Alert ownership**: still not assigned — an organisational decision
for whoever operates this deployment.

## Incident response runbook

Real, usable now — even without live alerting wired up yet, this is
what to actually do when one of the conditions above is noticed (by a
human checking, in the meantime):

**Sustained 5xx / abnormal error rate**
1. Check `elevated_status_response`/`recommendation_request` in the
   backend container logs for the failing path(s) and exception type.
2. Check `/api/ready` — if it's also failing, this is a database issue,
   not an application bug; see below.
3. Mitigation: if traceable to the most recent deploy, redeploy the
   previous release (`DEPLOYMENT.md`'s rollback section — safe as long
   as the prior code tolerates the current schema, true for every
   migration in this repo so far).
4. Recovery confirmed when: `elevated_status_response` stops firing and
   `python -m app.smoke_check` passes clean against production.

**Readiness failure (`/api/ready` returning 503)**
1. Read the response body — it names which check failed (`database
   unavailable: <exception class>` or `schema not at migration head`).
2. Database-unavailable: check the database's own health/connection
   count directly; this app has no retry/backoff of its own here by
   design (a 503 is the correct signal to stop routing traffic, not
   something to paper over).
3. Schema-behind-head: the container started but `alembic upgrade head`
   didn't reach the expected revision — check the migration step's own
   logs from that deploy; do not manually run `alembic upgrade head`
   against production without rehearsing it against a restored copy
   first (`docs/migrations.md`'s own rule, unchanged).
4. Recovery confirmed when: `/api/ready` returns `200 {"status":
   "ready"}` again.

**Migration/deployment failure**
1. This app's own logs won't show anything (the migration runs before
   the app starts) —
   check the container platform's deploy history/exit code directly.
2. Mitigation: fix forward and redeploy, or roll back to the last
   successfully-deployed image; do not attempt `alembic downgrade`
   against production without reading `docs/migrations.md`'s specific
   hazards first (the `updated_at` migration's downgrade genuinely loses
   data; the baseline's downgrade drops every table).
3. Recovery confirmed when: the deploy platform reports success and
   `/api/ready` is green.

**Demo-creation abuse**
1. Check `demo_rate_limited`/the global circuit breaker's own logs
   (`app/demo_protection.py`) for scope (`ip` vs `global`) and rate.
2. `python -m app.demo_purge report` for current active/expired/total
   counts — a sudden spike in `active` alongside the rate-limit logs
   confirms real abuse rather than a false positive.
3. Mitigation: the per-IP/global limits (`DEMO_RATE_LIMIT_*` env vars,
   `docs/rate-limiting.md`) can be tightened without a code change; a
   determined distributed attacker needs an edge/infra-level control
   this app's own in-process limiter was already documented not to be a
   full substitute for.
4. Recovery confirmed when: the rate-limited/rejected rate returns to
   baseline.

**Purge failure / retained-demo backlog**
1. `python -m app.demo_purge report` — if `expired_demo_accounts` is
   nonzero and growing, purging isn't happening (scheduled or manual).
2. Run `python -m app.demo_purge purge` (dry-run — the default) and
   review the printed account list per this repo's own SAFETY GATE
   (`docs/demo-lifecycle.md`) before ever running `--apply` against
   production.
3. Recovery confirmed when: `expired_demo_accounts` returns to (near)
   zero after an authorised `--apply` run.

**Data-quality contamination (`data_quality_flagged_in_aggregation`
firing repeatedly)**
1. `python -m app.data_quality_audit` for the specific rows/nutrients
   involved (`docs/data-quality.md`).
2. Decide whether the flagged rows need a per-nutrient threshold
   adjustment (`data_quality.py`'s override dicts) or are a genuine new
   data-entry error worth excluding at the source.
3. Recovery confirmed when: the flagged rate returns to near-zero.

**Escalation owner**: placeholder — not assigned, same as alert
ownership above; an organisational decision, not a code change.

## Log retention

Not configured, unchanged from the prior version of this document:
Vercel (frontend) has its own plan-dependent retention; the backend's
actual hosting platform (confirmed live this round at
`https://api.nutri-matic.uk`, though which specific hosting service —
the EXECUTION SAFETY REQUIREMENTS context for this round mentions
Hetzner as a *possible* backend host, unconfirmed from this session)
has whatever retention its own logging setup provides, not configured
or controlled from this repository.
