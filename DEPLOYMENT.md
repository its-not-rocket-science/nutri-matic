# Deployment

This covers what's required to run the backend outside `docker compose up`
(the default dev setup, which already has safe defaults for everything
below). Read this before deploying anywhere the JWT secret or CORS origin
matters — i.e. anywhere that isn't your own laptop.

## Required environment variables

| Variable | Required in production | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Yes | `postgresql://nutrimatic:nutrimatic@localhost:5433/nutrimatic` | Postgres connection string. The dev default only works against the bundled `docker-compose.yml` Postgres container. |
| `JWT_SECRET` | Yes (enforced) | `dev-secret-change-me` | Signs auth tokens. The default is a fixed, public string committed to source — anyone can read it and forge a token for any user id. Generate a real one: `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `APP_ENV` | Yes — set to `production` | `development` | When `production`, the app refuses to start if `JWT_SECRET` isn't explicitly set, rather than silently falling back to the public dev value (see `backend/app/auth.py::_resolve_jwt_secret`). This is the enforcement mechanism, not just documentation — set it. |
| `CORS_ORIGINS` | Yes | `http://localhost:5173` | Comma-separated list of frontend origins allowed to call the API (e.g. `https://app.example.com,https://staging.example.com`). |
| `DEMO_RATE_LIMIT_PER_IP` / `DEMO_RATE_LIMIT_PER_IP_WINDOW_SECONDS` | No | `5` / `3600` | Per-IP cap on `POST /api/auth/demo`. See `docs/rate-limiting.md` — in-memory, per-process, resets on restart. |
| `DEMO_RATE_LIMIT_GLOBAL` / `DEMO_RATE_LIMIT_GLOBAL_WINDOW_SECONDS` | No | `300` / `3600` | Global circuit breaker on total demo-account creation. Same doc — becomes `limit × instance count` if the backend is ever scaled horizontally. |

## Minimal production checklist

1. Set `JWT_SECRET` to a real, private, randomly-generated value — never
   reuse the value in `docker-compose.yml` (that one's committed to source
   control and is dev-only by design).
2. Set `APP_ENV=production` so a missing `JWT_SECRET` fails startup loudly
   instead of silently degrading auth security.
3. Set `CORS_ORIGINS` to your actual frontend origin(s).
4. Point `DATABASE_URL` at a real, backed-up Postgres instance and run
   the Alembic migration workflow in `docs/migrations.md` — schema
   creation and evolution is Alembic's job now, not a redeploy alone.
   **Every existing database needs a one-time `alembic stamp
   aac138c38096` before its first Alembic-enabled deploy** — see that
   doc for exactly why and how.
5. Build with `@sveltejs/adapter-vercel` (operational-hardening prompt
   6 — resolved; this repo has a live Vercel project already connected
   via GitHub, so this is the adapter that actually matches current
   hosting, not a guess). It talks to the backend over `VITE_API_URL`,
   baked in at build time — set per-environment in the Vercel project's
   own dashboard, not this repo's `.env`. Production is live at
   **https://nutri-matic.vercel.app/**. See
   `docs/frontend-deployment.md` for the build command, Vercel project
   configuration, and the smoke tests this was verified against.

## Deployment checklist (production-hardening prompt 4)

The "Minimal production checklist" above is what a first deploy needs.
This is what every deploy that touches the database or ships a schema
change should walk through, in order.

**1. Backups**
- Confirm automated Postgres backups are configured and recent (point-
  in-time recovery is ideal; at minimum, a scheduled `pg_dump`).
- Take a manual backup immediately before this deploy regardless —
  automated backup timing won't necessarily line up with the exact
  moment you're about to run a migration, and a fresh, known-good
  restore point costs little.

**2. Migrations**
- If this is the database's first Alembic-enabled deploy, confirm it's
  been stamped: `alembic current` should show `aac138c38096` (or later)
  — if it shows nothing, **run `python -m app.verify_pre_alembic_schema`
  first and confirm PASS** before stamping (see `docs/migrations.md` —
  `stamp` doesn't check anything itself, it just records a claim; this
  repo's own `docker-compose` database was stamped without this check
  before the tool existed and turned out not to actually match the
  baseline — a real, not hypothetical, mistake this step exists to
  prevent repeating). Only once it passes, run `alembic stamp
  aac138c38096` (running `upgrade head` on an unstamped pre-existing
  database fails loudly, which is correct, but don't let that be the
  first time you discover it needed stamping).
- Where practical, run `alembic upgrade head` against a staging copy of
  the database first.
- In production, `alembic upgrade head` runs automatically before
  `uvicorn` starts (`backend/Dockerfile`'s `CMD`) — after the deploy,
  confirm it actually reached head: `alembic current` should match
  `alembic heads` exactly. A container that's serving traffic on an
  old revision (migration silently failed but the process kept running
  some other way) is worse than one that failed to start.

**3. Schema verification**
- Spot-check the columns/constraints the deploy's migrations touch —
  `\d <table>` in `psql`, or query `information_schema.columns` — matches
  what the migration claims (nullability in particular; a migration that
  claims to set `NOT NULL` but didn't reach that step is a silent bug).
- On a from-scratch database, confirm the `pg_trgm` extension exists
  (`\dx` in `psql`) — the baseline migration creates it, but it's cheap
  to double check on a deploy that matters.

**4. Smoke tests** (after the new version is serving traffic, before
   declaring the deploy done)
- `GET /api/recommendations/ingredients?entry_date=<today>` for a real
  or throwaway account returns `200` with a well-formed body (exercises
  the DB connection, the profile/eligibility path, and — if the account
  has any diary entries — the `DiaryEntry.updated_at`/`version` columns
  most recently added).
- Full substitution-apply round trip: log a recipe to the diary, fetch
  `GET /api/recommendations/substitutions?entry_id=...`, apply the top
  suggestion via `POST /api/recommendations/substitutions/apply`, and
  confirm the diary entry's `recipe_id` changed and `version`
  incremented by exactly 1. This is the one write path recommendation
  suggestions have, and the one most recently restructured (production-
  hardening prompt 3) — worth a real end-to-end check, not just a
  reachability ping.
- Register a throwaway account end-to-end (register → log a diary
  entry → load the diary page) to confirm the frontend can actually
  reach the backend (`VITE_API_URL` correctly pointed, `CORS_ORIGINS`
  includes the frontend's real deployed origin — a CORS misconfiguration
  won't show up in a backend-only health check).

**5. Rollback**
- **Application code**: redeploying the previous release is safe as
  long as its code tolerates the *current* (possibly newer) schema —
  true for every migration in this repo so far, since each only adds
  nullable-then-backfilled or safely-defaulted columns, never removes
  or repurposes one. Check the specific migrations involved before
  assuming this holds for a future one.
- **Database**: prefer `alembic downgrade -1` for undoing only the most
  recent migration, and only alongside rolling back the application
  code that depends on it — see `docs/migrations.md`'s own rollback
  section for two specific hazards already on record: the `updated_at`
  migration's `downgrade()` genuinely loses data (drops the column), and
  the baseline's `downgrade()` drops every table in the application and
  must never run against a database with real data. For anything beyond
  the single most recent migration, restore from the backup taken in
  step 1 rather than chaining `alembic downgrade` calls.

**6. Monitoring**
- Watch error rates on `/api/recommendations/*`, `/api/diary`, and
  `/api/meal-plan` specifically for the first hour after any deploy that
  touches the database — these are the endpoints most recently changed.
- Watch migration duration and lock time during the `alembic upgrade
  head` step itself. The `version` column migration is a fast,
  metadata-only operation (constant default, no table rewrite — see its
  own docstring); the `updated_at` migration backfills every existing
  row, so its duration scales with `diary_entries`/`meal_plan_entries`
  row counts and is the one worth watching on a database with real
  usage history.
- **No monitoring/alerting stack (Sentry, Datadog, or equivalent) is
  configured in this repository** — this is a documented gap, not a
  claim of coverage. See the "remaining operational risks" in
  `docs/production-hardening.md`'s final validation report.

## Historical manual migrations (frozen — superseded by Alembic)

**This section is a frozen historical record, not a live process.** Every
schema change from production-hardening prompt 1 onward is an Alembic
migration under `backend/migrations/versions/` — see `docs/migrations.md`
for the current workflow. The SQL below predates Alembic and is kept only
so a database that somehow missed one of these along the way (this list
was compiled by hand, over many rounds of work, before migrations
existed to enforce it) has a reference for what it might still be
missing; Alembic's own baseline migration (`aac138c38096`) already
captures the end state of everything below for any database being
migrated fresh.

```sql
-- users.plan / users.plan_expires_at (Phase 3.1 entitlements)
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR NOT NULL DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMPTZ;

-- food_nutrients query performance (Phase 5.2 technical audit — see
-- docs/production-readiness-audit.md; measured 137ms -> 0.2ms on a
-- 222k-row table for the gap-suggestions/meal-optimize query path)
CREATE INDEX IF NOT EXISTS ix_food_nutrients_key_amount
    ON food_nutrients (nutrient_key, amount_per_100g);

-- recipes.is_public / collections.is_public (Phase 4 stock-recipe feature —
-- visible to every user regardless of ownership, still owner-only to edit)
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE collections ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;

-- users.currency (Phase 4 — ISO 4217 code overriding the browser locale's
-- implied currency for price/cost displays; null means "follow the browser")
ALTER TABLE users ADD COLUMN IF NOT EXISTS currency VARCHAR;

-- users.goal (Phase 4 — onboarding goal, used to personalize the dashboard;
-- null means "not set", distinct from any specific goal value)
ALTER TABLE users ADD COLUMN IF NOT EXISTS goal VARCHAR;

-- recipes.source_url / recipes.method (optional source-link + free-text
-- cooking instructions) — previously missing from this list entirely;
-- found and added while migrating a real pre-existing database that had
-- never had it applied.
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS source_url VARCHAR;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS method VARCHAR;

-- Stock recipe library (see docs/stock-recipes.md) — system-account
-- ownership, per-recipe/per-ingredient provenance, and robustness ratings
-- for the curated recipe library imported/maintained by
-- `python -m app.stock_recipes`.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE recipes ADD COLUMN IF NOT EXISTS import_slug VARCHAR;
CREATE UNIQUE INDEX IF NOT EXISTS ix_recipes_import_slug ON recipes (import_slug);
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS source_name VARCHAR;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS source_licence VARCHAR;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS parser_version VARCHAR;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS content_fingerprint VARCHAR;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS stock_status VARCHAR;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS match_coverage_lines DOUBLE PRECISION;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS match_coverage_mass DOUBLE PRECISION;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS unresolved_ingredients JSON;
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS educational_note VARCHAR;

ALTER TABLE collection_recipes ADD COLUMN IF NOT EXISTS assignment_source VARCHAR;
ALTER TABLE collection_recipes ADD COLUMN IF NOT EXISTS assignment_confidence DOUBLE PRECISION;
ALTER TABLE collection_recipes ADD COLUMN IF NOT EXISTS assignment_reason VARCHAR;
ALTER TABLE collection_recipes ADD COLUMN IF NOT EXISTS approval_status VARCHAR NOT NULL DEFAULT 'approved';

-- recipe_ingredient_provenance / robustness_results are brand new tables —
-- Base.metadata.create_all() creates those automatically on next backend
-- startup, same as any other new table. No ALTER TABLE needed for them.

-- Household profiles (multiple individuals per account) — profiles is a
-- brand new table, created automatically by create_all(); every other
-- personal-data table gets a nullable profile_id alongside its existing
-- user_id (kept, not dropped — see models.Profile's docstring). Three of
-- these tables have a uniqueness constraint that was scoped to user_id
-- alone and must move to profile_id, or two profiles under one account
-- couldn't each have their own row for the same date/tag.
--
-- Rollout is two steps, in order:
--   1. Deploy this code + run the block below.
--   2. Run `python -m app.migrate_profiles` (idempotent, re-runnable) and
--      confirm it reports zero remaining NULL profile_id rows before
--      relying on any profile_id-scoped endpoint.
ALTER TABLE dietary_constraints ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE diary_entries ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE diary_snapshots ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE weight_logs ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE meal_plan_entries ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE meal_plan_templates ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE diary_meal_templates ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);
ALTER TABLE saved_filter_presets ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id);

-- uq_dietary_constraint / uq_diary_snapshot_user_date / uq_weight_log_user_date
-- move from (user_id, ...) to (profile_id, ...) — Postgres allows any
-- number of NULLs in a unique constraint, so this is safe to run before
-- migrate_profiles.py backfills profile_id (existing NULL rows don't
-- conflict with each other in the meantime).
ALTER TABLE dietary_constraints DROP CONSTRAINT IF EXISTS uq_dietary_constraint;
ALTER TABLE dietary_constraints ADD CONSTRAINT uq_dietary_constraint UNIQUE (profile_id, category, tag);
ALTER TABLE diary_snapshots DROP CONSTRAINT IF EXISTS uq_diary_snapshot_user_date;
ALTER TABLE diary_snapshots ADD CONSTRAINT uq_diary_snapshot_user_date UNIQUE (profile_id, entry_date);
ALTER TABLE weight_logs DROP CONSTRAINT IF EXISTS uq_weight_log_user_date;
ALTER TABLE weight_logs ADD CONSTRAINT uq_weight_log_user_date UNIQUE (profile_id, log_date);

-- robustness_results: prompt section 4 replaces "one row per recipe,
-- upserted in place on every re-analysis" with immutable history rows
-- (is_latest flags the one current result). A database whose
-- robustness_results table predates this change needs the old implicit
-- "one row per recipe_id" uniqueness relaxed and the new flag column
-- added — existing rows default to is_latest=TRUE, which is correct
-- (there was only ever one row per recipe before this).
ALTER TABLE robustness_results ADD COLUMN IF NOT EXISTS is_latest BOOLEAN NOT NULL DEFAULT TRUE;
-- drops whatever unique constraint enforced that "one per recipe_id" —
-- name depends on how the original table was created; check
-- \d robustness_results and adjust if this particular name doesn't match:
ALTER TABLE robustness_results DROP CONSTRAINT IF EXISTS robustness_results_recipe_id_key;
CREATE INDEX IF NOT EXISTS ix_robustness_results_recipe_id_is_latest ON robustness_results (recipe_id, is_latest);
-- replaces that dropped uniqueness with the correct one: at most one
-- is_latest=TRUE row per recipe (not "at most one row per recipe" at
-- all) — a partial unique index, supported by Postgres and by SQLite
-- 3.8.0+ (what the test suite runs against), so it's enforced by the
-- database itself, not just by _upsert_robustness's application code.
CREATE UNIQUE INDEX IF NOT EXISTS uq_robustness_results_recipe_id_latest
    ON robustness_results (recipe_id) WHERE is_latest;

-- recipe_ingredient_provenance.match_relationship (prompt section 8) —
-- which AliasRelationship (exact/regional_equivalent/close_analogue/
-- category_proxy/reviewed_substitution) an alias/manual_review match came
-- from; null for canonical/fuzzy matches and pre-existing rows.
ALTER TABLE recipe_ingredient_provenance ADD COLUMN IF NOT EXISTS match_relationship VARCHAR;

-- recipe_ingredient_provenance: mapping-quality provenance fields
-- (prompt section 5) — rationale text, which fdc_id/food_id (if any) an
-- alias/reviewed match was pinned to regardless of whether it actually
-- resolved, whether resolution had to fall back to the description
-- search, and any target-validation warning. All null for canonical/
-- fuzzy matches, an unresolved ingredient, or a pre-existing row.
ALTER TABLE recipe_ingredient_provenance ADD COLUMN IF NOT EXISTS match_rationale VARCHAR;
ALTER TABLE recipe_ingredient_provenance ADD COLUMN IF NOT EXISTS match_preferred_fdc_id INTEGER;
ALTER TABLE recipe_ingredient_provenance ADD COLUMN IF NOT EXISTS match_preferred_food_id INTEGER;
ALTER TABLE recipe_ingredient_provenance ADD COLUMN IF NOT EXISTS match_used_fallback BOOLEAN;
ALTER TABLE recipe_ingredient_provenance ADD COLUMN IF NOT EXISTS match_validation_warning VARCHAR;
```

## What's deliberately not covered here

Refresh tokens, per-tier session limits, and shorter-lived access tokens
are a live design question, not an oversight — see
`docs/auth-model-review.md` for the reasoning as of this app's current
scale. Revisit that doc before assuming the current 7-day access-token-only
model is wrong.
