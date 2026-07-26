# Demo account lifecycle

Public-launch hardening prompt 2. A demo account (`POST /api/auth/demo`,
see `app/demo_data.py`) is a full, real account with no verification —
without an enforced lifetime it lives forever. This gives every demo
account a finite lifetime, rejects an expired one at auth time, and adds
a safe, batched, human-gated purge job.

## Model

`User.is_demo` (bool, default false) and `User.expires_at` (nullable,
timezone-aware) — see `app/models.py`. `demo_data.create_demo_account`
sets both at creation: `is_demo=True`, `expires_at = created_at +
DEMO_LIFETIME_HOURS`.

| Env var | Default | Purpose |
|---|---|---|
| `DEMO_LIFETIME_HOURS` | `24` | How long a demo account lives from creation. Matches the existing 24h JWT access-token expiry (`app/auth.py`) by default, so in the common case a demo session's token and its account expire together. |

## Expiry enforcement

`app/demo_lifecycle.py::is_expired_demo(user)` is the single source of
truth. `auth.get_current_user` rejects an expired demo with the exact
same `401 "Invalid or expired token"` any other invalid/expired token
gets — no distinguishing detail. `auth.get_optional_current_user`
treats an expired demo as anonymous, same as any other expired token on
an optional-auth endpoint. An ordinary (non-demo) user is never affected
— `is_expired_demo` returns `False` immediately whenever `is_demo` is
false, regardless of `expires_at` (which is always null for them).

## The migration (92158621e2f3) is deliberately mechanical

It only adds the two columns; every existing row (real users **and**
any pre-existing demo accounts from manual testing — production already
has some, per this round's EXECUTION SAFETY REQUIREMENTS) gets
`is_demo=false`. It does not attempt to identify pre-existing demo
accounts itself — see the migration's own docstring for why folding a
guess into the migration would be wrong, and `app/backfill_demo_flag.py`
below for the actual, separate, human-reviewed mechanism. This is the
same two-step shape this repo already uses for `app/migrate_profiles.py`.

## Identifying pre-existing demo accounts — `app/backfill_demo_flag.py`

```
python -m app.backfill_demo_flag              # dry-run (default)
python -m app.backfill_demo_flag --apply       # marks confirmed matches
```

Heuristic (both signals required, not either alone):

1. Email under `demo_data.DEMO_EMAIL_DOMAIN` (`demo.nutrimatic.local`).
2. `sex`/`activity_level`/`weight_kg`/`height_cm` exactly match
   `demo_data.py`'s hard-coded seed values (`"female"`/`"moderate"`/
   `65.0`/`168.0`).

Signal 1 alone is not proof — `register()` never validates or restricts
the email domain, so nothing stops a real registration from choosing an
email under this domain. Signal 2 alone is coincidental. Both together,
on an account nobody has since edited every one of those four fields to
coincidentally match, is about as strong as an automated heuristic gets
without a human just reading the list — which is exactly what's still
required before `--apply` touches production (see the SAFETY GATE
below). A row matching only the email is reported separately as
"ambiguous — not auto-marked" for manual investigation, never guessed
either way.

## Purge — `app/demo_purge.py`

```
python -m app.demo_purge report                     # counts only
python -m app.demo_purge purge                       # dry-run (default)
python -m app.demo_purge purge --apply                # actually deletes
python -m app.demo_purge purge --apply --batch-size 200
```

- **Batched** by user id (default 100/batch) — each batch is its own
  transaction, so a large backlog never holds one long lock. A failure
  partway through leaves earlier batches purged and the rest untouched;
  safe to just re-run.
- **Idempotent** — already-deleted users simply aren't selected again.
  Safe under concurrent/repeated runs: a delete-by-id-list matching zero
  rows (because another run already removed them) is a no-op, not an
  error.
- **Dry-run reports every matching account** (`user_id` + `email`), not
  just a count — the whole point is a human being able to review
  exactly what would be deleted.
- **Deletion order.** No FK to `users.id` in this schema declares `ON
  DELETE CASCADE` (checked against every table in `app/models.py`), so
  every dependent row is deleted in explicit application-code order
  before the row it depends on:

  1. `recipe_ingredient_provenance` (via owned recipes' ingredients)
  2. `recipe_ingredients` (owned recipes)
  3. `recipe_ratings`, `recipe_comments` (owned recipes OR authored by this user)
  4. `recipe_tags` (owned recipes)
  5. `recipe_shares` (owned recipes OR shared *to* this user)
  6. `collection_recipes` (owned recipes OR owned collections)
  7. `robustness_results` (owned recipes)
  8. `recipes`, then `collections`
  9. `meal_plan_template_entries`, then `meal_plan_templates`
  10. `diary_meal_template_items`, then `diary_meal_templates`
  11. `diary_entries`, `diary_snapshots`, `meal_plan_entries`,
      `weight_logs`, `food_prices`, `saved_filter_presets`,
      `dietary_constraints`, `api_keys`
  12. `clinician_client_links`, `clinician_notes` (either side of the link)
  13. `profiles`
  14. `users`

  A demo account is a full account and can touch any feature via the
  API before expiring — this covers every table that can reference one,
  not just what `demo_data.py` seeds. Regression-tested in
  `tests/test_demo_purge.py::test_purge_removes_every_dependent_row_across_the_full_schema`,
  which builds one row in every table above and confirms the purge
  clears all of it while a control (non-demo) user's equivalent rows
  survive untouched.

### SAFETY GATE — read before ever running `--apply` against production

Production already contains real demo accounts from manual testing.
**Never run `purge --apply` (or `backfill_demo_flag --apply`) against
production without first running the dry-run form and having a human
review the exact account list it prints.** This tooling has no way to
skip that review — it only refuses to delete anything without `--apply`
being passed explicitly. See prompts.txt's EXECUTION SAFETY
REQUIREMENTS for the full text of this constraint.

As of this writing, neither the migration rehearsal (upgrade/downgrade
against a **restored copy of actual production data**) nor the
backfill/purge dry-run against **actual production** has been performed
— this session has no production database credentials or SSH access
(see the EXECUTION SAFETY REQUIREMENTS' credential-scoping check). The
migration and purge logic have been verified against a real, throwaway
Postgres instance (`tests/test_migrations.py`, `tests/test_demo_purge.py`)
and against the full backend test suite, which is necessary but **not**
a substitute for rehearsing against a real copy of production's actual
data and reviewing the actual production dry-run output — both of those
steps still need to happen, by whoever has that access, before this is
applied to production.

## Reporting — `app/demo_purge.py report`

The "emergency operational command": prints total/active/expired demo
account counts, independent of the purge job itself.

## Scheduling — `.github/workflows/demo-purge.yml`

GitHub Actions is the only scheduling mechanism this repo already has
(see `ci.yml`) — reused rather than inventing a new one. **Not active
out of the box**: the job checks for a `PRODUCTION_DATABASE_URL` secret
and no-ops with a log message if it's unset; adding that secret is a
repo-admin action outside what a workflow-file change should do
unilaterally. The daily schedule always runs in dry-run mode
(`github.event.inputs.apply` is unset for a `schedule` trigger) — only a
manually triggered `workflow_dispatch` run with `apply` checked can
actually delete anything. Routine reporting can run unattended; a real
deletion always requires someone to explicitly trigger it.

To actually activate scheduled dry-run reporting:
1. Add the `PRODUCTION_DATABASE_URL` secret (Settings → Secrets →
   Actions) — pointed at a role with read access at minimum.
2. Confirm a GitHub-hosted runner can actually reach it — not
   guaranteed if production Postgres is only reachable from a private
   network, which is a common setup this repo doesn't verify.
3. Only after a human has run at least one manual
   `python -m app.demo_purge purge` dry-run against production and
   reviewed it, consider a manual `workflow_dispatch` run with `apply`
   checked. Do not flip this to routine unattended `--apply` runs
   without separately deciding that's wanted — this document does not
   recommend that as a next step.
