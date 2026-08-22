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

