# Database migrations

Production-hardening prompt 1. This app used to rely entirely on
`Base.metadata.create_all()` at startup for schema creation, plus a long
manually-run `ALTER TABLE` block in `DEPLOYMENT.md` for every change to
an *existing* table (`create_all()` only ever creates missing tables —
it never alters or adds columns to ones that already exist). That manual
block is now frozen as a historical record; every schema change from
this point on is an Alembic migration, applied with `alembic upgrade
head`, never a hand-run `ALTER TABLE` and never a redeploy alone.

## Why a "baseline" migration exists

This project adopted Alembic mid-project, not at day one, so there's no
migration history for the ~28 tables that already existed. The standard
resolution (and what's used here): one **baseline** migration
(`aac138c38096_baseline.py`) captures the entire schema as it stood
immediately before Alembic was introduced — every table, index, and
constraint `create_all()` had ever been relied on to build. It does
**not** include `diary_entries.updated_at` / `meal_plan_entries.
updated_at`, since those were added in the same work that introduced
Alembic and no real database had them yet (`create_all()` never adds a
column to an existing table, so they were pure schema drift until this
migration exists to fix it). A second migration
(`dba3649596f0_add_diary_and_meal_plan_entry_updated_at.py`) adds those
two columns safely (prompt 2 — see below).

This means the baseline is handled **differently** depending on whether
a database is brand new or already exists:

- **Brand new database** (fresh deploy, CI, a developer's first local
  setup): `alembic upgrade head` runs the baseline for real — it
  executes the same `CREATE TABLE` statements `create_all()` used to,
  then applies the `updated_at` migration on top (a no-op backfill,
  since there are no rows yet).
- **Existing database** (anything that's already been running this
  app — including production, and this repo's own `docker-compose`
  Postgres and any local dev database): the tables already exist, so
  running the baseline's `upgrade()` for real would fail immediately
  (`relation "foods" already exists"). Instead, tell Alembic the
  database is already at that point without running the DDL:

  ```bash
  alembic stamp aac138c38096
  ```

  This writes `aac138c38096` into a new `alembic_version` table and
  does nothing else — no DDL runs. **This is a required, one-time,
  manual step for every existing database before it can ever run
  `alembic upgrade head`.** There is no safe way to automate detecting
  "this database predates Alembic" from inside a migration, so this
  isn't attempted — it fails loudly (relation-already-exists) instead
  of guessing, which is the correct failure mode for a schema
  operation.

  `stamp` itself doesn't check that the database *actually* matches the
  baseline it's being told it's at — a database missing a table, column,
  index, or the `pg_trgm` extension (because a historical manual
  migration from `DEPLOYMENT.md`'s frozen list was never run against it)
  would get stamped anyway, silently. **Run the read-only verifier
  first, every time, before stamping any existing database**:

  ```bash
  python -m app.verify_pre_alembic_schema
  # or, for a database other than DATABASE_URL's default:
  python -m app.verify_pre_alembic_schema --database-url postgresql://...
  ```

  `PASS` means safe to stamp. `FAIL` lists exactly what's missing or
  incompatible — do not stamp until every issue is resolved (bring the
  database up to the baseline schema by hand first, using
  `DEPLOYMENT.md`'s frozen historical migration block as a reference for
  what each missing piece was for). This tool is read-only — it never
  modifies the database, and never stamps or upgrades anything itself.

  Immediately after stamping (and only once the verifier passes), run
  `alembic upgrade head` — this applies every migration *after* the
  baseline for real, starting with the `updated_at` backfill.

## Local development commands

From `backend/`, with `DATABASE_URL` pointing at your local Postgres
(the same variable `app/database.py` already reads):

```bash
# One-time, only if this database already has tables (was ever run
# against a pre-Alembic version of this app) — verify first, always:
python -m app.verify_pre_alembic_schema
alembic stamp aac138c38096

# Every time after that, including on a genuinely fresh database:
alembic upgrade head

# Check what revision a database is currently at:
alembic current

# See pending migrations without applying them:
alembic history
```

`docker compose up` now runs `alembic upgrade head` automatically before
starting the backend (see `backend/Dockerfile`) — safe on every
container start once the one-time `stamp` above has been done, since
`upgrade head` is a no-op when already current.

**This repo's own `docker-compose` Postgres was stamped without running
the verifier first, before the verifier existed, and it turned out not
to actually match the baseline** — real drift, not hypothetical: 29
missing objects, including the entire `medical_recommendation_
acknowledgements` table, every table's `profile_id` column, and several
`recipe_ingredient_provenance` columns. Its `alembic_version` currently
claims `d7819c868cf4` (head) but the underlying schema doesn't back that
up. Do not treat that database as a working example to copy — it needs
the missing objects added by hand (see `DEPLOYMENT.md`'s frozen
historical migration block for what each one was for) before it can be
trusted, and `python -m app.verify_pre_alembic_schema` should show PASS
against the baseline before doing so was ever attempted, which is
exactly the mistake this tool now exists to prevent happening again.

## Production commands

Same two commands, run from wherever you deploy (a release step, a
one-off task in your platform, etc.) with `DATABASE_URL` pointing at the
real production database:

```bash
# Once, before the first Alembic-enabled deploy — verify first, always:
python -m app.verify_pre_alembic_schema
alembic stamp aac138c38096

# On every deploy from then on, before the new app version starts
# serving traffic:
alembic upgrade head
```

If your deployment platform runs the container's `CMD` directly (as
`docker-compose.yml` does), the `alembic upgrade head && uvicorn ...`
chain in `backend/Dockerfile` handles the second command automatically
— you only ever need to run `stamp` by hand, and only once, ever, for
each pre-existing database.

## Writing a new migration

```bash
# Preferred — let Alembic diff the live models against the database:
alembic revision --autogenerate -m "short description"

# Always review the generated file before committing it. Autogenerate
# does not reliably detect: column type changes, table/column renames
# (it will emit a drop+add, losing data — rewrite these by hand as an
# alter/rename), or check constraints in some dialects. It also can't
# know your data-safety intent — see the updated_at migration
# (dba3649596f0) for the nullable→backfill→NOT NULL pattern required
# any time a NOT NULL column is added to a table that might have rows.
```

Every new model change from now on needs a matching migration in the
same commit — `docs/nutrient-gap-recommendations-hardening.md` and
similar feature docs no longer need their own "manual migrations
needed" section; that pattern is retired as of this file.

## Rollback

Each migration has a `downgrade()`. To roll back the most recent one:

```bash
alembic downgrade -1
```

**`dba3649596f0` (the `updated_at` backfill) is not fully reversible
without data loss**: its `downgrade()` drops the `updated_at` column
outright, which is correct (there's nothing else sensible it could do),
but any real mutation history captured in that column since the
migration ran is gone once you downgrade — only roll it back if you're
also rolling back the application code that reads `updated_at` (the
substitution-apply endpoint's staleness check), since that code would
otherwise immediately break against a database missing the column it
expects.

**`096f80b058ab` (clinician invite by email) deletes unregistered
invites on downgrade.** Re-tightening `clinician_client_links.
client_user_id` back to `NOT NULL` can't coexist with any row still
sitting at `client_user_id IS NULL` (an invite nobody has registered
against yet), so `downgrade()` deletes those rows outright rather than
failing the `ALTER` — a real, if narrow, loss of pending-invite state,
same tradeoff as `dba3649596f0` below.

**The baseline (`aac138c38096`) should never actually be downgraded on
a real database.** Its `downgrade()` drops every table this app has —
correct for local development iteration (Alembic needs *a* downgrade
path to exist for tooling to work sanely), catastrophic anywhere real
data lives. If you ever need to undo the baseline in production, that's
a "restore from backup," not an `alembic downgrade` — see
`DEPLOYMENT.md`'s deployment checklist.

## Testing

`tests/test_migrations.py` runs the full chain (`stamp`-equivalent from
empty, `upgrade head`, and the backfill's nullable-then-NOT-NULL
behaviour against rows inserted between steps) against a real, throwaway
Postgres database — not SQLite, since the whole point is verifying real
DDL behaviour (including the Postgres-specific partial unique index and
`pg_trgm` extension) that SQLite's looser type/constraint handling could
hide a real bug behind. This test is skipped automatically unless the
connecting Postgres role has `CREATEDB` (a plain local install's
`nutrimatic` role may be reachable but not have it) — CI's Postgres
service always grants this to its own user, so it always runs there
(see `.github/workflows/ci.yml`).

`tests/test_verify_pre_alembic_schema.py` covers the pre-stamp verifier
itself the same way: an exact baseline schema passes cleanly, and each
of a missing table, missing column, wrong column type, missing unique
index, and missing `pg_trgm` extension is independently confirmed to
fail with a specific, relevant message — plus credential redaction and
correct process exit codes. Same skip/CI-hard-failure behaviour as
`test_migrations.py`.
