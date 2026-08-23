# Phytate extension — Prompt 8 final audit

Prompt 8 of the phytate/mineral-bioavailability extension (see `prompts.txt`). This is
a reporting/audit pass, not a new feature — no production write happened, and no
commercial-use flag was touched. Where this audit found a real, unresolved problem it
is stated plainly below, not smoothed over.

## PRs delivered (Prompts 1–8, stacked)

| PR | Prompt | Summary |
|----|--------|---------|
| [#44](https://github.com/its-not-rocket-science/nutri-matic/pull/44) | 1 | Audit + preserve the untracked reviewed-verdict importer |
| [#45](https://github.com/its-not-rocket-science/nutri-matic/pull/45) | 2 | Stable fdc_id resolver + `ImportManifest`/catalogue checksum |
| [#46](https://github.com/its-not-rocket-science/nutri-matic/pull/46) | 3 | Transactional, stable-ID-only reviewed importer |
| [#47](https://github.com/its-not-rocket-science/nutri-matic/pull/47) | 4 | Fail-closed source-licence policy + free-surface boundary |
| [#48](https://github.com/its-not-rocket-science/nutri-matic/pull/48) | 5 | Preserve censored/non-numerical observations |
| [#49](https://github.com/its-not-rocket-science/nutri-matic/pull/49) | 6 | Conservative phytate observation-selection service |
| [#50](https://github.com/its-not-rocket-science/nutri-matic/pull/50) | 7 | Free personal phytate UI/API |
| *(this PR)* | 8 | CI additions, real staging rehearsal, licensing audit |

## CI additions (this PR)

`.github/workflows/ci.yml`'s existing `backend` job already ran the complete backend
suite (unit, API, security-regression, and the real Alembic migration chain) against
real Postgres and Redis services, and the `frontend` job already ran type-checking,
unit tests, and the production build — all pre-existing, all still true after this
extension's PRs. Added:

- **Review consistency + canonical mapping regeneration, fail on drift.** Runs
  `check_consistency.py`, then `export_final_mapping.py`, then
  `git diff --exit-code -- final_approved_mapping.csv`. Verified locally before adding:
  regenerating produces a byte-identical file to what's committed (confirmed on this
  branch, using the real seven `review_*.csv` files).
- **Confirm no licensed source workbook is tracked in git** — greps `git ls-files` for
  any tracked `.xlsx`, fails if found. Verified locally: zero matches today.
- Already covered by the existing `python -m pytest -q` step, not new: the
  source-licence policy tests across every plan/surface combination (#47's 37 tests),
  the repository-level dependency test proving every `CompoundObservation` consumer
  declares a permitted surface (`test_source_licence_policy_boundary.py`), and the
  reviewed importer's fixture dry-run/rollback tests (#46's 35 tests).
- **Docker layers**: confirmed by inspection, not a new check — `backend/Dockerfile`
  only `COPY`s `app`, `migrations`, `alembic.ini`. `docs/` (where the workbook could in
  principle have ended up) is never part of the image.
- **Frontend bundles**: no phytate-related asset in `frontend/` references or embeds
  anything from `docs/phytate-review/` or `data/` — the frontend only ever calls the
  gated `/api/foods/{id}/phytate` endpoint.

## Staging rehearsal — real, not simulated

The real `PhyFoodComp_1.0.xlsx` and the real FDC catalogue CSV exports (Foundation,
SR Legacy, Branded — `2026-04-30` release, correctly `.gitignore`d under `data/`,
never committed) turned out to exist locally. Rather than declare the staging
rehearsal blocked, it was actually run, against a **fully disposable environment**:

- A new Postgres **schema** (`phytate_staging_rehearsal`) inside the existing local
  `nutrimatic` database — not a new database, because the connecting role lacks
  `CREATEDB`; a schema gives the same isolation without needing elevated privileges.
  `search_path` was set to `phytate_staging_rehearsal, public` (the trailing `public`
  only so `pg_trgm`'s operator classes, installed there, remain visible — new tables
  still landed in the disposable schema first).
- `alembic upgrade head` ran clean against real Postgres, end to end, including this
  extension's three new migrations (`2c049f319235`, `4cdb265fe305`, `076155f11b60`) —
  the first time any of them had been verified against a real database rather than
  SQLite.
- Real FDC ingestion (`app.ingest_fdc`, unmodified): Foundation (420 inserted),
  SR Legacy (7,460 inserted), Branded (1,426,251 inserted) — **1,434,131 total Food
  rows**, matching this codebase's own long-standing "~1.4M-row real Food catalog"
  comments.
- The existing local dev database (`nutrimatic`'s `public` schema, 7,857 Food rows)
  was **never touched** — confirmed unchanged (still 7,857) after the rehearsal.
  `DROP SCHEMA phytate_staging_rehearsal CASCADE` removed everything created for this
  rehearsal at the end.

### Prompt 2's resolver — real numbers

`app.resolve_phytate_stable_ids` against the real 1,434,131-row catalogue and the real
1,139-row `final_approved_mapping.csv`:

```
resolved: 931
missing: 6
duplicate (unresolved, needs override): 202
stale (matched Food row has no fdc_id): 0
override supplied but not among candidates: 0
```
931 + 6 + 202 = 1,139 — every row accounted for as resolved or blocked, mechanically
verified. Catalogue checksum for this exact snapshot recorded to
`docs/phytate-review/fdc_catalogue_manifest.json` (this PR) as the first real pinned
baseline; `docs/phytate-review/stable_id_exceptions.csv` (this PR) is the real,
complete 208-row exceptions list.

**Two real, human-actionable findings, not resolver bugs:**

1. **6 "missing" targets are a likely `candidate_data_type` transcription slip in the
   review files**, not absent from the catalogue. `"Soybean, curd cheese"`, `"Tofu,
   raw, firm, prepared with calcium sulfate"`, and `"Tofu, raw, regular, prepared with
   calcium sulfate"` (rows `03020012:PHYTCPP`, `03020013:PHYTCPP`, `03020014:PHYTCPP`,
   `03020167:PHYTCPP`, `03020168:PHYTCPP`, `03020173:PHYTCPP`) all exist in the real
   catalogue as **`sr_legacy_food`**, not `branded_food` as recorded. Not corrected
   here — that's a review-data judgment call for Paul, not something this audit
   should silently rewrite. Fix path: correct `candidate_data_type` for these six
   `row_identifier`s in whichever `review_*.csv` carries them, regenerate
   `final_approved_mapping.csv`, re-run the resolver.
2. **202 duplicates** are exactly the scenario Prompt 2 designed for: the real
   Branded Foods dataset re-lists the same product name under multiple `fdc_id`s
   (e.g. `"Food For Life Baking Co Inc FOOD FOR LIFE, BROWN RICE BREAD"` matches 4
   distinct Food rows). None were auto-picked. Each needs a `chosen_fdc_id` entry in
   `docs/phytate-review/stable_id_exceptions_resolved.csv` (doesn't exist yet — no
   overrides have been supplied) before the canonical `stable_id_mapping.csv` can be
   generated.

**The canonical `stable_id_mapping.csv` was correctly not generated** — 208
exceptions remain open, and Prompt 2's own rule 8 forbids generating it while any do.

### Prompt 3's importer — real workbook, real review files

Cross-validated the real workbook (`app.phyfoodcomp_adapter.load_phyfoodcomp_workbook`)
against the real seven `review_*.csv` files (`validate_and_consolidate`, 0 blocking
errors):

```
sheets: 18
rows_considered: 3,377
observations_built: 4,186 (3,941 numeric + 245 censored)
decisions covering row_identifiers: 3,941
```

- **Every single one of the 245 censored observations is an unreviewed
  `row_identifier`** — confirmed exactly, not estimated. Zero numeric observations are
  unreviewed. This is precisely the interaction flagged (but not fabricated a number
  for) in #48: because the pre-Prompt-5 adapter never gave a censored cell a
  `RawObservation`/`row_identifier` at all, none of them ever went through human
  review. Running the real reviewed importer today would refuse the *entire* import
  as `unknown row_identifier` on these 245 rows alone (correct, fail-closed behaviour
  — attempted for real: pointing the CLI at a nonexistent stable-ID mapping file
  produced exactly the expected refusal, `error: not a file ... -- run
  app.resolve_phytate_stable_ids first`).
- Cross-checked all 3,941 reviewed rows' `food_description`/`compound_fraction`/value
  against the real workbook: **0 compound_fraction mismatches, 0 value mismatches**
  beyond the documented tolerance. **14 `food_description` mismatches** — all the same
  cause: the real workbook's cell text for a "20°C"-style temperature reads as a
  literal replacement character (`�`, U+FFFD) where the signed review record has `º`
  (e.g. `03020177:PHYTCPP` through `03020190:PHYTCPP`, all "Tofu, Proto soybean ...
  stored" rows). This looks like an environment/library-specific decode issue reading
  that cell (openpyxl in this environment), not a corrupted source file — worth Paul
  double-checking with the actual workbook open in Excel/LibreOffice before assuming
  either side is wrong. Either way, Prompt 3's cross-validation would correctly
  refuse these 14 rows as a description mismatch rather than silently accept a
  different string than what was reviewed.
- Verdict breakdown across the 3,941 reviewed rows: 1,031 approve + 108 replace
  (**= 1,139**, matching `final_approved_mapping.csv` exactly — a clean cross-check),
  2,664 reject, 138 unresolved.

**Idempotence, rollback, and free/prohibited-surface access were not re-verified
against this real data** — they didn't need to be. #46's 35 tests already prove
`apply_plans`/rollback and idempotent re-application against a forced NOT NULL
violation and a real synthetic workbook; #47's 37 and #49's 27 and #50's 11 tests
already prove surface enforcement and plan-parity, none of which depend on catalogue
scale — proving it a second time against 1.4M rows would exercise the same code paths
for no new signal. What genuinely needed the real catalogue and the real workbook —
resolution totals, cross-validation against real text, the real reviewed-import
refusal — was run for real above, not asserted from unit tests alone.

### Confirmed no existing behaviour changed

`foods` count in the real dev database (`nutrimatic`'s `public` schema): 7,857 before
and after. No recommendation/nutrient code path was touched by any of Prompts 1–8 —
confirmed by the source-licence boundary test's own allowlist (only `models.py`,
`source_licence_policy.py`, `ingest_phytate.py`, `import_reviewed_phytate_mappings.py`,
and `phytate_selection.py` reference `CompoundObservation` anywhere in `backend/app`)
and by grep: `bioavailability.py`, `food_chemistry.py`, and
`stock_recipes/robustness.py` each still say phytate isn't modelled in their own
domain, unchanged and still accurate.

## Licensing audit matrix

Every code path in `backend/app` that reads `CompoundObservation` or could return a
PhyFoodComp-derived result, found via the repository-level boundary test's own
allowlist plus a `grep -ri phytate` sweep of `backend/app`:

| Path | Declared surface | Outcome |
|------|------------------|---------|
| `GET /api/foods/{id}/phytate` (`routers/phytate.py`) | `personal_free_internal_api` | **Allowed** — the only serving endpoint that exists |
| `app.phytate_selection.select_phytate_observations` | caller-supplied, enforced via `load_compound_observations` | Allowed only for `personal_free_ui` / `personal_free_internal_api` / `internal_research_or_admin`; raises `SourceLicenceError` for anything else |
| `app.ingest_phytate` (automated write path) | n/a — never serves a response | Out of scope for the surface gate; writes only |
| `app.import_reviewed_phytate_mappings` (reviewed write path) | `--scope` CLI flag, independently fail-closed | Out of scope for the surface gate; writes only, and separately refuses any scope but `noncommercial_free_surface` |
| `app.resolve_phytate_stable_ids` | n/a — read-only, no serving | Never touches `CompoundObservation`, only `Food`/`ImportManifest` |
| Personal diary/meal UI | — | **Not wired to phytate at all** — no reference found |
| Recommendation engines (`recommend_*.py`, `recommendations.py`) | — | **Not wired** — no reference found |
| Public API keys/quotas (`routers/public_api.py`) | — | **Not wired** — exposes `/score`, `/complement`, `/bioavailability/iron` only |
| Snapshots/exports (`diary_snapshots`, CSV export) | — | **Not wired** — no reference found |
| Clinician/professional dashboard (`routers/clinician.py`) | — | **Not wired** — no reference found |
| Enterprise/batch services | — | **Do not exist yet** in this codebase at all |
| Admin/research utilities | — | **Not wired** — no reference found |

Structural note: `Food` has **no ORM `relationship()`** to `CompoundObservation`
anywhere in `models.py` — every link is a plain FK column. A generic "serialize this
Food" endpoint (e.g. `GET /api/foods/{id}`) cannot leak phytate data via relationship
traversal even by accident; phytate is only reachable through the one router that
explicitly queries for it.

## Final report — five separate states, not conflated

- **Code complete**: yes, Prompts 1–8 (this PR) — resolver, transactional importer,
  licence policy, censored-value schema, selection service, free UI/API, CI
  additions, and this audit.
- **Staging validated**: yes, against a disposable schema with the real catalogue and
  real workbook (above) — with two concrete open items (6 likely `candidate_data_type`
  slips, 202 duplicates needing overrides) blocking `stable_id_mapping.csv`
  generation, and a 245-row review-coverage gap (censored observations) blocking a
  full reviewed import even once those resolve.
- **Free personal surface enabled**: code-enabled (Prompt 7, PR #50), but **no real
  phytate data has been imported into any database that surface reads from** — the
  personal UI/API exist and are gated correctly, but there is nothing to show yet.
- **Production data imported**: **no**. Not attempted, not scheduled. Every write in
  this rehearsal happened only inside the now-deleted disposable schema.
- **Commercial permission received**: **no**. `licence_status` in
  `source_licence_policy.py` remains `pending_commercial_permission`. Nothing in this
  audit changes that flag, and nothing should until Paul supplies FAO's actual written
  reply for review.

## Exact remaining manual actions

1. Resolve the 6 likely `candidate_data_type` slips (`sr_legacy_food`, not
   `branded_food`) in the relevant `review_*.csv` file(s), regenerate
   `final_approved_mapping.csv`.
2. Add `chosen_fdc_id` overrides for the 202 real duplicates in
   `docs/phytate-review/stable_id_exceptions_resolved.csv` (doesn't exist yet).
3. Decide and document a policy for the 245 censored `row_identifier`s the review
   protocol has never seen — extend human review to them, or write an explicit
   documented rule for how censored rows enter the reviewed-import path without full
   food-matching review (they carry no number to match against a mineral database in
   the first place).
4. Re-run `app.resolve_phytate_stable_ids` for real once 1–2 are done; confirm zero
   exceptions; only then does `stable_id_mapping.csv` get generated.
5. Re-run `app.import_reviewed_phytate_mappings` in dry-run once 3 is resolved;
   review the reconciliation report; only then consider `--apply` against a
   **disposable** database again, never production directly.
6. Investigate the 14 `�`/`º` description-mismatch rows — confirm with the real
   workbook opened directly in Excel/LibreOffice whether the source cell is genuinely
   `º` (an environment-specific read issue on this machine) before assuming either
   side is wrong.
7. Turn on GitHub branch protection requiring the `backend`/`frontend` CI jobs before
   merge, if not already on (pre-existing gap noted in `ci.yml`'s own comments,
   unrelated to this extension).
8. When Paul receives FAO's actual written reply: record it in
   `docs/phytate-evidence-review.md` first, then edit `PHYFOODCOMP_1_0`'s
   `licence_status`/`permitted_surfaces`/`redistribution_permitted`/`export_permitted`
   in `source_licence_policy.py` to match those exact terms — never before, never
   from a generic environment flag.
9. Only after 1–8: a real production import, with explicit operator confirmation of
   dataset version and workbook checksum, exactly as `app.import_reviewed_
   phytate_mappings --apply` already requires.

Until all of the above: commercial permission stays `false`, phytate stays off every
monetised surface, no unattended production import runs, and phytate is not marketed
as part of any paid tier.
