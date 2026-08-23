# Phytate extension — Prompt 8 final audit

> **Update (2026-08-22): manual actions 1–4 below have been worked, not just
> planned** — see "Remediation of manual actions 1–4" at the end of this document
> for what changed and the real numbers after re-running against the same real
> catalogue. The rest of this document is the original audit, unchanged.

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
  **Correction (2026-08-22): this suspicion was wrong — see "Investigation of the 14
  description mismatches" at the end of this document for the actual root cause and
  fix. The `�` above was this terminal's own rendering of a real, correctly-decoded
  character, not a decode bug in openpyxl or the workbook.**
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
- **Staging validated**: **partially** — as of 2026-08-23, `app.resolve_phytate_stable_ids`
  has completed successfully against the real catalogue with zero exceptions (see
  "First successful full stable-ID resolution against the real catalogue" below),
  producing a real `stable_id_mapping.csv`. The reviewed-import step
  (`app.import_reviewed_phytate_mappings`, remaining manual action 5) has not been
  run against it yet, so "yes" would still overstate this — no full dry run
  (resolve → reviewed import → selection) has completed end to end against the real
  catalogue.
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

## Remediation of manual actions 1–4 (2026-08-22)

Re-established the same disposable-schema environment (real catalogue re-ingested,
1,434,131 Food rows — identical to before) to actually work these rather than leave
them purely as instructions.

**1. Fixed the 6 `candidate_data_type` slips.** All 12 row instances (each of the 6
`row_identifier`s appears in two review files) changed from `branded_food` to
`sr_legacy_food` in `review_1_ambiguous.csv`, `review_3_branded_low_confidence.csv`,
and `review_4_special_cases.csv`. `check_consistency.py` still reports zero problems.
`final_approved_mapping.csv` regenerated — 6 lines changed, only the `candidate_data_type`
column, nothing else. Re-running the resolver confirmed the fix: `missing` dropped
from 6 to **0**, `resolved` rose from 931 to **937** (exactly +6).

**2. The 202 real duplicates — 105 auto-resolved, 97 genuinely need Paul's judgement.**
Rather than guess, wrote a one-off analysis (not committed — a throwaway script, not
an app feature) that pulled every candidate Food row's `protein_g_per_100g` and full
`FoodNutrient` amounts directly from the real ingested data and compared them per
duplicate group:

- **105 rows**: every candidate Food row is *nutritionally identical* — same protein,
  same every nutrient FDC recorded for it (these are the real Branded Foods dataset's
  own re-listings of one product under multiple `fdc_id`s, e.g. regional catalog
  entries). Since the choice between them cannot change any figure this app computes,
  the lowest `fdc_id` was picked deterministically and recorded, with that exact
  justification, in `docs/phytate-review/stable_id_exceptions_resolved.csv`.
- **97 rows**: candidates genuinely differ in at least one nutrient value (protein or
  otherwise) despite sharing the reviewed name — these are real, different catalog
  entries (different pack sizes/reformulations/regional listings with materially
  different nutrition), and picking one requires actual judgement about which product
  the original PhyFoodComp entry corresponds to, which this audit cannot supply.
  Listed with every candidate's protein value for comparison in
  `docs/phytate-review/stable_id_duplicates_still_needing_review.csv` — **not**
  resolved, **not** guessed.

**3. Censored-row auto-policy implemented in code**, not just documented as an idea:
`app.import_reviewed_phytate_mappings` now auto-classifies an unreviewed
`row_identifier` as `verdict="unresolved"` when — and only when — its workbook
observation is censored (`value is None`); an unreviewed row with a real number is
still a full blocking problem, unchanged. Counted separately in the reconciliation
report as `auto_unresolved_censored`, so it's always visible how many rows were
auto-handled versus genuinely reviewed by a human. Two new tests
(`test_unreviewed_censored_row_is_auto_unresolved_not_blocked`,
`test_unreviewed_numeric_row_is_still_blocked_not_auto_resolved`) prove the policy
fires exactly for the censored case and never widens past it. Full backend suite
passes with this change.

**4. Re-ran the resolver with the 105 overrides applied**: `resolved: 1042` (937 direct
+ 105 override), `duplicate: 97`, `missing: 0`, `stale: 0` — 1042 + 97 = 1,139, every
row still accounted for. `stable_id_mapping.csv` **still correctly does not exist** —
97 exceptions remain open, and Prompt 2's own rule 8 forbids generating the canonical
mapping while any do. This is progress (208 → 97 open items), not completion; the
remaining 97 are the one piece of manual action 1–4 that has no defensible automated
answer and is now Paul's decision to make, with the actual comparison data already
prepared.

The disposable schema was dropped again afterward; the real dev database was
confirmed unchanged (7,857 Food rows) throughout.

## Investigation of the 14 description mismatches (2026-08-22)

Manual action 6 asked to confirm whether the real workbook's `�` was a corrupted
source file or an environment-specific read issue, before assuming either side was
wrong. Neither guess was right — checked directly, not assumed:

- Read `xl/sharedStrings.xml` straight out of the real `.xlsx` (it's a zip of XML) and
  found the raw bytes for this cell: `...20\xc2\xbaC)...` — `\xc2\xba` is the exact,
  correctly-formed UTF-8 encoding of `º` (U+00BA MASCULINE ORDINAL INDICATOR). **The
  source workbook has always been correct.**
- Read the same cell through `openpyxl` (this app's actual adapter) and confirmed via
  `ord()` (not eyeballing terminal output) that it returns codepoint `U+00BA` — the
  correct character, not `U+FFFD`. **`openpyxl` has always been correct too.** The `�`
  seen in this document and in earlier terminal output was this environment's own
  console failing to *render* U+00BA with a glyph, not a wrong codepoint in the data —
  a display artifact, not a data bug.
- Diffed the two strings character-by-character with codepoints instead of relying on
  display: the review file's version has **`U+00C2` (`Â`) followed by `U+00BA` (`º`)**
  — two characters where the workbook has one. That's the textbook signature of UTF-8
  bytes decoded as Latin-1/cp1252: `º`'s own UTF-8 encoding (`0xC2 0xBA`) reinterpreted
  one byte at a time produces exactly `Â` + `º`. **The bug is in
  `docs/phytate-review/review_4_special_cases.csv`**, not the workbook, not this app's
  reading of it.
- Scope-checked before touching anything: grepped all seven `review_*.csv` files for
  the `Â` mojibake byte pattern. Found in **exactly 14 lines, all in
  `review_4_special_cases.csv`**, all the same 14 `row_identifier`s already
  identified (`03020177:PHYTCPP` through `03020190:PHYTCPP`) — isolated to this one
  file, not a wider encoding problem across the review corpus.
- Confirmed before fixing: all 14 rows carry `review_verdict=reject` (each with the
  same reviewer rationale — "controlled storage-degradation research sample... no
  commercial FDC product can represent this"), so **`final_approved_mapping.csv` was
  never affected** — only `import_reviewed_phytate_mappings.py`'s
  workbook-vs-review-record cross-validation would have hit this, and would have
  correctly (if for the wrong underlying reason) refused these 14 rows as a
  description mismatch rather than proceed on a corrupted comparison.
- **Fixed**: replaced the literal `Âº` → `º` in `review_4_special_cases.csv` (14
  occurrences, confirmed via `str.count`/`str.replace`, not a regex that could
  overreach). Re-ran the full cross-validation against the real workbook and real
  review files afterward: **0 description mismatches** (down from 14), **0
  compound_fraction mismatches**, **0 value mismatches** — all 3,941 reviewed rows now
  agree with the real workbook exactly. `check_consistency.py` still reports zero
  problems; `final_approved_mapping.csv` has zero diff (as expected, since none of
  these 14 rows are approve/replace).

## Bot review fixes on #52 (2026-08-22)

Two real findings from automated PR review, both fixed:

- **Rationale mislabelling**: a `CENSORED_ROW_AUTO_POLICY` synthetic decision was
  passing through the same `f"Human-reviewed ({verdict}): ..."` formatter every real
  reviewer decision does, so the persisted `match_rationale` for all 245
  auto-classified censored rows would have falsely claimed human review provenance.
  Fixed: `AUTO_CENSORED_SOURCE_FILE` sentinel added to `Decision.source_file`,
  checked before formatting the rationale, so an auto-classified row is now
  persisted as `"Auto-classified (not human-reviewed, unresolved): ..."` — never
  `"Human-reviewed"`. New test proves it, alongside a new regression test proving a
  genuinely human-reviewed decision still gets the `"Human-reviewed"` label
  unchanged.
- **Stale committed exceptions file**: `docs/phytate-review/stable_id_exceptions.csv`
  had been updated after fixing the 6 `candidate_data_type` slips (208 → 202 rows) but
  never updated again after applying the 105 overrides — the committed file still
  listed all 202 duplicates, including the 105 already resolved, contradicting this
  document's own reported 97-row remaining count. Fixed: replaced with the real
  97-row exceptions file the override-aware resolver run actually produced, verified
  zero overlap with `stable_id_exceptions_resolved.csv`'s 105 `row_identifier`s.

Full backend suite passes after both fixes.

## Second pass on the 97 duplicates (2026-08-22)

The 97 row instances collapse to only **34 unique duplicate decisions** — most
row_identifiers sharing a candidate set are the same food across several phytate
fractions (e.g. "FAMILIA SWISS MUESLI" is one decision applied to 16 IP4/IP5/IP6
row instances). Built a per-group comparison report directly from the raw FDC CSVs
(`nutrient.csv`, `branded_food.csv`, `food.csv`, `food_nutrient.csv` — no database
needed for this pass) showing exactly which nutrients differ between candidates,
each candidate's GTIN/barcode, serving size, and modification date.

That surfaced a second, stronger equivalence signal beyond raw nutrient equality:
**18 of the 34 groups (42 row instances) have every candidate sharing the identical
GTIN/barcode** (or, for the one `foundation_food` group, near-identical down to a
single trace nutrient present-vs-absent) — the same real-world product, catalogued
multiple times by USDA with inconsistent field completeness (a `null` vs. explicit
`0.0` for a minor vitamin, or a unit-representation swap like Vitamin A recorded as
IU in one entry and RAE in another). Matching GTIN is about as close to "definitely
the same physical product" as this dataset can confirm.

**One exception found and excluded**: "Bob's Red Mill Natural Foods, Inc. TEXTURED
VEGETABLE PROTEIN" shares one GTIN across all 6 candidates, but `fdc_id=733492`
genuinely differs in core macros from the other 5 (carbohydrate 36.0 vs. 39.13g,
fibre 20.0 vs. 17.4g, iron 8.0 vs. 8.7mg, protein 52.0 vs. 52.17g) — likely a real
reformulation or data-entry correction under an unchanged barcode, not annotation
noise. Moved to the genuinely-needs-review pile rather than folded into the GTIN
tier.

Auto-resolved the other **17 GTIN-matching groups (38 row instances)** the same
way as the original 105 — lowest `fdc_id`, justified this time by matching GTIN
rather than raw nutrient equality, recorded with that distinct justification in
`stable_id_exceptions_resolved.csv` (now 143 total overrides). The remaining **16
groups (59 row instances)** — genuinely different GTINs with materially different
core nutrition (different pack sizes, regional variants, or real reformulations) —
stay in `stable_id_duplicates_still_needing_review.csv` for an actual decision;
`stable_id_exceptions.csv` updated to match (97 → 59 rows). Verified: zero overlap
between the three files, 143 + 59 = 202, every original duplicate still accounted
for.

Not re-verified against a live resolver run this time (the disposable schema had
already been dropped, and reloading the full 1.4M-row catalogue again purely to
re-confirm arithmetic already checked directly against the same raw FDC CSVs the
database was built from seemed like real time spent for no new signal) — file-level
consistency was checked instead (no overlap between any pair of the three files,
exact row-count reconciliation). If in doubt, re-running
`app.resolve_phytate_stable_ids --overrides-csv stable_id_exceptions_resolved.csv`
against the real catalogue is a five-minute check once the disposable schema (or
production) is reloaded, and would show `resolved=1080, duplicate=59, missing=0`
if this arithmetic is right.

## Third pass: majority-agreement exclusion, and deduplicating the presentation (2026-08-22)

Re-checked the 16 remaining groups (59 rows) at finer grain, re-clustering each
group's raw candidates by (GTIN, full nutrient signature) instead of just GTIN
alone. Two outcomes:

**"Bob's Red Mill Natural Foods, Inc. TEXTURED VEGETABLE PROTEIN" (4 rows) —
auto-resolved with Paul's explicit sign-off.** Finer clustering showed only
`fdc_id=733492` is a true outlier — the other 5 candidates (`1124109`, `1698648`,
`1972519`, `2392801`, `2671857`) share the identical GTIN (`039978035424`) and
identical core nutrition (protein 52.17g, carbohydrate 39.13g, fibre 17.4g, iron
8.7mg) vs. `733492`'s 52.0g/36.0g/20.0g/8.0mg. This is a **weaker bar than the other
two tiers** — majority-agreement-with-a-named-exclusion, not unanimous agreement
across every candidate — so it was checked with Paul before applying, not decided
unilaterally. Resolved to the lowest `fdc_id` among the 5 agreeing candidates
(`1124109`), with `733492` explicitly named and excluded (not silently folded in)
in the override note. `stable_id_exceptions_resolved.csv` now has **147** entries
(105 original + 38 GTIN-tier + 4 this pass); `stable_id_exceptions.csv` down to
**55** rows.

**The other 16 groups don't collapse further, but the raw candidate lists were
pure noise.** USDA re-lists the same real product many times under the same GTIN
(e.g. "Supervalu, Inc. WHEAT BREAD" has 25 raw candidate `fdc_id`s but only **8
real distinct products** once clustered by GTIN + full nutrient signature — the
other 17 are just repeat catalog entries for those same 8). Rewrote
`stable_id_duplicates_still_needing_review.csv` to show, per group, the
deduplicated set of genuinely distinct products (GTIN, a representative `fdc_id`,
how many duplicate listings it represents, and its key macros) instead of a flat,
noisy candidate list — the same 16 groups and 55 row_identifiers, materially easier
to actually decide from. This is presentation-only: no ambiguity was resolved,
because a real choice between genuinely different GTINs (different pack
sizes/regional variants/reformulations) is exactly the judgement this whole
exercise couldn't automate — it's Paul's call, now with the real options in front
of him instead of noise.

One caveat carried over from the GTIN-clustering method: a handful of entries in
the deduplicated view (e.g. "Meijer, Inc. BLANCHED PEANUTS"'s two `713733444873`
rows) show the *same* GTIN split across two "distinct" clusters purely because of a
minor secondary-nutrient completeness difference, the same annotation-noise pattern
found and excluded for the GTIN tier — not re-verified row-by-row here for every
group the way it was for Bob's Red Mill specifically, so `distinct_products_found`
is a conservative upper bound, not a guarantee that every listed cluster is a
genuinely different product from its GTIN-mate.

Final state after three passes: **147 auto-resolved** (105 + 38 + 4), **55 rows /
16 groups genuinely need Paul's decision** (down from the original 202 → 97 → 59).
143 + 4 = 147; 147 + 55 = 202 — every original duplicate still accounted for,
verified via file-level set equality (not re-run against a live resolver, same
caveat as the previous pass).

## Simplification review fixes on #52 (2026-08-22)

A simplification-angle review of `reconcile_rows` in
`import_reviewed_phytate_mappings.py` (part of the code-review pass requested before
merging) found four real issues, all fixed:

- **Nested if/else broke the function's flat-guard-clause idiom.** The
  `CENSORED_ROW_AUTO_POLICY` branch nested a `row.value is None` check inside the
  `decision is None` check, with the block/continue two lines separated from its
  governing `if`. Every other check in the function is a flat early-`continue`
  guard. Restructured into two flat guards matching the rest of the function.
- **The synthetic `Decision` copied `row.food_description`/`compound_fraction`,
  making the disagreement checks two lines below trivially, tautologically true —
  dead validation for that path, not real validation.** Changed to leave those
  fields blank (`""`) instead, so the checks skip via the same falsy-guard they
  already use for any human-reviewed decision that left a field blank — no special
  case needed, no vacuous comparison against the row it came from.
- **`report["unresolved"]` and `report["auto_unresolved_censored"]` overlapped** —
  every auto-censored row was counted in *both*, breaking the mutual-exclusivity
  invariant every other report bucket follows (a downstream consumer summing
  buckets to reconcile against total rows processed would silently double-count).
  Fixed: an auto-classified row now increments only `auto_unresolved_censored`;
  `unresolved` stays exclusively the human-reviewed count. New assertion on the
  existing human-reviewed-unresolved test proves the normal path is unaffected.
- **Two new tests had identical setup, differing only in which assertions ran
  afterward.** Merged into one test asserting report counts, plan fields, and
  rationale content together — same scenario, one place to update if the policy's
  behaviour changes again.

Full backend suite passes after these fixes.

## Second code-review pass on #52 (2026-08-22)

A follow-up review (the same `/code-review 52` command re-run after the first pass
above) surfaced three more findings against `reconcile_rows`, two acted on and one
declined with reasoning:

- **Fixed — DEFERRED rows were indistinguishable from truly-unseen rows.**
  `validate_and_consolidate` silently skips a blank-verdict row noting DEFERRED/MOVED
  (a human looked, explicitly punted) the same way it skips a row that was never
  sampled at all — neither ever entered `decisions`. `CENSORED_ROW_AUTO_POLICY` then
  persisted the same `"no review coverage at all"` rationale for both, which is a
  false claim for the deferred case. Fixed: `validate_and_consolidate` now also
  returns a `deferred: set[str]` (row_identifiers with a DEFERRED/MOVED note that
  never got a real decision anywhere else), and `reconcile_rows` takes a `deferred`
  parameter to pick the accurate rationale — `"reviewed but explicitly deferred"`
  vs. `"no review coverage at all"`. Four new tests cover both directions plus the
  case where a deferred row_identifier gets a real decision in another file (the
  real decision wins, it's not "still deferred").
- **Fixed — magic sentinel string doing a typed field's job.** `Decision.source_file
  == AUTO_CENSORED_SOURCE_FILE` was the actual mechanism distinguishing an
  auto-classified decision from a human-reviewed one — the same class of fragility
  that caused the rationale-mislabelling bug fixed earlier on this PR (a
  typo'd/reused sentinel would silently misclassify with nothing to catch it).
  Replaced with a real `Decision.is_auto_censored: bool` field; the sentinel string
  now only sets a human-readable `source_file` label, never compared against.
- **Declined — reusing `phytate_selection.MEASURED_QUALIFIERS` instead of
  `row.value is None`.** `RawObservation.__post_init__` already enforces that
  `value is None` if and only if `value_qualifier` isn't a measured qualifier, so
  the two checks test the same invariant on two different types (a `RawObservation`
  mid-import vs. a persisted `CompoundObservation`) via two different, independently
  correct routes — not the same code duplicated, and importing `phytate_selection`
  into the reviewed-importer module for one boolean check adds a cross-module
  dependency for marginal benefit. Left as-is.
- **Noted, not actioned — ~245 additional per-row DB lookups now that censored
  rows reach `reconcile_rows`'s query.** This is the intended effect of
  `CENSORED_ROW_AUTO_POLICY`, not a regression: before it existed, the entire import
  refused outright on the first unreviewed censored row, so *zero* rows of any kind
  got this far. Every additional lookup is doing real, correct new work the policy
  exists to enable. A batched pre-fetch would be a reasonable future optimisation
  if import volume ever makes per-row queries here a real bottleneck, but isn't
  a correctness issue and isn't a new inconsistency (every other branch in this
  function already queries per-row).
- **Noted, not actioned — the GTIN/nutrient-signature duplicate-resolution logic
  (the 105+38+4 auto-resolved overrides) exists only as prose in this document and
  ad hoc, deleted scratch scripts, not a committed, re-runnable tool.** Accurate,
  and already implicitly flagged above ("not re-verified against a live resolver
  run"). Building a proper committed script would be real, separate work — offered
  to Paul as a follow-up, not built unprompted here.

Full backend suite passes after both fixes.

## P1/P2 bot-review remediation across the #44–#52 stack (2026-08-22)

24 unresolved bot-review conversation threads accumulated across PRs #44–#52 (branch
protection's `required_conversation_resolution` blocks merge on any of them). Fixed
every P1 and resolved every P2, either with a real fix or a documented decline.

**P1s fixed:**
- `resolve_phytate_stable_ids.py` (#44): a "replace" verdict's `candidate_data_type`
  describes the pipeline's rejected candidate, not the human-approved replacement —
  6 real rows hit this during the manual-actions remediation above. `resolve_mapping_rows`
  now falls back to a name-only match when the type-filtered query finds nothing,
  which can only become more cautious (a wrong filter that silently produced "missing"
  now either finds the one real row or correctly demotes to "duplicate" for a human).
- `resolve_phytate_stable_ids.py` (#45): `main()` no longer silently trusts the
  current DB state as the baseline on a first-ever run — a new
  `--acknowledge-new-catalogue-baseline` flag is now required, or it refuses with
  instructions.
- `import_reviewed_phytate_mappings.py` (#46): `StableTarget` now carries
  `approved_fdc_food` (already in the resolver's output CSV, just not loaded before);
  `reconcile_rows` blocks an approve/replace row if the stable-ID mapping's recorded
  `approved_fdc_food` no longer matches the signed decision's — catches a stable-ID
  mapping gone stale relative to a re-reviewed row.
- `import_reviewed_phytate_mappings.py` (#46): `reconcile_rows` now also computes
  `decisions.keys() - seen_row_ids` and blocks on every signed decision absent from
  the workbook actually being imported (previously only checked workbook → decisions,
  never the reverse).
- `import_reviewed_phytate_mappings.py` (#48): `_values_disagree` previously returned
  `False` (no disagreement) whenever *either* side was `None` — a reviewed numeric
  value and a now-censored workbook cell (or vice versa) passed reconciliation
  silently. Now only both-`None` bypasses the check; a null/non-null mismatch blocks.
- `source_licence_policy.py` (#47): `load_compound_observations` now also filters on
  `source_dataset_name == policy.source_name`, not just `compound` — a future second
  dataset sharing a compound name would otherwise inherit PhyFoodComp's policy purely
  by name collision.
- `phytate_selection.py` (#49): inositol-phosphate subsumption was computed
  Food-wide; a summed tag from one source measurement could suppress an independent
  fraction from a *different* source measurement mapped to the same food. Now grouped
  by the source-row-identifier prefix before its `:TAGNAME` suffix (see
  `phyfoodcomp_adapter`'s `f"{row_identifier}:{tagname}"` convention) so subsumption
  only applies within one originating measurement. Updated the three existing
  subsumption tests to use a shared prefix (same source entry) and added
  `test_subsumption_is_scoped_to_the_same_source_entry` covering the cross-source
  case the bug allowed.
- `+page.svelte` (#50): phytate observations were keyed by `compound_fraction`, which
  real data repeats dozens of times per food (62 duplicate `IP5_A_IP6` rows seen).
  Now keyed by index.

**P2s fixed:**
- `import_reviewed_phytate_mappings.py`: `_parse_value` silently returned `None` for
  an unparsable (non-blank) signed value, disabling the cross-check for that row.
  Now raises `UnparsableValueError`, caught in `validate_and_consolidate` and turned
  into a blocking error.
- `import_reviewed_phytate_mappings.py`: `numeric_observations` was assigned directly
  from `adapter_stats["observations_built"]`, which counts numeric *and* censored
  observations together — now subtracts `censored_observations_built`.
- `phytate_selection.py`: the censored-only early-return path didn't sort `declined`
  (determinism-contract violation) — now sorted same as the main path.
- `catalogue_manifest.py` (#45): the checksum excluded every null-`fdc_id` row, but
  those rows do participate in the resolver's name-only fallback duplicate-detection
  query (the #44 fix above) — one appearing/disappearing/renaming can turn a target
  from unique to duplicate without moving the checksum. Now fingerprinted in a second
  pass with a distinct line prefix so they can never collide with an FDC row's line;
  `row_count` is unchanged (still FDC-identified rows only).
- `routers/phytate.py` (#51): `MAX_OBSERVATIONS_RETURNED = 20` was based on the wrong
  premise (16 *distinct fraction types* exist) — real foods have up to 62 *repeated*
  observations from independent source entries. Raised to 200; still a real ceiling
  against bulk-export-shaped responses.
- `076155f11b60_preserve_censored_compound_observations.py` migration (#48): the
  pre-migration backfill labelled every existing row `measured`, including any stored
  as literal `0` — now conditionally backfills `reported_zero` for those, matching
  how new ingestion classifies the same value.
- `+page.svelte` (#50): the `selected` branch never surfaced `phytate.explanation`
  (so a food with some fractions declined gave no visible indication of partial
  coverage), and `no_data` rendered nothing at all — inconsistent with this same
  page's DIAAS/PDCAAS sections, which do surface an unavailable-reason message
  rather than staying silent. Added the explanation line to the `selected` branch and
  a `no_data` branch with a plain "not available yet" message.

**P2s declined, with reasoning (behaviour unchanged):**
- `source_licence_policy.py`: wiring `validate_source_licence_policy_coverage` into a
  live check — still no real consumer reads unregistered compounds (Prompt 6/7's
  `phytate_selection`/`routers/phytate.py` both go through the one registered
  `phytate` compound). Adding a boot-time DB dependency for a check with nothing yet
  to verify remains the wrong trade, per the original PR #47 reasoning.
- `phytate_selection.py`: applying `preparation_compatible`/match-quality to
  selection instead of just returning them as metadata. The module is deliberately
  scope-limited (see its own docstring: not an absorption model, not a molar-ratio
  calculator) to "what does the literature say, is it safe to report" — demoting
  based on quality thresholds is a scoring decision, a different and larger piece of
  design work, and `preparation_context` isn't wired from any caller yet (next
  finding), so there's no live input to demote against regardless.
- `+page.svelte` (#50): wiring an actual preparation-context UI control. No such
  control was ever in scope for Prompts 6/7/8 — the query param and
  `preparation_compatible` field exist for a future consumer. Left as dead-but-ready
  plumbing rather than building an undocumented UI feature here.
- `.github/workflows/ci.yml` (#51): adding stable-ID/catalogue validation to CI. There
  is still no real `stable_id_mapping.csv` to validate (55 duplicate rows still block
  generation — see "Third pass" above), and CI cannot run the real 1.4M-row FDC
  catalogue regardless (sandbox limitation documented earlier in this file). Nothing
  to wire up yet.

Also reworded the "Staging validated" line in "Final report" above from an
unqualified "yes" to explicitly state the rehearsal *mechanism* was validated but
the rehearsal itself never completed end to end (bot-review finding on #51).

Full backend suite (`python -m pytest`, all files) passes after every fix, including
new/updated tests for the #49 subsumption scoping, the #45 manifest fingerprinting,
and the #46 stable-ID mapping fixture shape. Frontend `svelte-check` passes clean.

## Excluding the genuinely-ambiguous branded-product duplicates (2026-08-23)

Re-examined the 55 remaining rows in `stable_id_exceptions.csv` (16 distinct
`approved_fdc_food` names, after grouping by row_identifier) using the GTIN/
nutrient-signature breakdown already captured in
`stable_id_duplicates_still_needing_review.csv` from the earlier duplicate-resolution
passes — no live database access to the real FDC catalogue was available this session
(that only ever existed inside the disposable schema from the staging rehearsal,
since deleted), so this re-used the prior analysis rather than re-deriving it.

Re-grouped each of the 16 by GTIN (not just nutrient signature) to find the true
count of physically-distinct branded products behind each name. 15 of the 16 have no
decisive majority — most split evenly (1/1, 2/2, 3/3) between genuinely different
products (different Energy/Protein/Fiber/Sugar profiles, not near-duplicate
data-entry artifacts), and the few with any gap at all (Kellogg's Frosted Flakes 3/2,
Supervalu Wheat Bread 5/4/4/4/4/2/2, Harmons Kidney Beans 4/3) are too thin to treat
as a real signal. Applying a majority-count heuristic to those 15 would be picking
essentially at random — declined to extend that tier further.

**Correction (2026-08-23, bot review on PR #54):** the 16th group, Thomas Brothers
Ham Company WHEAT FLOUR, actually does have a decisive gap — 4 of its 5 candidates
share GTIN 074854355555 with identical core nutrition (a same-barcode duplicate
listing, not really 4 independent votes), against 1 candidate under a genuinely
different GTIN. The first pass here wrongly folded this group into the "no majority"
blanket statement and rejected it along with the other 15. Paul's correction: resolve
`01030187:IP6`/`01030192:IP6` via that 4:1 majority (fdc_id=1807783, added to
`stable_id_exceptions_resolved.csv` with a note explicitly flagging it as a weaker
justification than the Bob's Red Mill TVP precedent — a true plurality between two
distinct real products, not unanimous-minus-one agreement under one barcode) rather
than exclude them. `final_approved_mapping.csv` is now 1,086 rows (1,084 + these 2
restored), and **53** rows across **15** groups remain excluded.

Paul's decision (offered three options: exclude, manually resolve each, or arbitrary
lowest-fdc_id pick): **exclude the 53 rows across the 15 groups with no real majority
from the reviewed mapping.** These are all low-confidence `branded_food`/
`category_estimate` matches to begin with, and guessing which specific packaged
product (e.g. which Frosted Flakes SKU) was intended isn't scientifically defensible.

Implementation reuses the existing, fully-tested "reject" verdict machinery rather
than inventing new plumbing: 53 `review_verdict` entries (18 in
`review_1_ambiguous.csv`, 35 in `review_3_branded_low_confidence.csv` — the latter
was 37 originally, minus the 2 Thomas Brothers rows restored by the correction above)
were changed from `approve`/`replace` to `reject`, with `approved_fdc_food`/`match_scope`
cleared and `rejection_reason` documenting the exact GTIN-count ambiguity and
pointing back at `stable_id_duplicates_still_needing_review.csv`; `review_date`
updated to 2026-08-23. No new code path — `validate_and_consolidate`/`reconcile_rows`
already handle `reject` exactly as required (matched_food_id cleared to NULL, never
inherits a prior match). The 2 Thomas Brothers rows instead got a
`stable_id_exceptions_resolved.csv` override entry (see correction above), the same
mechanism every other duplicate-resolution override in this file already uses.

Verified: `check_consistency.py` still reports 0 problems (7 files, 4112 rows);
`export_final_mapping.py` regenerated `final_approved_mapping.csv` at 1,086 rows
(down from 1,139 — the 53 excluded rows, with the 2 Thomas Brothers rows restored via
override; confirmed no overlap between the 53 excluded row_identifiers and the
regenerated file's row_identifiers). `stable_id_exceptions.csv` itself is now stale
relative to this change (it can only be regenerated by actually re-running
`app.resolve_phytate_stable_ids` against the real FDC catalogue, which remains
unavailable this session) — left as-is rather than hand-edited, since hand-editing a
tool's own output file would violate the same "generated, not hand-massaged" rule
`export_final_mapping.py`'s CI step exists to enforce. Whoever next runs the resolver
for real will see the 53 excluded rows simply absent (zero new `duplicate` exceptions
in their place) and the 2 Thomas Brothers rows resolved via the override.

## First successful full stable-ID resolution against the real catalogue (2026-08-23)

Paul supplied the real USDA FDC "Download Datasets" CSV exports locally
(`data/foundation/`, `data/sr_legacy/`, `data/branded/`). Re-created the disposable
Postgres schema technique from the Prompt 8 staging rehearsal (`CREATE SCHEMA
phytate_resolver_20260823`, `alembic upgrade head` against it via
`DATABASE_URL=...?options=-csearch_path%3Dphytate_resolver_20260823,public` — the
shared local dev database's own `foods` table, 7,857 rows, was never touched), then
ran `app.ingest_fdc` against all three directories:

```
considered=2,008,212 skipped_no_protein=574,081 inserted=1,434,131
duplicate_barcode_skipped=1,078,970 nutrient_rows=14,097,639
```

Ran `app.resolve_phytate_stable_ids --acknowledge-new-catalogue-baseline` against
that schema:

```
total rows: 1086
resolved: 1086
missing: 0
duplicate (unresolved, needs override): 0
stale (matched Food row has no fdc_id): 0
override supplied but not among candidates: 0
resolved via manual override: 149
```

**Zero exceptions — the first time this has ever resolved cleanly.** Wrote
`docs/phytate-review/stable_id_mapping.csv` (1,086 rows) for real. Verified the two
Thomas Brothers override rows resolved to `fdc_id=1807783` as intended.
`stable_id_exceptions.csv` is now header-only (the 55 stale rows from the exclusion
pass above are gone, correctly accounted for as 53 rejected + 2 resolved).

Notably, `fdc_catalogue_manifest.json` needed **no changes at all** — the freshly
computed checksum matched the one already committed exactly. The manifest's
fingerprint is `(Food.id, Food.fdc_id, Food.name, Food.data_type)` per row; since
`Food.id` is a fresh-schema auto-increment counter, re-ingesting the identical CSVs
in the identical order into a fresh schema reproduces byte-identical IDs and
therefore a byte-identical checksum. This is a real, independent confirmation that
the catalogue identity backing the review has not drifted since it was first
recorded — exactly the guarantee `check_catalogue_manifest` exists to provide.

The disposable schema was dropped immediately after (`DROP SCHEMA ... CASCADE`) —
nothing about this run touched the shared local dev database.

This closes remaining manual action 4 from the original Prompt 8 punch list. Next
(not done here): re-run `app.import_reviewed_phytate_mappings` in dry-run mode
against this mapping and review the reconciliation report — see remaining manual
action 5.

