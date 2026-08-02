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
| `DEMO_PURGE_GRACE_PERIOD_HOURS` | `0.5` | Operational-hardening prompt 1: an account is eligible for purge only once it's been expired for at least this long, not at the exact expiry instant — see `app/demo_purge.py`'s `DEFAULT_GRACE_PERIOD_HOURS` docstring for the rationale (clock-skew buffer, small investigation window). Auth already blocks an expired demo immediately regardless of this — it only delays *deletion*. |

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
python -m app.demo_purge purge --apply --max-batches 50 --grace-period-hours 0.5   # both shown at their defaults
```

- **Batched** by user id (default 100/batch) — each batch is its own
  transaction, so a large backlog never holds one long lock. A failure
  partway through leaves earlier batches purged and the rest untouched;
  safe to just re-run.
- **Bounded per run** (`--max-batches`, default 50 — operational-
  hardening prompt 1 requirement 8): a run stops after this many batches
  regardless of backlog size, rather than potentially running for an
  unbounded time. `PurgeReport.hit_batch_limit`/the CLI's own "N expired
  account(s) still remain" line say so explicitly when it happens — the
  next scheduled run picks up automatically (nothing about batching
  assumes one run clears the whole backlog; see Idempotent below).
- **Grace period** (`--grace-period-hours`, default 0.5 — requirement
  7): an account becomes eligible only once expired for at least this
  long, not at the exact expiry instant. See the env var table above.
- **Idempotent** — already-deleted users simply aren't selected again.
  Safe under concurrent/repeated runs: a delete-by-id-list matching zero
  rows (because another run already removed them) is a no-op, not an
  error.
- **Dry-run reports every matching account** (`user_id` + `email`), not
  just a count — the whole point is a human being able to review
  exactly what would be deleted.
- **One structured summary log per run** (`demo_purge_run_summary`,
  logger `app.demo` — requirement 9): `scanned`/`eligible`/`deleted`/
  `failed`/`hit_batch_limit`/`remaining_expired`/`duration_seconds`.
  Counts only, never account emails — those stay in the dry-run
  console report above, a deliberately separate, human-review-only path
  (see the SAFETY GATE below for why that distinction matters). A
  mid-run failure logs `failed: true` with whatever was already
  committed still reflected in `deleted`, then re-raises — `main()`
  logs a second `demo_purge_failed` line and exits non-zero either way
  (requirement 10), so a failure is visible to both structured-log
  monitoring and GitHub Actions' own pass/fail status.
- **Deletion order.** No FK to `users.id` (or the tables hanging off a
  recipe/profile) in this schema declares `ON DELETE CASCADE` (checked
  against every table in `app/models.py`), so every dependent row is
  deleted in explicit application-code order before the row it depends
  on:

  1. `diary_entries`, `meal_plan_entries`, `meal_plan_template_entries`,
     `diary_meal_template_items` **referencing an owned recipe by
     `recipe_id`, regardless of who logged them** — a demo-owned recipe
     can be `is_public` or `RecipeShare`'d, so another real user can have
     their own diary/meal-plan/template entry pointing at it. These must
     go before the recipe delete or Postgres rejects it (a restrictive
     FK) and aborts the whole batch. This is the one place purging a
     demo account can remove a row belonging to a non-demo user — an
     accepted, unavoidable tradeoff: the alternative is an orphaned
     recipe with no owner, which isn't valid either (`Recipe.user_id` is
     `NOT NULL`). Caught by automated PR review, not written correctly
     the first time.
  2. `recipe_ingredient_provenance` (via owned recipes' ingredients)
  3. `recipe_ingredients` (owned recipes)
  4. `recipe_ratings`, `recipe_comments` (owned recipes OR authored by this user)
  5. `recipe_tags` (owned recipes)
  6. `recipe_shares` (owned recipes OR shared *to* this user)
  7. `collection_recipes` (owned recipes OR owned collections)
  8. `robustness_results` (owned recipes)
  9. `recipes`, then `collections`
  10. `meal_plan_template_entries`, then `meal_plan_templates` (this
      user's own templates — step 1 already cleared any cross-user
      entries referencing a now-deleted recipe)
  11. `diary_meal_template_items`, then `diary_meal_templates` (same note)
  12. `diary_entries`, `diary_snapshots`, `meal_plan_entries`,
      `weight_logs`, `food_prices`, `saved_filter_presets`,
      `dietary_constraints`, `api_keys`
  13. `clinician_client_links`, `clinician_notes` (either side of the link)
  14. `medical_recommendation_acknowledgements` (via this user's profiles
      — also caught by automated PR review; missing entirely would abort
      the profile delete below for any profile with one)
  15. `profiles`
  16. `users`

  A demo account is a full account and can touch any feature via the
  API before expiring — this covers every table that can reference one,
  not just what `demo_data.py` seeds. Regression-tested in
  `tests/test_demo_purge.py`: `test_purge_removes_every_dependent_row_across_the_full_schema`
  builds one row in every table above and confirms the purge clears all
  of it while a control (non-demo) user's equivalent rows survive
  untouched; `test_purge_clears_another_users_reference_to_a_demo_owned_recipe`
  and `test_purge_clears_medical_recommendation_acknowledgements_before_profile`
  cover the two gaps above specifically.

- **API-key auth also enforces expiry.** A demo account can create a
  public-API key (`POST /api/api-keys`) before it expires —
  `app/api_keys.py::get_api_key_user` checks `is_expired_demo` the same
  way the JWT session path does, so an expired demo can't keep using a
  key it created earlier. Also caught by automated PR review: this
  prompt's first pass only wired expiry into the JWT path
  (`auth.get_current_user`/`get_optional_current_user`), missing that
  `/api/v1/*` authenticates independently through a separate credential
  system.

### SAFETY GATE — read before ever running `--apply` against production

Production already contains real demo accounts from manual testing.
**Never run `purge --apply` (or `backfill_demo_flag --apply`) against
production without first running the dry-run form and having a human
review the exact account list it prints.** This tooling has no way to
skip that review — it only refuses to delete anything without `--apply`
being passed explicitly. See prompts.txt's EXECUTION SAFETY
REQUIREMENTS for the full text of this constraint.

This still applies with the scheduled workflow now running `--apply`
automatically every night (see Scheduling below) — the one-time human
dry-run review described here is what happens **before** scheduled
apply runs are ever turned on for the first time, not something that
happens per-run afterward. Once live, routine visibility comes from the
structured `demo_purge_run_summary`/`demo_purge_batch` log lines (see
Purge above) and GitHub Actions' own pass/fail status, not a human
reading an account list every night.

## Reporting — `app/demo_purge.py report`

The "emergency operational command": prints total/active/expired demo
account counts, independent of the purge job itself.

## Scheduling — `.github/workflows/demo-purge.yml`

GitHub Actions is the only scheduling mechanism this repo already has
(see `ci.yml`) — reused rather than inventing a new one.

**Runs over SSH via `docker compose exec`**, the same way
`deploy.yml`'s rehearse-migration job and `migrate-profiles.yml` reach
the server — production Postgres isn't directly reachable from a
GitHub-hosted runner, so this executes `python -m app.demo_purge purge
[--apply]` inside the already-running `backend` container rather than
connecting to the database directly. This replaced an earlier design
that used a raw `PRODUCTION_DATABASE_URL` secret from the runner — that
design was never actually reachable and is why, as of the previous
version of this document, scheduled purging had still never run for
real despite the workflow file existing.

**The scheduled (cron) run always applies** — `python -m app.demo_purge
purge --apply` — this is deliberate, not a bug: operational-hardening
prompt 1 asked for genuinely automatic deletion, not another
dry-run-only schedule. A manual `workflow_dispatch` run still defaults
to dry-run unless the `apply` box is explicitly checked.

**No `environment: production` approval gate on this job** — unlike
`migrate-profiles.yml`'s manual one-off, a required-reviewer gate on a
nightly schedule would mean clicking "approve" every night, which isn't
automatic. The real gate is server-side: `PROD_SSH_KEY` (the same
restricted deploy key `deploy.yml`/`migrate-profiles.yml` already use)
can only run the exact commands allowlisted in
`/root/deploy-allowed-commands.sh` on the server — until the two
`app.demo_purge purge` / `app.demo_purge purge --apply` entries are
added there (a one-time, human-reviewed authorisation, not a per-run
click), every invocation of this workflow is rejected by the server
itself with a non-zero exit, which shows as a failed (not silently
green) GitHub Actions run.

**Fails closed AND loud** if `PROD_SSH_KEY`/`PROD_SSH_HOST` aren't
configured — `exit 1` with an `::error::` annotation, not the previous
design's silent `exit 0`. No deletion happens either way; the
difference is that a missing/broken configuration now shows as a
failing scheduled job instead of a quietly-succeeding no-op that could
mask a broken pipeline for weeks.

**Concurrency-locked** (`concurrency: group: demo-purge-production`,
`cancel-in-progress: false`) — two runs never execute at once on
purpose, even though `purge_expired_demo_accounts` is safe if they did
(idempotent, see Purge above); an in-flight run is never killed
mid-batch, a queued one just waits its turn.

### Production rehearsal procedure — before enabling scheduled `--apply` for real

1. **Add the SSH allowlist entries.** On the server, `case` branches for
   both `docker compose exec -T backend python -m app.demo_purge purge`
   and `... purge --apply` must exist in
   `/root/deploy-allowed-commands.sh` (same pattern as the existing
   `migrate_profiles` entries) — without these, every run of this
   workflow fails closed at the SSH layer regardless of anything else
   below. This is a manual, human-reviewed server change; it cannot be
   done from this repository.
2. **Manual dry-run against production first**, reviewed by a human —
   either `workflow_dispatch` with `apply` unchecked, or directly over
   SSH: `ssh <host> "cd nutri-matic && docker compose exec -T backend
   python -m app.demo_purge purge"`. Confirm the account list looks
   right (only genuinely expired demo accounts, no surprises).
3. **Restored-database rehearsal** (recommended, not yet a hard
   requirement of this workflow): run the same dry-run against a
   restored copy of production data, same way `deploy.yml`'s
   rehearse-migration job rehearses schema migrations, to see the
   purge's behaviour against a realistic backlog size before it ever
   touches the live database.
4. **One manual `workflow_dispatch` apply run**, reviewed — check the
   `demo_purge_run_summary`/`demo_purge_batch` log lines in the Actions
   run output match the dry-run's expectations (same accounts, sane row
   counts).
5. **Let the schedule run once, then observe** — check the next
   scheduled run's summary log and GitHub Actions status before
   considering this "activated". Confirm `demo_account_counts`
   (`python -m app.demo_purge report`) trends down toward zero expired
   accounts over the following days rather than accumulating.
6. **Rollback/disable**, if anything looks wrong at any point: remove
   (or comment out) the two `demo_purge` case branches from
   `/root/deploy-allowed-commands.sh` — this immediately fails closed
   again for every future run (scheduled or manual) without touching
   this repository at all. To stop the schedule itself without a server
   change, disable the workflow from the repo's Actions tab (Actions →
   "Demo account purge" → "..." → Disable workflow) — `workflow_dispatch`
   dry-runs still work; the cron trigger won't fire.
