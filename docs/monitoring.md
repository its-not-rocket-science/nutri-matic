# Monitoring and alerting

Operational-hardening prompt 4, building on public-launch hardening
prompt 6's version of this document (kept below where still accurate;
superseded parts are marked as such rather than silently rewritten).

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

## New this round (operational-hardening prompt 4)

- **`validate_monitoring_config()`** (`app/monitoring.py`, called from
  `main.py` right after `init_monitoring()`) — logs a loud `ERROR`
  (`monitoring_not_configured`) if `APP_ENV=production` and
  `SENTRY_DSN` was never set, then continues starting up. Deliberately
  a warning, not the hard-fail-at-import pattern `JWT_SECRET`/
  `REDIS_URL` use (see `app/auth.py`/`app/redis_rate_limit.py`): missing
  observability is a real operational risk, but making the whole app's
  availability depend on a third-party monitoring vendor being
  configured would itself be a new production risk this app doesn't
  need — "can't see errors" is a materially different failure mode than
  "forges auth tokens" or "unlimited account creation". The log call
  reaches container/CI stderr even with zero handlers configured
  anywhere in this app, via Python's own `logging.lastResort` fallback
  — confirmed with a real subprocess (not assumed), see
  `test_warns_via_pythons_own_last_resort_handler_with_no_configured_handler`
  in `tests/test_monitoring.py`.
- **`RELEASE_VERSION` is now actually wired**, superseding this
  document's own prior "nothing currently sets this automatically"
  note: `.github/workflows/deploy.yml`'s deploy job exports
  `RELEASE_VERSION=<the exact deployed commit SHA>` into the SSH
  session before `docker compose build backend`/`up -d backend`, and
  `docker-compose.yml`'s `backend.environment` threads it through via
  `${RELEASE_VERSION:-}` — the same shell-interpolation pattern
  `CORS_ORIGINS` already used. No manual step on a normal deploy.
- **Frontend source-map upload** (requirement 5's gap, closed) —
  `frontend/vite.config.ts` conditionally adds `@sentry/vite-plugin`'s
  `sentryVitePlugin()` (bundled transitively via the already-installed
  `@sentry/sveltekit`; no new `package.json` dependency) when
  `SENTRY_AUTH_TOKEN` is set at build time, uploading readable stack
  traces and then deleting the `.map` files from the deployed bundle.
  Entirely absent — not erroring — when `SENTRY_AUTH_TOKEN` is unset,
  same as every other optional-credential path in this repo. UNVERIFIED
  against a real Sentry org (this session has no `SENTRY_AUTH_TOKEN`);
  verified instead that `npm run build` still succeeds cleanly with it
  unset.
- **`frontend/vercel.json`** (new) maps `PUBLIC_RELEASE_VERSION` to
  Vercel's own `$VERCEL_GIT_COMMIT_SHA` system env var, so the frontend
  release tag lines up with the backend's `RELEASE_VERSION` without a
  manual per-deploy step — UNVERIFIED against a real Vercel deploy in
  this session (no live Vercel project access); relies on
  `$env/dynamic/public` reading this at request time on the deployed
  serverless function, matching how `PUBLIC_SENTRY_DSN` already works.
- **Deploy annotations** (requirement 9) — a new, optional, non-blocking
  step in `deploy.yml`'s `deploy` job records a Sentry release + a
  production deploy against it via Sentry's REST API, gated on
  `SENTRY_AUTH_TOKEN`/`SENTRY_ORG`/`SENTRY_PROJECTS` (plural — this step
  can annotate multiple Sentry projects, e.g. backend and frontend,
  unlike the single-project `SENTRY_PROJECT` the build-time source-map
  step above uses) all being set. Every Sentry API call uses `|| echo
  "::warning::..."`, never `set -e` — a monitoring-annotation failure
  can never fail the deploy itself. UNVERIFIED against a real Sentry
  org, same caveat as above.
- **Uptime check** (requirement 7) — `.github/workflows/uptime-check.yml`
  runs the existing read-only `app/smoke_check.py` against
  `https://api.nutri-matic.uk`/`https://nutri-matic.uk` every 15
  minutes, achievable entirely from this repository without an external
  uptime-SaaS account. A failing run is a visible red X on the workflow
  (plus, depending on each watcher's own GitHub notification settings,
  an email) — a real always-on signal, but not the same as a paged
  on-call alert with a named owner; "alert ownership: not assigned"
  below still applies to this too.

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
| `RELEASE_VERSION` | No | unset | Backend release tag — now wired automatically end-to-end by `deploy.yml`/`docker-compose.yml` (see "New this round" above); nothing to configure manually on a normal deploy. |
| `APP_ENV` | Already required (`DEPLOYMENT.md`) | `development` | Reused as Sentry's `environment` tag, backend and frontend both. When `production` and `SENTRY_DSN` is unset, `validate_monitoring_config()` logs a loud `ERROR` at startup (see "New this round" above) — starts anyway, doesn't block. |
| `PUBLIC_SENTRY_DSN` | No | unset (frontend monitoring disabled) | Enables frontend Sentry (client + server). Set in Vercel's project env vars per environment, same mechanism as `VITE_API_URL` — see `docs/frontend-deployment.md`. |
| `PUBLIC_SENTRY_ENVIRONMENT` | No | `development` | Frontend's `environment` tag. |
| `PUBLIC_RELEASE_VERSION` | No | unset | Frontend release tag — now wired automatically via `frontend/vercel.json`'s `env` mapping to Vercel's own `$VERCEL_GIT_COMMIT_SHA` (see "New this round" above); nothing to configure manually on Vercel, UNVERIFIED against a live deploy. |
| `PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | No | `0.1` | Frontend performance-trace sampling. |
| `SENTRY_AUTH_TOKEN` / `SENTRY_ORG` / `SENTRY_PROJECT` | No | unset (no source-map upload) | Frontend build-time only — enables `sentryVitePlugin()` in `vite.config.ts` to upload readable source maps. Singular `SENTRY_PROJECT`: one frontend build targets one Sentry project. |
| `SENTRY_AUTH_TOKEN` / `SENTRY_ORG` / `SENTRY_PROJECTS` | No | unset (no deploy annotation) | `deploy.yml`'s deploy job only — records a Sentry release + production deploy annotation. Plural `SENTRY_PROJECTS` (comma-separated): this step can annotate more than one Sentry project (e.g. backend and frontend) in one deploy. Same `SENTRY_AUTH_TOKEN`/`SENTRY_ORG` secret names as the build-time pair above but a distinct GitHub Actions secret from the frontend build's own env — don't assume setting one sets the other. |

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
5. **Source maps** (frontend): the build-step wiring now exists
   (`sentryVitePlugin()` in `vite.config.ts`, see "New this round"
   above) — set `SENTRY_AUTH_TOKEN`/`SENTRY_ORG`/`SENTRY_PROJECT` (org-
   scoped token, must never be committed) as Vercel build-env vars to
   activate it. Until that secret is actually set on the real Vercel
   project, frontend Sentry events will still show minified/bundled
   stack traces rather than original source locations — the code is no
   longer the gap, an actual token being provisioned still is.

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
| Backend unavailable | `/api/health` fails for >1 minute | `.github/workflows/uptime-check.yml` — runs `app/smoke_check.py` against production every 15 minutes; a failed run is a red X on the workflow (plus email, depending on watcher notification settings) |
| Readiness failure | `/api/ready` returns 503 for >2 minutes | Same `uptime-check.yml` run |
| Migration failure | `alembic upgrade head` exits non-zero in `Dockerfile`'s `CMD` | **Infra-level only** — this app's own code never runs if this step fails (see pre-flight table); must be the container platform's own deploy-failure/crash-loop alert, not anything in this repo |
| Demo-creation abuse | Sustained `demo_rate_limited`/`no_eligible_candidates`-style rejection rate, or the global circuit breaker (`demo_protection.py`) tripping repeatedly | Existing prompt-1 telemetry |
| Purge failure / retained-demo backlog | `python -m app.demo_purge report`'s `expired_demo_accounts` count staying nonzero/growing across runs | Existing prompt-1 tooling — the scheduled run genuinely applies nightly (not dry-run-only, correcting a stale claim this row previously made). No dedicated alerting wraps a *silent* failure yet — a rejected/crashed run still shows as a red X on `.github/workflows/demo-purge.yml` itself, which is the real signal until something more specific is added. |
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
- **Source-map upload activation** for frontend Sentry — the build-step
  code now exists (this round), but still needs a real
  `SENTRY_AUTH_TOKEN` this session has no way to create or verify;
  documented as a manual follow-up, not silently skipped.
- **Live alert/dashboard configuration** — no Sentry/alerting account
  exists to configure against (confirmed via the pre-flight check, not
  assumed); the tables above are the specification for once one exists.
- **Alert/escalation ownership** — an organisational decision, not a
  code change.
