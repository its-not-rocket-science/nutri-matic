# Final operational hardening

Tracks the "Nutri-Matic Final Operational Hardening Prompts" round: 7
prompts assuming the recommendation engine, security hardening, Alembic
migrations, safe `updated_at` backfill, integer row-version concurrency,
deployment documentation, and CI workflow (`docs/production-hardening.md`)
are already done. This round closes the remaining operational gaps:
real CI execution evidence, branch protection, pre-stamp schema
verification, database-enforced concurrency, monitoring, the frontend
production adapter, and a final validation pass. Same per-prompt
structure as the other hardening docs.

## Prompt 1: verify and fix GitHub Actions execution

`.github/workflows/ci.yml` already triggered on push-to-main and pull
requests (added in `docs/production-hardening.md`'s prompt 5), but
lacked several things this prompt asks for explicitly:

- **`workflow_dispatch`** — added, so a run can be triggered manually
  without needing a push.
- **Stable, explicit check names** — jobs previously had no `name:`,
  so their displayed check name was the raw job id (`backend`/
  `frontend`). Added `name: Backend tests` / `name: Frontend checks` —
  exactly the names prompt 2's branch protection will need to reference,
  chosen to be stable across future implementation changes.
- **A dedicated CREATEDB-privilege verification step**, run before the
  test suite. `tests/test_migrations.py`/`tests/test_verify_pre_alembic_
  schema.py` already self-skip (correctly) when the connecting Postgres
  role can't `CREATEDB` — but a silent skip in CI would defeat this
  prompt's explicit acceptance criterion ("migration tests execute
  rather than skip") without anyone noticing. Two independent guards
  now exist: this CI step fails the job loudly before tests even run if
  the service is ever reconfigured wrong, and the test files themselves
  raise at collection time (not skip) when `CI` is set and the privilege
  check fails — verified directly, all three paths: local skip,
  CI-without-CREATEDB hard failure, CI-with-CREATEDB passing normally.
- **pip dependency caching** for the backend job, matching the
  frontend job's existing npm cache.
- Confirmed no `continue-on-error`/`|| true`/conditional skipping hides
  a real test, type-check, or build failure — only the two explicitly
  informational vulnerability-scan steps use `|| true`, unchanged from
  before and clearly commented as intentional.

**Done, after this round's commits were pushed** — and it immediately
earned its keep: the first real run
(https://github.com/its-not-rocket-science/nutri-matic/actions/runs/30164523528)
failed the `Backend tests` job with `ModuleNotFoundError: No module
named 'app'` on every test file. Real, pre-existing bug, not introduced
by this round: `ci.yml` ran a bare `pytest -q`, which — unlike `python
-m pytest`, the form every local run of this suite has ever used —
doesn't add the working directory to `sys.path`. This has apparently
been failing on every CI run going back before this hardening round
even started (confirmed by checking prior run history). Fixed by
changing to `python -m pytest -q`; reproduced the failure locally with
a bare `pytest` invocation first, to be sure the fix addressed the real
cause rather than papering over a flake. Second run, after the fix
(https://github.com/its-not-rocket-science/nutri-matic/actions/runs/30164682584):
both jobs green — `Backend tests` in 4m12s (**991 passed, 0 skipped, 0
failed** — matches the local real-Postgres run exactly, migration/
verifier/health/concurrency tests all executed for real, not skipped),
`Frontend checks` in 33s (**17 passed**, clean type-check, successful
build). This is genuine GitHub evidence, not a local run reported as if
it were one.

## Prompt 2: branch protection

**Not applied.** This is a repository-admin action affecting every
future contributor's workflow — pushing code (already pre-authorised,
repeatedly, this session) and changing access-control/branch-protection
settings are different classes of consequence, and the latter needs the
repository owner's explicit go-ahead in the moment, not inference from
"execute the prompts". Exact required settings, for when that's given:

- Require a pull request before merging into `main`.
- Require status checks **`Backend tests`** and **`Frontend checks`**
  (the exact names from prompt 1's `ci.yml`) to pass before merging.
- Require branches to be up to date with `main` before merging.
- Restrict force pushes and branch deletion on `main`.
- Require conversation resolution before merging.
- Consider requiring at least one approving review — left to the
  repository owner's judgement on team size/workflow.
- No admin bypass unless explicitly wanted.

Via `gh`: `gh api repos/its-not-rocket-science/nutri-matic/branches/main/protection --method PUT --input <payload>` with a JSON payload encoding the settings above (`required_status_checks.contexts: ["Backend tests", "Frontend checks"]`, `enforce_admins`, `required_pull_request_reviews`, `restrictions: null`, `allow_force_pushes: false`, `allow_deletions: false`, `required_conversation_resolution: true`). Or via the UI: Settings → Branches → Add branch protection rule → `main`, ticking the equivalent boxes and selecting the two check names from the dropdown (only available after prompt 1's workflow has run at least once on the repo, since GitHub only offers checks it's actually seen).

**If job names ever change**: branch protection's required-check list
must be updated to match — it does not track `ci.yml` automatically.
Update the rule's selected checks in the same PR that renames a job.

## Prompt 3: pre-stamp schema verification

`app/verify_pre_alembic_schema.py` — full detail in
`docs/migrations.md` and the commit that introduced it. Summary: a
read-only CLI that runs the baseline migration's own `upgrade()` against
a recording stand-in for Alembic's `op` (never a real connection), then
compares that expected shape against a live database via
`sqlalchemy.inspect` reflection only. `PASS`/`FAIL` with a specific
issue list, redacted credentials, non-zero exit on failure, PostgreSQL
only. `tests/test_verify_pre_alembic_schema.py` — 10 tests, exact-match
passes cleanly, each of a missing table/column/type-mismatch/missing
unique index/missing `pg_trgm` independently confirmed to fail with a
relevant message, plus redaction and exit-code checks.

**Real finding**: this repo's own `docker-compose` Postgres was stamped
(in the previous round, before this tool existed) without any such
check, and doesn't actually match the baseline — 29 missing objects.
Documented in `docs/migrations.md` and `DEPLOYMENT.md` rather than
silently fixed, since it holds real data.

## Prompt 4: structurally enforce optimistic concurrency

**The gap this closes was real, not hypothetical.** The previous
round's `entry.version != body.expected_version` check (Python-level,
read-then-compare-then-write) does correctly reject a *replayed* or
*client-known-stale* request — every existing sequential-HTTP-request
test already proved that. What it does **not** close is a genuine race
between two truly concurrent requests: both could read the same
`version`, both pass the equality check in their own request's memory,
and then the *second* commit would simply overwrite the first's row
wholesale (an unconditional `UPDATE ... WHERE id = :id`, no version
predicate) — a real lost-update bug that sequential pytest requests
structurally cannot exercise, since they never actually overlap.

**Fix, option A from the prompt's own priority order — SQLAlchemy's
native versioned-row support**: `models.DiaryEntry`/`MealPlanEntry`
gained `__mapper_args__ = {"version_id_col": version}`. SQLAlchemy now
manages the column itself: every UPDATE it emits for one of these rows
gets `WHERE version = <the value this session loaded>` appended and
`version = version + 1` added to `SET`, and raises `StaleDataError` if
zero rows match. This holds for **any** future code path that mutates
one of these rows, not just the one hand-written check in
`apply_substitution` — directly satisfying "structurally enforced
rather than relying on every future mutation site remembering to
increment version."

The previous explicit `entry.version += 1` was removed (it would have
double-incremented alongside the new automatic mechanism). A new small
module, `app/entry_mutation.py`, centralises the one thing every mutation
site needs: call `commit_entry_mutation(db)` instead of a bare
`db.commit()`; it translates SQLAlchemy's `StaleDataError` into this
app's own `EntryConflict`, so callers never depend on an ORM-internal
exception type directly. `apply_substitution` is currently the only
caller — the module exists so a second mutation endpoint reuses the
same translation rather than re-implementing it.

The Python-level `expected_version`/`expected_current_recipe_id` checks
stay, for a fast, specific 409 message on the common case (a suggestion
generated against data that's since changed) — `EntryConflict` is the
second, structural guard for the genuine concurrent-race case that
check alone can't close.

**Tests**:

- `test_recommendations_substitutions_api.py` gained
  `test_meal_plan_source_apply_works_identically` (this file previously
  only exercised `source="diary"` — prompt 4's explicit "diary and
  meal-plan paths both work") and a version-increments-by-exactly-1
  assertion on the existing success test (catching exactly the
  double-increment bug the refactor could have introduced).
- New file, `test_entry_optimistic_concurrency.py` — three tests
  exercising the mechanism directly at the ORM/session layer rather
  than through sequential HTTP requests, since that's the only way to
  actually prove the database predicate (not the Python check) is what
  stops a lost update: two independent `Session` objects both load the
  same row; the first commits; the second — still holding its
  pre-conflict in-memory copy — has its commit rejected with
  `StaleDataError` (`test_second_writer_fails_at_the_database_predicate_
  not_in_python`); the app-facing wrapper translates that to
  `EntryConflict` and leaves the session usable
  (`test_commit_entry_mutation_translates_stale_data_error_and_leaves_
  session_usable`); and the loser's write never partially lands — every
  field the loser tried to change is confirmed absent from the final
  row state, not just the one the test happens to check first
  (`test_transaction_rollback_leaves_no_partial_mutation`).

Full backend suite result recorded in prompt 7's final report.

## Prompt 5: production monitoring and alerting

Full detail in `docs/monitoring.md` — summary here. **Honesty note
first**: nothing here is actually live. There is no Sentry account (or
equivalent) provisioned for this project, so `SENTRY_DSN` is unset
everywhere, monitoring is a no-op, and the alerts/dashboards/log-
retention/incident-response sections of `docs/monitoring.md` are a
specification for the repository owner to complete, not a record of
something already configured. What *is* real: the code is written,
tested, and ready to activate the moment a real DSN is set, with zero
further code changes needed.

- **`app/monitoring.py`** — `init_monitoring()` (no-op without
  `SENTRY_DSN`, called once at startup), `scrub_event` (Sentry's
  `before_send` hook — strips anything key-matching authorization/
  token/password/secret/jwt/cookie/note/medical, redacts a database
  URL's password rather than removing it outright), and
  `alembic_head_and_current()` (reads the live `alembic_version` table
  plus the migration scripts on disk, for the readiness check below).
- **`/api/health`** (liveness, moved here from an inline stub in
  `main.py` — same path/response, not a breaking change) and
  **`/api/ready`** (readiness — 503 if the database is unreachable, or
  if its Alembic revision doesn't match head, with a short,
  credential-free reason either way).
- **Structured logging** at exactly the two points this prompt names
  explicitly: `recommendation_safety.assess_eligibility` logs once,
  centrally, whenever it disables the engine (covers all four
  `/api/recommendations/*` endpoints, never the medical constraint's
  free-text note); `apply_substitution` logs one line per outcome
  (success, each 409/422/404 case, distinguished by an `outcome` code).
  Plus a `/api/recommendations/*`-scoped latency/status-code logging
  middleware in `main.py` (the specific endpoint family this prompt
  asks to be watched, not a generic access log for the whole app).
- `sentry_sdk` added to `requirements.txt` (already installed in this
  environment; pinned to the installed version, `2.58.0`).

**Tests**: `test_monitoring.py` — `init_monitoring()` is a no-op
without `SENTRY_DSN` (and importing the whole app succeeds with no
monitoring configuration at all, confirming "missing credentials do not
break local development" isn't just true of the one function but of the
app as a whole); initialises when a DSN is set; six scrubbing cases
(auth headers, cookies, password/token body fields, medical/dietary
note fields, `extra` context including a database URL, breadcrumb
data). A dedicated fixture tears Sentry's global client back down after
every test in this file — the SDK's own state is process-global, so
leaving a fake DSN active would make unrelated tests' `WARNING`-level
log calls attempt real network sends (caught directly: the very first
run of this file printed "Sentry is attempting to send 6 pending
events" before the teardown fix). `test_health.py` — liveness always
`200`; readiness succeeds when the database responds and the revision
matches head; fails with `503` (never a raw exception/500) when the
database raises, when the revision is behind head, and when
`alembic_version` doesn't exist yet at all (`current=None`); and a
dedicated test confirming neither endpoint's response body ever
contains a database URL's password or host under any of those outcomes.

Full backend suite: 977 passed (up from 962), 14 skipped (the same
migration/verifier tests, correctly self-skipping locally), 0
regressions.

## Prompt 6: select the correct SvelteKit production adapter

Full detail in `docs/frontend-deployment.md` — summary here.
`frontend/vite.config.ts` (this project configures the adapter via the
`sveltekit()` Vite plugin's options, not a separate `svelte.config.js` —
`DEPLOYMENT.md`'s earlier reference to `svelte.config.js` was
inaccurate and has been corrected) swapped `@sveltejs/adapter-auto` for
`@sveltejs/adapter-node`. Chosen, not guessed: this repo's only actual
deployment story is the backend's own `Dockerfile`/`docker-compose.yml`
— a plain Node server is the standard adapter for that kind of Docker/VM
deploy, and nothing in this repo points at Vercel/Netlify/Cloudflare.

**Verification, real not inferred**:

- `npm run build` — `adapter-auto`'s "Could not detect a supported
  production environment" warning is gone; build output confirms `Using
  @sveltejs/adapter-node`.
- The built server, run locally, correctly served the root route,
  `/login`, and a nested route hit directly (`/diary` — proving
  refresh-on-a-nested-route works, since a raw GET returning real SSR
  HTML rather than a 404 is exactly what that needs), 404s a genuinely
  nonexistent route, and serves static assets — checked via direct HTTP
  requests, not assumed from the adapter's general reputation.
- **A full browser smoke test against a temporary, fully isolated
  backend** (its own throwaway Postgres database, migrated to head,
  `CORS_ORIGINS` scoped to the preview server's origin — the real
  `docker-compose` backend and its data were never touched): registered
  a real account through the actual UI, confirmed via the browser's own
  network log that the CORS preflight and the real request both
  succeeded for registration, session check, and profile load; opened
  the diary page and expanded the recommendation panel, confirming
  `GET /api/recommendations/ingredients` returned `200` — the panel
  genuinely loads and calls the backend, not just renders an empty
  shell. No console errors, no CORS failures. Everything temporary was
  torn down afterward (server processes killed, throwaway database
  dropped, browser tab closed).
- `vitest run` (17 passed) and `svelte-check` (0 errors, same 1
  pre-existing unrelated warning) both remain green after the
  dependency swap.

**Not done**: an actual external preview deployment on real hosting
infrastructure — none is selected for this project yet. The smoke test
above is real (a real built server, a real isolated backend, a real
browser) but ran locally, not on production-equivalent infrastructure —
stated plainly in `docs/frontend-deployment.md` rather than implied
otherwise.

**Also fixed while here**: `DEPLOYMENT.md` and `docs/production-
hardening.md` both referenced this gap as "item 6" / pointed at a
`frontend/svelte.config.js` that doesn't exist — updated both to point
at `docs/frontend-deployment.md` and the real config file instead of a
stale numbered reference and an inaccurate filename.

### Correction: adapter-node was the wrong choice — this repo already has Vercel

The "nothing in this repo points at Vercel/Netlify/Cloudflare" claim
above was wrong — checked only repo-local files
(`Dockerfile`/`docker-compose.yml`) and never checked *actual current
hosting*, which task 1 of this prompt explicitly asks for
("Identify the real deployment target from repository configuration
**and current hosting**"). This repo has a live Vercel project
(`pauls-projects-24d18deb/nutri-matic`) connected via GitHub, auto-
deploying every push and PR — discovered only afterward, via the
`Vercel`/`Vercel Preview Comments` status checks that appeared on an
unrelated pull request (the first one this repo ever needed, once
branch protection went in — see prompt 2). `adapter-node`'s build did
report "Ready" when Vercel built it, but that's Vercel tolerating a
plain Node server bundle, not the same thing as using its native Build
Output API the way `adapter-vercel` does — never confirmed working
end-to-end there.

**Fixed**: swapped `@sveltejs/adapter-node` for `@sveltejs/
adapter-vercel`. `npm run build` now produces `.vercel/output/`
matching Vercel's Build Output API v3 shape (`config.json`,
`functions/`, `static/`) rather than a standalone server bundle.
`vitest run` (17 passed) and `svelte-check` (0 errors) both still
green. Full detail, including what's still not independently
re-verified against a real Vercel deployment (no Vercel CLI credentials
available in this environment), in `docs/frontend-deployment.md`.

Left as a durable note for next time: check a repo's connected
platform integrations (PR status checks, or the hosting dashboard
directly), not just its own committed config files, before concluding
what "current hosting" is.

## Prompt 7: final operational validation

Per this prompt's own instruction: nothing below is reported as passing
if it was skipped, inferred from code, run only locally when the
requirement asked for GitHub evidence, tested against SQLite when
PostgreSQL behaviour matters, or documented without being configured.
Where that applies, it's stated explicitly rather than glossed over.

**1. Commit SHA**: `061e78a` (the CI-fix commit; this report's own
commit lands one past it — check `git log` for the actual current tip,
this SHA is a snapshot, not a moving reference). This round's full
range on `origin/main`: `da53c9b..061e78a`.

**2. Alembic head revision**: `d7819c868cf4` (`add diary and meal plan
entry version`). Full chain: `aac138c38096` (baseline) → `dba3649596f0`
(`updated_at` backfill) → `d7819c868cf4` (head).

**3. CI run URL and results**: **real, after push — and it found a real
bug.** First run
(https://github.com/its-not-rocket-science/nutri-matic/actions/runs/30164523528)
failed: `ci.yml` invoked a bare `pytest -q`, which doesn't add the
working directory to `sys.path`, so every test file's `from app...`
import failed with `ModuleNotFoundError`. Pre-existing, not introduced
by this round — reproduced locally to confirm, then fixed
(`python -m pytest -q`) and pushed as a follow-up commit. Second run,
after the fix
(https://github.com/its-not-rocket-science/nutri-matic/actions/runs/30164682584):
**both jobs green** — `Backend tests` (991 passed, 0 skipped, 0 failed,
4m12s — matches the local real-Postgres run exactly) and `Frontend
checks` (17 passed, clean type-check, successful build, 33s). See
prompt 1's section above for the full account.

**4. Required branch-protection check names**: `Backend tests`,
`Frontend checks` — exact job names from `.github/workflows/ci.yml`
(prompt 1), now confirmed against a real successful run, not just the
YAML source. Not yet configured as required checks (prompt 2 — a
repo-admin action pending the owner's explicit go-ahead, not applied
unilaterally).

**5. Backend and frontend test counts**: backend — **991 passed, 0
skipped, 0 failed**, run against real Postgres
(`DATABASE_URL=postgresql://nutrimatic:nutrimatic@localhost:5433/nutrimatic`,
a role with `CREATEDB`) so every migration/verifier/health test executed
for real rather than self-skipping. Frontend — **17 passed** (`vitest
run`), **0 type errors** (`svelte-check`, 1 pre-existing unrelated
warning).

**6. Migration test results**: `tests/test_migrations.py` — **4/4
passed** against real Postgres: fresh-install `upgrade head` (creates
the full schema including the `pg_trgm` extension), `downgrade base`
(drops everything back down), the documented `stamp`-then-`upgrade`
workflow, and the `updated_at` backfill against a table with real
pre-existing rows (confirmed backfilled, not left `NULL`, not lost).

**7. Concurrency test results**: `tests/test_entry_optimistic_
concurrency.py` — **3/3 passed**, proving the database-level predicate
(not a Python check) rejects a second writer that lost the race, that
the app-facing `EntryConflict` wrapper leaves the session usable
afterward, and that a lost race leaves zero partial mutation (every
field the loser tried to change confirmed absent from the final row).
`tests/test_recommendations_substitutions_api.py::TestApplySubstitution`
— **17/17 passed**, including the explicit concurrent-update scenario
(two "clients" holding the same version, racing different replacements)
and both diary and meal-plan source paths.

**8. Pre-stamp verifier result**: `tests/test_verify_pre_alembic_
schema.py` — **10/10 passed** (exact-match pass, and each of a missing
table/column/type-mismatch/missing-unique-index/missing-`pg_trgm`
independently confirmed to fail with a specific message, plus
redaction and exit-code checks). **Separately, run for real against
this repo's own `docker-compose` Postgres**: `FAIL`, 29 issues — see
prompt 3's section above. This remains open; it was not remediated as
part of this round (the database holds real data and fixing it wasn't
requested).

**9. Monitoring provider and alert list**: Sentry, **not provisioned**
(no `SENTRY_DSN` configured anywhere real) — code is written and
tested (`tests/test_monitoring.py`, `tests/test_health.py`) to activate
the moment a real DSN is set. Alert list (sustained 5xx, backend
unavailable, readiness failure, migration failure, connection
exhaustion, abnormal recommendation latency, substitution 409/422
spike, failed deployment) is specified in `docs/monitoring.md`, not
configured in any real alerting system.

**10. Frontend adapter selected**: `@sveltejs/adapter-vercel` —
corrected from an initial, wrong `adapter-node` choice once this
repo's existing live Vercel integration was discovered (see prompt 6's
"Correction" subsection above). `npm run build` produces `.vercel/
output/` matching Vercel's Build Output API v3 shape; `vitest run`/
`svelte-check` both green. Not yet independently re-verified against
an actual Vercel deployment from this environment (no Vercel CLI
credentials available here) — see `docs/frontend-deployment.md`.

**11. Deployment and rollback commands**: `docs/migrations.md` (local/
production migration commands, the mandatory `stamp` step for existing
databases, and rollback — including the two specific data-loss/
destructive-downgrade hazards already on record for this repo's actual
migrations) and `DEPLOYMENT.md`'s "Deployment checklist" (backups,
schema verification, smoke tests, rollback, monitoring) together cover
this. `docs/frontend-deployment.md` covers the frontend's own build/run
commands separately.

**12. Remaining risks** (carried forward from `docs/production-
hardening.md` where still open, updated where this round closed them,
plus new ones this round surfaced):

- **Resolved**: this round's commits are now pushed and CI is verified
  green on GitHub itself (see point 3 above) — no longer a risk, kept
  here only to mark it closed relative to earlier drafts of this report.
- **Branch protection is not configured.** Exact settings and check
  names are specified (prompt 2's section) but not applied — a
  repo-admin action pending the owner's explicit go-ahead.
- **The `docker-compose` Postgres does not actually match the baseline
  it's stamped at** — real, verified drift (29 missing objects),
  found by this round's own tooling, not remediated. Do not treat that
  database as trustworthy until `python -m app.verify_pre_alembic_
  schema` shows `PASS` against it.
- **This project's native local-dev Postgres role lacks `CREATEDB`** —
  by design/pre-existing, not a defect, but it means migration/
  verifier tests only run for real locally when explicitly pointed at
  a Postgres that has it (documented, not hidden — see `docs/
  migrations.md`).
- **No monitoring is actually live** — Sentry integration is code-
  complete and tested but inert without a real `SENTRY_DSN`; no
  alerts, dashboards, or incident-response process exist outside the
  specification in `docs/monitoring.md`.
- **Resolved for the frontend, still open for the backend**: the
  frontend's actual hosting platform is Vercel (discovered, not chosen,
  during this round — see prompt 6's correction) and now has the
  matching adapter (`adapter-vercel`). The backend still has no hosting
  platform beyond a working `Dockerfile`/`docker-compose.yml` — no
  actual production place it runs. Log retention and real alerting
  infrastructure still depend on that being decided.
- **The Vercel `adapter-vercel` switch is not independently
  re-verified against a real Vercel deployment from this environment**
  — no Vercel CLI credentials available here. The build output shape is
  confirmed correct (`.vercel/output/` matches Build Output API v3);
  an actual deployed-and-working check needs either those credentials
  or the repository owner checking the next PR's Vercel preview
  directly.
- **The `version` column's increment is now structurally enforced**
  (resolved this round, prompt 4) — no longer a risk, listed here only
  to mark it closed relative to the previous round's report.

No core requirement from this round's `prompts.txt` was left as a TODO
— every one of the 7 prompts has either a completed, tested
implementation, or (prompts 2 and the GitHub-evidence portions of 1/7)
an explicit, specific statement of exactly what remains and why it
wasn't done unilaterally.
