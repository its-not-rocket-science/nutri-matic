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

## Minimal production checklist

1. Set `JWT_SECRET` to a real, private, randomly-generated value — never
   reuse the value in `docker-compose.yml` (that one's committed to source
   control and is dev-only by design).
2. Set `APP_ENV=production` so a missing `JWT_SECRET` fails startup loudly
   instead of silently degrading auth security.
3. Set `CORS_ORIGINS` to your actual frontend origin(s).
4. Point `DATABASE_URL` at a real, backed-up Postgres instance — the app
   only runs `Base.metadata.create_all()` on startup (creates missing
   tables; does not migrate existing ones), so schema changes to existing
   tables need a manual migration, not just a redeploy.
5. Serve the frontend (`frontend/`) as a static SvelteKit build; it talks
   to the backend over `VITE_API_URL` (see `frontend/.env`).
6. Pick a real SvelteKit adapter before deploying. `frontend/svelte.config.js`
   currently uses `@sveltejs/adapter-auto`, which only auto-detects known
   platforms (Vercel, Netlify, Cloudflare) at build time — `npm run build`
   prints "Could not detect a supported production environment" as-is.
   Swap in `@sveltejs/adapter-node` (Docker/VM deploys) or the adapter for
   whichever platform you're actually targeting.

## Manual migrations needed on an existing (pre-this-session) database

`Base.metadata.create_all()` creates missing tables but never alters or
indexes existing ones (point 4 above). A fresh database gets all of this
automatically; a database that already existed before this round of work
needs these run by hand once:

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
```

## What's deliberately not covered here

Refresh tokens, per-tier session limits, and shorter-lived access tokens
are a live design question, not an oversight — see
`docs/auth-model-review.md` for the reasoning as of this app's current
scale. Revisit that doc before assuming the current 7-day access-token-only
model is wrong.
