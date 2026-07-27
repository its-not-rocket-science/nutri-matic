# Monitoring and alerting

Public-launch hardening prompt 6, building on operational-hardening
prompt 5's original version of this document (kept below where still
accurate; superseded parts are marked as such rather than silently
rewritten).

## Pre-flight reality check (done before any code this round)

The prompt's own explicit requirement: audit what actually exists, with
evidence, before assuming the "current position" this prompt's brief
described was still accurate. It wasn't, in two places — corrected
below rather than carried forward.

| Claim | Status | Evidence |
|---|---|---|
| CI passes on `main` | **True** | `gh run list` — latest run on `main` (`2026-07-27T13:30:13Z`) is `success`; branch protection (`gh api .../branches/main/protection`) requires `Backend tests`/`Frontend checks`, `enforce_admins: true`. |
| Backend has no hosting platform (prior doc's claim) | **False — stale** | `curl https://api.nutri-matic.uk/api/health` → `{"status":"ok"}`, `/api/ready` → `{"status":"ready"}`, both live. The backend **is** deployed and reachable at `https://api.nutri-matic.uk` — this document (and `DEPLOYMENT.md`) previously said otherwise; corrected here. |
| `SENTRY_DSN` configured anywhere real | **Not evidenced** | `gh secret list` / `gh variable list` on this repo — both empty. No proof either way for wherever the backend actually deploys from (unknown deploy pipeline, not GitHub Actions), but nothing here confirms it's set, so treated as unset. |
| Sentry captures uncaught (not just logged) exceptions | **Was unverified — now checked and true** | `sentry_sdk`'s `FastApiIntegration`/`StarletteIntegration` are in its `_AUTO_ENABLING_INTEGRATIONS` list (checked directly against the installed `sentry-sdk==2.58.0`), so `sentry_sdk.init()` enables them automatically since `fastapi`/`starlette` are installed — confirmed empirically in `test_captures_uncaught_exceptions_via_the_auto_enabled_fastapi_integration`, which raises a real unhandled exception through a live app and checks it reaches `before_send`. This was previously *assumed* rather than checked; it holds, but wasn't free of doubt going in. |
| Frontend error tracking | **Did not exist before this round** | No Sentry package anywhere in `frontend/package.json` prior to this prompt — added this round (see below). |
| Any alerting (PagerDuty/Slack/etc.) configured | **Not configured** | No integration anywhere in the codebase or repo config; unchanged from prior doc's assessment. |
| Alembic migration failures monitored | **Architecturally can't self-report** | `Dockerfile`'s `CMD` is `alembic upgrade head && uvicorn ...` — if the migration step fails, the process exits before any Python application code (including Sentry) ever runs. This has to be caught at the infra/orchestrator level (container exit code / crash-loop detection), not by this app's own code — documented as a real limitation, not solved by a workaround that can't actually work. |

## What's implemented (real, tested)

Everything from operational-hardening prompt 5 (health/readiness
endpoints, `init_monitoring()`'s no-op-without-DSN guarantee, the
original event-scrubbing policy, `recommendation_disabled`/
`substitution_apply_outcome`/`recommendation_request` logging) still
applies — see that section preserved near the bottom of this file. New
this round:

### Backend

- **Uncaught-exception capture confirmed, not assumed** — see the
  pre-flight table above.
- **Email redaction** (`app/monitoring.py::scrub_event`) — this
  prompt explicitly names emails alongside tokens/passwords/diary
  contents; the prior policy deliberately left email unscrubbed (it's
  this app's account identifier, not treated as a secret). Superseded:
  emails are now redacted by *pattern* (regex match on any string
  value, not just a key-name check — an email can show up under any
  key), recursively through nested dicts/lists. `_scrub_mapping` is now
  recursive (previously one level deep).
- **`elevated_status_response`** (`app/main.py`) — a new, app-wide
  middleware logging for any 5xx response, on any route (the existing
  recommendation-specific middleware only ever covered `/api/
  recommendations/*`). Deliberately silent on success — logging every
  request at real traffic volume would be pure noise.
- **`recommendation_request` now tags `mode`** (ingredients/recipes/
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
- **Severity correction, caught by PR review**: all five signals above
  are logged at `ERROR`, not `WARNING`. `init_monitoring()`'s
  `LoggingIntegration` is configured with `event_level=logging.ERROR` —
  a `WARNING` only ever becomes a breadcrumb attached to some later,
  unrelated captured event, never a Sentry event/alert of its own. The
  first version of this round's code logged these at `WARNING` on the
  (wrong) assumption that alone was enough to reach Sentry as an event;
  every one of the five call sites, and their tests, were corrected to
  assert `ERROR` before this was merged.
- **`send_default_pii=False`** set explicitly on `sentry_sdk.init()` —
  already the SDK's own default, but stated rather than relied upon
  silently.

### Frontend

- **`@sentry/sveltekit`** added — `hooks.client.ts` (new) and
  `hooks.server.ts` (extended) both call `Sentry.init()`, gated on
  `PUBLIC_SENTRY_DSN` via `$env/dynamic/public` (not `$env/static/
  public` — the point is exactly that it's allowed to be absent without
  failing the build, mirroring `app/monitoring.py`'s own guarantee).
  `hooks.server.ts`'s existing redirect/security-header logic
  (renamed `canonicalAndSecurityHandle`, tested exactly as before) is
  now composed with `Sentry.sentryHandle()` via `sequence()`.
- **`frontend/src/lib/sentryScrub.ts`** — the same redaction policy as
  the backend's `scrub_event` (sensitive key substrings + email-pattern
  regex, recursive), wired as Sentry's `beforeSend` on both client and
  server.
- Environment/release tagging (`PUBLIC_SENTRY_ENVIRONMENT`,
  `PUBLIC_RELEASE_VERSION`) and a configurable trace sample rate
  (`PUBLIC_SENTRY_TRACES_SAMPLE_RATE`, default `0.1`) — same shape as
  the backend's equivalents.
- **CSP fix, caught by PR review**: `vite.config.ts`'s `connect-src`
  now also allows the origin derived from `PUBLIC_SENTRY_DSN` (when
  set). The Sentry browser SDK posts error/trace envelopes straight to
  the DSN's own ingest origin, not the backend origin already
  allowlisted there — without this, the CSP this app already enforces
  would have silently blocked every envelope the moment a real DSN was
  configured, so client-side Sentry would have been wired up but never
  actually delivered anything. Verified directly: rebuilt with a real
  DSN shape set, ran the built preview server, and curled the
  `Content-Security-Policy` header to confirm the ingest origin
  actually appears in `connect-src`.

### Post-deploy smoke check — `app/smoke_check.py`

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

## Required environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SENTRY_DSN` | No | unset (backend monitoring disabled) | Enables backend Sentry. |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.1` | Backend performance-trace sampling once `SENTRY_DSN` is set. |
| `RELEASE_VERSION` | No | unset | Backend release tag (e.g. a commit SHA) — set in CI/deploy for "which deploy introduced this error" triage. Nothing currently sets this automatically; it must be wired into whatever deploys the backend. |
| `APP_ENV` | Already required (`DEPLOYMENT.md`) | `development` | Reused as Sentry's `environment` tag, backend and frontend both. |
| `PUBLIC_SENTRY_DSN` | No | unset (frontend monitoring disabled) | Enables frontend Sentry (client + server). Set in Vercel's project env vars per environment, same mechanism as `VITE_API_URL` — see `docs/frontend-deployment.md`. |
| `PUBLIC_SENTRY_ENVIRONMENT` | No | `development` | Frontend's `environment` tag. |
| `PUBLIC_RELEASE_VERSION` | No | unset | Frontend release tag. Vercel exposes the deployed commit SHA as `VERCEL_GIT_COMMIT_SHA` at build time, but that's not a `PUBLIC_`-prefixed var SvelteKit exposes to the client automatically — set `PUBLIC_RELEASE_VERSION` explicitly (e.g. via a Vercel build-step env mapping) if release tagging is wanted. |
| `PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | No | `0.1` | Frontend performance-trace sampling. |

## Local / default behaviour

Every one of the above is unset by default in local/dev/CI — both
backend and frontend behave exactly as they did before this prompt,
confirmed by `test_importing_the_app_does_not_require_sentry_dsn`
(backend) and the frontend build/preview/browser check performed this
round with no `PUBLIC_SENTRY_DSN` set (zero console errors, all
headers/functionality intact — see the prompt 5/6 verification trail
in this repo's PR history).

## Production setup — what's still a manual step

1. Create a Sentry project (backend) and one for the frontend (or reuse
   one project for both, tagged by `environment`/a service name — not
   decided here, an operational choice for whoever runs this).
2. Set `SENTRY_DSN` (backend) and `PUBLIC_SENTRY_DSN` (frontend, in
   Vercel's dashboard) to their respective DSNs.
3. Set `RELEASE_VERSION`/`PUBLIC_RELEASE_VERSION` to the deployed commit
   SHA in the same deploy step, for both halves.
4. Confirm activation: trigger a real WARNING+ (e.g. a failed login) and
   confirm it reaches the Sentry project within a few minutes, for both
   backend and frontend independently.
5. **Source maps** (frontend): not configured this round — uploading
   readable stack traces requires a `SENTRY_AUTH_TOKEN` (org-scoped,
   must never be committed) wired into the build step, which this
   session has no way to create or verify. Until that's done, frontend
   Sentry events will show minified/bundled stack traces rather than
   original source locations — usable for triage by message/tags, less
   so for exact line numbers. Documented as a known gap, not silently
   left unmentioned.

**Provider**: unchanged reasoning from the prior version of this
document — Sentry is what the prompt names as the lightweight default;
swapping providers later only means changing `app/monitoring.py` and
`frontend/src/lib/sentryScrub.ts`/the two `hooks.*.ts` files.

## Alerts, dashboards, alert ownership

**Still not configured** — same honest caveat as before: this section
is the specification, not a record of something live. Confirmed again
this round (`gh secret list`/`gh variable list` empty; no alerting
integration anywhere in the codebase).

| Condition | Suggested threshold | Where the signal comes from |
|---|---|---|
| Sustained 5xx errors | >1% of requests over 5 minutes | `elevated_status_response` (any route) / Sentry issue rate |
| Backend unavailable | `/api/health` fails for >1 minute | Uptime check against `https://api.nutri-matic.uk/api/health` |
| Readiness failure | `/api/ready` returns 503 for >2 minutes | Uptime check against `/api/ready` |
| Migration failure | `alembic upgrade head` exits non-zero in `Dockerfile`'s `CMD` | **Infra-level only** — this app's own code never runs if this step fails (see pre-flight table); must be the container platform's own deploy-failure/crash-loop alert, not anything in this repo |
| Demo-creation abuse | Sustained `demo_rate_limited`/`no_eligible_candidates`-style rejection rate, or the global circuit breaker (`demo_protection.py`) tripping repeatedly | Existing prompt-1 telemetry |
| Purge failure / retained-demo backlog | `python -m app.demo_purge report`'s `expired_demo_accounts` count staying nonzero/growing across runs | Existing prompt-2 tooling — no scheduled alerting wraps this yet (`.github/workflows/demo-purge.yml` is dry-run-only on its schedule, per its own design) |
| Database connection exhaustion | `slow_readiness_db_check` firing repeatedly, or `/api/ready`'s "database unavailable" outcome, sustained | New this round |
| Abnormal recommendation latency (by mode) | `recommendation_request`'s `duration_ms` p95 exceeds a baseline, per `mode` tag | Baseline must come from real production traffic once available — no synthetic number here would be honest |
| Sudden rise in substitution 409/422 | `substitution_apply_outcome` non-`200_success` rate spikes relative to a rolling baseline | Existing telemetry |
| Data-quality contamination | `data_quality_flagged_in_aggregation` firing at a rate above near-zero | New this round |
| Failed production deployment | CI/deploy pipeline failure notification (platform-native, not Sentry) | — |

**Alert ownership**: still not assigned — an organisational decision
for whoever operates this deployment.

## Incident response runbook

Real, usable now — even without live alerting wired up yet, this is
what to actually do when one of the conditions above is noticed (by a
human checking, in the meantime):

**Sustained 5xx / abnormal error rate**
1. Check `elevated_status_response`/`recommendation_request` logs (or
   Sentry, once configured) for the failing path(s) and exception type.
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
1. This app's own logs won't show anything (see pre-flight table) —
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

## What this round explicitly did NOT do, and why

- **Migration/startup-failure self-reporting** — architecturally
  impossible from inside this app (see pre-flight table); flagged as an
  infra-level requirement, not implemented as a code workaround that
  couldn't actually work.
- **Source-map upload** for frontend Sentry — needs a `SENTRY_AUTH_TOKEN`
  this session has no way to create or verify; documented as a manual
  follow-up, not silently skipped.
- **Live alert/dashboard configuration** — no Sentry/alerting account
  exists to configure against (confirmed via the pre-flight check, not
  assumed); the tables above are the specification for once one exists.
- **Alert/escalation ownership** — an organisational decision, not a
  code change.
