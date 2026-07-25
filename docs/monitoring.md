# Monitoring and alerting

Operational-hardening prompt 5. Covers what's implemented in code
(real, tested) versus what still needs an actual Sentry account/plan
from the repository owner to become live (specification only, honestly
labelled as such below — this doc does not claim monitoring is "on"
anywhere; it isn't, until `SENTRY_DSN` is set somewhere real).

## What's implemented

- **`app/monitoring.py`** — `init_monitoring()`, called once at startup
  (`main.py`). No-op unless `SENTRY_DSN` is set: local development and
  CI need zero monitoring configuration, ever (`tests/test_monitoring.py`
  confirms this directly, including that importing the app at all
  succeeds with no `SENTRY_DSN` in the environment).
- **Event scrubbing** (`monitoring.scrub_event`, wired as Sentry's
  `before_send` hook) — strips, from request headers, request body/query
  data, and any `extra=`/breadcrumb context, anything whose key contains
  `authorization`, `token`, `password`, `secret`, `jwt`, `cookie`,
  `note`, or `medical` (case-insensitive) — replaced with `[Scrubbed]`.
  A `DATABASE_URL`-shaped value has its password redacted rather than
  removed outright (host/db name stay useful for triage). This is
  deliberately a broad substring policy, not a narrow allowlist: a new
  sensitive field added anywhere in the app is scrubbed by default
  rather than silently leaking until someone remembers to extend a list.
- **Structured logging at the specific points this prompt names**:
  - `recommendation_safety.assess_eligibility` logs `WARNING
    recommendation_disabled` with `profile_id` and `reason_code`
    whenever it returns `enabled=False` — one place, covers all four
    `/api/recommendations/*` endpoints that call it, never logs the
    medical constraint's free-text note.
  - `routers/recommendations.py`'s `apply_substitution` logs `INFO
    substitution_apply_outcome` with `entry_id`/`source`/`outcome` at
    every exit point: `404_not_found`, `422_plain_food_entry`,
    `409_stale_recipe_id`, `409_stale_version`,
    `404_inaccessible_replacement`, `422_dietary_rejection`,
    `422_recommendations_disabled`, `409_concurrent_conflict`,
    `200_success`.
  - `main.py`'s `log_recommendation_endpoint_latency` middleware logs
    `INFO recommendation_request` with path/method/status/duration for
    every `/api/recommendations/*` request (not every request in the
    app — this is the one prompt explicitly asks to be watched).
  All of the above are plain `logging` calls — useful in self-hosted
  logs whether or not Sentry is configured. When it is, its
  `LoggingIntegration` (WARNING+ as breadcrumbs, ERROR+ as events) turns
  them into Sentry data with no code change needed at the call sites.
- **Health endpoints**:
  - `GET /api/health` — liveness. Always `200 {"status": "ok"}` if the
    process is serving requests at all; never touches the database.
  - `GET /api/ready` — readiness. `200 {"status": "ready"}` only if the
    database is reachable *and* its Alembic revision matches the
    migration head on disk; `503` with a short, secret-free reason
    otherwise (`database unavailable: <exception class name>`, or
    `database schema not at migration head (current=..., head=...)`).
    The migration-head check is what catches "the container started but
    the migration step failed or was skipped" — see
    `docs/migrations.md`.
- **`SENTRY_TRACES_SAMPLE_RATE`** (default `0.1`) — when monitoring is
  active, Sentry's own performance monitoring captures per-request
  timing for every endpoint automatically (FastAPI/Starlette
  auto-instrumentation), independent of the recommendation-specific
  logging middleware above.

## Required environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SENTRY_DSN` | No | unset (monitoring disabled) | Enables Sentry. Unset means every check in this document that depends on Sentry is inactive — logging still happens locally, nothing is sent anywhere. |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.1` | Fraction of requests Sentry captures full performance traces for, once `SENTRY_DSN` is set. |
| `RELEASE_VERSION` | No | unset | Tags Sentry events with a release identifier (e.g. a commit SHA) — set this in CI/deploy for "which deploy introduced this error" triage. |
| `APP_ENV` | Already required (see `DEPLOYMENT.md`) | `development` | Reused as Sentry's `environment` tag — no separate variable needed. |

## Local / default behaviour

`SENTRY_DSN` unset (the default in every local/dev/CI environment, and
in `docker-compose.yml`): `init_monitoring()` returns immediately,
`sentry_sdk.init()` is never called, no network configuration is
attempted, and the app behaves exactly as it did before this prompt
except for the plain-logging calls above (which just go to stdout/
wherever the process's normal logging is configured, same as any other
`logging.getLogger(__name__)` call in this codebase).

## Production setup

1. Create a Sentry project (or equivalent — see "provider" below) and
   obtain its DSN.
2. Set `SENTRY_DSN` in the production environment.
3. Set `RELEASE_VERSION` to the deployed commit SHA in the same deploy
   step that sets `SENTRY_DSN`, so events are attributable to a
   specific release.
4. Confirm activation: trigger any WARNING+ log line (e.g. hit a
   recommendation endpoint for an under-18 test profile) and confirm it
   appears in the Sentry project within a few minutes.

**Provider**: this repo has no existing monitoring provider to prefer
(`docs/production-readiness-audit.md` doesn't name one) — Sentry is
used because the prompt names it as the lightweight default when
nothing else is already in place. Swapping providers later only means
changing `app/monitoring.py`'s `init_monitoring()`/`scrub_event`
implementations; nothing else in the app talks to Sentry directly (see
"what's implemented" above — application code only ever calls
`logging`).

## Alerts, dashboards, alert ownership

**Not configured** — these require an actual Sentry project (or
equivalent) that doesn't exist yet, so nothing here has been created;
this section is the specification for what to set up once one does,
not a record of something already live. Do not read the presence of
this document as evidence that alerting is active.

Alerts to configure, matching this prompt's explicit list:

| Condition | Suggested threshold |
|---|---|
| Sustained 5xx errors | >1% of requests over 5 minutes |
| Backend unavailable | `/api/health` fails for >1 minute |
| Readiness failure | `/api/ready` returns 503 for >2 minutes (allows a brief window for a rolling deploy's old/new instances to overlap) |
| Migration failure | the `alembic upgrade head` step in `Dockerfile`'s `CMD` exits non-zero (deploy-platform-level: fail the deploy, don't start serving) |
| Database connection exhaustion | connection pool errors logged, or `/api/ready`'s "database unavailable" outcome, sustained |
| Abnormal recommendation latency | `recommendation_request` `duration_ms` p95 exceeds a baseline (establish the baseline from real production traffic once available — no synthetic number here would be honest) |
| Sudden rise in substitution 409/422 | `substitution_apply_outcome` non-`200_success` rate spikes relative to a rolling baseline |
| Failed production deployment | CI/deploy pipeline failure notification (platform-native, not Sentry) |

**Alert ownership**: not assigned — this is an organisational decision
for whoever operates this deployment, not something a code change can
decide on the repository's behalf.

## Log retention

Not configured — depends entirely on where production logs actually go
(the deploy platform's own log aggregation), which isn't chosen yet
(see `DEPLOYMENT.md` item 6, the SvelteKit adapter question, for the
related "where does this actually run" gap). Revisit once a concrete
hosting platform is chosen.

## Incident response

Not written — a real incident-response runbook needs to reference real
alert channels, on-call ownership, and a real dashboard, none of which
exist yet (see above). Placeholder acknowledged rather than fabricated;
write this once the alerts above are actually configured against a real
provider.
