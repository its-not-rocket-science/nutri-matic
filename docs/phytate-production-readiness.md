# Phytate/mineral-bioavailability extension — production readiness audit

PROMPT 14 of `prompts.txt`: a final end-to-end safety and readiness audit, run
2026-08-25 after PROMPTS 9–13 were all merged to `main`. This is an audit and
corrective pass, not new product functionality. Two documentation-clarity gaps
were found and fixed (see "Corrections made during this audit" below); no code
logic, schema, or behaviour changed. No real database apply, deployment, or
write to production data occurred during this audit.

## How to read this table

- **Code-enforced**: a structural mechanism (DB constraint, boundary function,
  repository-policy test, CI check) makes the wrong outcome fail, not just a
  comment saying it shouldn't happen.
- **Documented**: stated correctly in code comments/docstrings/user-facing
  copy, but relies on a human reading and following it rather than a
  mechanism that fails closed on its own.
- **Manual**: a real decision or action only a human (specifically Paul, for
  anything licence/legal) can make; nothing here should or does simulate it.

| # | Control | Enforcement | Evidence / test | Status | Remaining owner action |
|---|---|---|---|---|---|
| 1 | Every read of `CompoundObservation` goes through `load_compound_observations` or an explicit allowlisted file | Code-enforced (repository policy test) | `backend/app/source_licence_policy.py:268-298` (the boundary function); `backend/tests/test_source_licence_policy_boundary.py` — re-run this audit, 2/2 pass; allowlist is exactly `models.py`, `source_licence_policy.py`, `ingest_phytate.py`, `import_reviewed_phytate_mappings.py`, `phytate_selection.py` | ✅ Confirmed | None |
| 2 | Surface allow/deny matrix: `personal_free_ui`/`personal_free_internal_api`/`internal_research_or_admin` permitted, `public_api`/`professional_dashboard`/`clinician_report`/`enterprise_batch`/`paid_export` prohibited, for PhyFoodComp while `licence_status=pending_commercial_permission` | Code-enforced | `source_licence_policy.py:136-166` (`SOURCE_LICENCE_POLICIES`), `check_surface_allowed`; `backend/tests/test_source_licence_policy.py` — 46/46 pass this audit, including `test_every_known_surface_has_an_explicit_allow_or_deny_for_phyfoodcomp` (no surface left in limbo) | ✅ Confirmed | None while `licence_status` stays pending — re-verify this table any time `licence_status`/`permitted_surfaces` change (see control 21) |
| 3 | Plan/entitlement logic cannot expand PhyFoodComp onto a prohibited surface or remove it from the free personal surface, for any plan | Code-enforced | `backend/app/entitlements.py` — grepped this audit, zero references to `phytate`/`CompoundObservation`/`PHYFOODCOMP_1_0` anywhere in the file; `check_surface_allowed`'s signature has no `user`/`plan` parameter (`test_allowed_surface_check_takes_no_plan_argument_at_all`); `test_personal_free_ui_response_is_identical_across_every_plan` and `test_prohibited_surface_is_denied_regardless_of_plan`, both parametrized over free/trial/paid/professional/enterprise | ✅ Confirmed | None |
| 4 | The free UI calls only the permitted internal endpoint; no generic/public API, export, report, batch, or recommendation endpoint includes phytate data indirectly | Code-enforced (structurally, via control 1) + documented | `frontend/src/lib/api.ts:188` — the only frontend call site, `GET /api/foods/{id}/phytate`; grepped `routers/public_api.py`, `routers/recommendations.py`, `schemas.py` this audit for `phytate`/`compound_fraction`/`CompoundObservation` — the only hit is `schemas.py`'s `PhytateObservationOut`, which is exclusive to `routers/phytate.py`; control 1's boundary test makes a future leak structurally impossible without also being caught there | ✅ Confirmed | None |
| 5 | Censored/non-numeric observations are preserved, never coerced to zero, never selected as numeric evidence | Code-enforced (DB constraint + service layer) | `backend/app/models.py:1017-1031` — `ck_compound_observation_value_qualifier_pairing` CHECK constraint (a censored row's `original_value` must be `NULL`, a measured row's must not be); `phytate_selection.py:183-200` — `MEASURED_QUALIFIERS` filter, censored rows always routed to `declined` with an explicit reason; `test_all_censored_is_insufficient_data`, `test_reported_zero_is_selected_as_a_real_value_not_missing` (a genuine measured zero is distinguished from a censored/missing value) | ✅ Confirmed | None |
| 6 | Overlapping/incompatible phytate fractions are never summed or averaged; different analytical methods and families are kept separate | Code-enforced | `phytate_selection.py:74-92` (`FRACTION_FAMILY`, `SUBSUMES`), `:202-238` (subsumption logic, scoped per source entry so two independent measurements never suppress each other); `test_different_methods_same_family_are_both_selected_not_averaged`, `test_ip3_is_not_subsumed_by_ip5_a_ip6`, `test_ipsum_subsumes_everything_else_present`, `test_subsumption_is_scoped_to_the_same_source_entry` | ✅ Confirmed | None |
| 7 | Preparation compatibility is metadata only, never a selection filter — and is described that way, not overclaimed | Code-enforced + documented (**gap found and fixed this audit**) | `phytate_selection.py:130-136` (`_preparation_compatible` — computed but never used to exclude a row from `selected`); frontend badge at `frontend/src/routes/foods/[id]/+page.svelte:163` (shown, not hidden) | ✅ Fixed | See "Corrections made during this audit" below — was previously true in code but not explicitly stated anywhere; now documented in both the function's docstring and the methodology page |
| 8 | Importer is dry-run by default | Code-enforced | `backend/app/import_reviewed_phytate_mappings.py:651` — `--apply` is `action="store_true"`, default `False` | ✅ Confirmed | None |
| 9 | Importer resolves stable IDs only, never by name, at import time | Code-enforced | Grepped `import_reviewed_phytate_mappings.py` this audit — zero `Food.name`/name-filter lookups; targets come exclusively from `StableTarget.food_id`/`fdc_id` loaded from the pre-resolved mapping file (`:337-345`) | ✅ Confirmed | None |
| 10 | Importer is catalogue-bound (refuses to proceed if the live catalogue has drifted from what the stable-ID mapping was resolved against) | Code-enforced | `import_reviewed_phytate_mappings.py:379-395` (`check_catalogue_drift`); `test_check_catalogue_drift_flags_mismatch`, `test_check_catalogue_drift_passes_when_checksums_match` | ✅ Confirmed | None |
| 11 | Importer is transactional and idempotent | Code-enforced | `test_error_during_apply_rolls_back_everything` (a failing commit leaves zero rows); `test_apply_plans_then_reconcile_again_reports_unchanged` (running reconcile twice after a real apply reports `unchanged=1`, `inserted=0`, row count stays 1 — a second real run would not double-insert) | ✅ Confirmed | None |
| 12 | Importer's `--apply` refuses to write under a prohibited or undeclared destination surface | Code-enforced | `check_surface_allowed` + `check_deployment_permits_write`, both consulted in `--apply` (`import_reviewed_phytate_mappings.py:20-32`); `docker-compose.yml` declares `DEPLOYMENT_PERMITTED_SURFACES` as a fixed value so this deployment's real `--apply` isn't permanently fail-closed; `test_deployment_write_check_fails_closed_when_env_var_unset` and siblings | ✅ Confirmed | None |
| 13 | Import audit trail is genuinely immutable, not just documented as such | Code-enforced (DB trigger) | Migration `473bba7cef14` — real Postgres `BEFORE UPDATE`/`BEFORE DELETE` trigger, verified against a disposable schema with live `INSERT`/`UPDATE`(rejected)/`DELETE`(rejected) when originally built (PROMPT 10) | ✅ Confirmed (not re-verified live this audit — logic unchanged since PROMPT 10, migration round-trip re-verified, see control 17) | None |
| 14 | Operational readiness check surfaces a missing/misconfigured source-licence policy before a real request hits it | Code-enforced, protected | `GET /api/ready/licence-policy-coverage` (`backend/app/routers/health.py`), gated by `require_ops_diagnostic_token`; `validate_source_licence_policy_coverage` keys on `(compound, source_dataset_name)`, not compound alone; 19 tests in `test_health.py`, all passing this audit | ✅ Confirmed | Operator must set `OPS_DIAGNOSTIC_TOKEN` on the real deployment to actually use this diagnostic — currently empty-default, so the endpoint always 401s until set (safe default, but inert until configured) |
| 15 | An *existing* stable-ID mapping file's recorded `food_id`/`fdc_id` pairs can be verified directly against the live catalogue, not just re-resolved fresh | Code-enforced, manual invocation | `backend/app/validate_stable_id_mapping.py --verify-live-catalogue` (`verify_against_live_catalogue`), added PROMPT 12; not run against the real private mapping in this audit — no real DB apply occurred | ✅ Tooling confirmed present and tested (synthetic data) | Operator should run this against the real `stable_id_mapping.csv` before/alongside any real `--apply`, as a matter of operating discipline — not automatic |
| 16 | Current HEAD contains no prohibited licensed PhyFoodComp artifacts | Code-enforced (CI) + re-verified live this audit | `python .github/scripts/check_licensed_artifacts.py` run directly against real `HEAD` this audit: `No tracked file matches a licensed-artifact fingerprint (workbook or source-row).` | ✅ Confirmed | None |
| 17 | Public CI never depends on the real private PhyFoodComp data | Code-enforced | `.github/workflows/ci.yml` grepped this audit — no reference to any of the 14 quarantined filenames outside explanatory comments; `backend/tests/fixtures/synthetic_stable_id_mapping.csv` is the only mapping-shaped file CI ever reads, content-hash-bound in the scanner's allowlist | ✅ Confirmed | None |
| 18 | Migration history applies and reverses cleanly | Code-enforced, re-verified this audit | Full `alembic upgrade head` → `downgrade base` → `upgrade head` round-trip against a disposable Postgres schema this audit, all 12 revisions clean both directions; schema dropped afterward (`DROP SCHEMA ... CASCADE`, confirmed) | ✅ Confirmed | None |
| 19 | Full test suites pass | Re-verified this audit | Backend: **1630 passed, 35 skipped** (`pytest -q`, full local run, sqlite-backed unit/integration tests — the real Postgres+Redis-backed CI job already passed on PR #61, see control 20). Frontend: type-check **0 errors** (1 pre-existing unrelated warning on the meal-plan page), tests **59 passed**, production build **succeeds** | ✅ Confirmed | None |
| 20 | Branch protection actually requires the CI checks that exist, not just "a workflow exists" | Verified via GitHub API this audit (repository setting, not repo code) | `gh api repos/its-not-rocket-science/nutri-matic/branches/main/protection`: `required_status_checks.contexts = ["Backend tests", "Frontend checks"]`, `strict=true`, `required_conversation_resolution.enabled=true`, `enforce_admins.enabled=true`, `allow_force_pushes=false`, `allow_deletions=false`, `required_pull_request_reviews.required_approving_review_count=0` | ✅ Confirmed accessible and configured | `required_approving_review_count` is 0 — no human-approval count is enforced by GitHub itself; this repo's actual practice (wait for bot review + resolve every thread + explicit human merge confirmation) is a process discipline, not a platform-enforced gate. Paul may want to decide whether to raise this if the workflow ever changes (e.g. a second contributor). Not changed by this audit — reporting only, per PROMPT 14's own instruction not to alter settings |
| 21 | Commercial permission / `licence_status` | Manual, pending FAO | `source_licence_policy.py:139` — `licence_status=LICENCE_STATUS_PENDING` (`"pending_commercial_permission"`); `docs/phytate-evidence-review.md` holds the licence-request trail | ⏳ Pending | Paul: when FAO's written reply arrives, record it verbatim in `docs/phytate-evidence-review.md` first, then follow the "Activation procedure" in `source_licence_policy.py`'s own module docstring — never flip `licence_status` from a generic environment flag |
| 22 | Historical git-history exposure of the 14 files quarantined by PROMPT 9 (full content still recoverable from pre-quarantine commits) | Manual, explicitly gated | `docs/phytate-review/PRIVATE_ARTIFACTS.md`'s "What this PR does *not* do"; `prompts.txt` OPTIONAL PROMPT 15 | ⏳ Not attempted | Paul's explicit decision required before doing anything here — history rewrite affects every existing clone/fork; this audit does not make that call |
| 23 | Upstream FDC release identity | Documented honestly as unknown | `resolve_phytate_stable_ids.py`'s operator report (PROMPT 11); `app.inspect_fdc_release` found no README/metadata/changelog evidence in Paul's real FDC directories when last run | ✅ Honestly reported as unrecorded | None required now — only report evidence if it's actually found; do not infer from directory names or file timestamps (already documented as insufficient) |

## Path trace (permitted)

private source inputs → review decisions → stable-ID resolution
(`resolve_phytate_stable_ids.py`, checksum-bound to the live catalogue) →
catalogue manifest (`catalogue_manifest.py`) → dry-run reconciliation
(`import_reviewed_phytate_mappings.py` default mode) → authorised
transactional import (`--apply`, gated by controls 8–13) → stored
`CompoundObservation` → selection service (`phytate_selection.py`, controls
5–7) → free personal internal API (`routers/phytate.py`, gated by control 2's
`require_surface`) → free personal UI (control 4). Every stage that reads
`CompoundObservation` is on this path or the explicit allowlist (control 1);
there is no other stage that reads it.

## Path trace (prohibited)

`public_api`, `professional_dashboard`, `clinician_report`,
`enterprise_batch`, `paid_export` — all five are explicitly listed in
`PHYFOODCOMP_1_0.prohibited_surfaces` (control 2), denied regardless of
account plan (control 3), and structurally unreachable because nothing on
any of those code paths calls `load_compound_observations`,
`select_phytate_observations`, or the phytate router (control 1/4). No
generic export/report/batch/public-API code references phytate data at all
— confirmed by direct grep this audit, not inferred.

## Corrections made during this audit

Two documentation-clarity fixes, no logic/schema/behaviour change:

1. `phytate_selection.py`'s `_preparation_compatible` had no docstring
   statement that its result is metadata only, never a selection filter
   (PROMPT 14 item 5's explicit ask: state this rather than let it be
   implicit). The code was already correct — a `False` result was never
   used to exclude a row — but nothing said so in writing. Added.
2. The methodology page's preparation-mismatch bullet described the
   behaviour ("flagged, not hidden") without stating explicitly that this
   is informational only, not a filter. Added one clarifying sentence.

## Final acceptance criteria — status against this audit

- **All real PhyFoodComp functionality is available on the ordinary free
  personal surface regardless of account plan.** ✅ Controls 2, 3.
- **All paid/professional/public/export/batch surfaces are denied while
  permission is pending.** ✅ Controls 2, 3, path trace (prohibited) above.
- **Unknowns fail closed.** ✅ Every boundary function in
  `source_licence_policy.py` (`get_policy`, `source_key_for_compound`,
  `check_surface_allowed`, `deployment_permitted_surfaces`) raises/empties
  rather than defaulting to allowed; re-keying `COMPOUND_SOURCE_KEYS` on
  `(compound, source_dataset_name)` (PROMPT 13) closed the one remaining
  ambiguity case (a hypothetical second source for the same compound).
- **No prohibited real source artifacts are present in current public
  HEAD.** ✅ Control 16, re-verified live this audit.
- **Stable mappings remain bound to exact `fdc_id` values and the
  catalogue checksum.** ✅ Controls 9, 10.
- **The documentation says the upstream FDC release is unknown unless
  evidence has actually been found.** ✅ Control 23.
- **No real database apply or deployment occurred during this audit.**
  ✅ Confirmed — every DB interaction this audit used a disposable Postgres
  schema (`audit_prompt14_migration_check`), dropped with `CASCADE`
  afterward, or the existing sqlite-backed test suite. No `--apply`, no
  production write, no deploy.
- **The final report contains no overclaims and lists every remaining
  manual/legal decision.** Controls 20 (branch-protection review-count
  note), 21 (FAO reply), 22 (historical git exposure) are the three
  remaining manual/legal items; none are silently assumed resolved.

## What this audit did not do (deliberately, per PROMPT 14's own scope)

- Did not add speculative product functionality.
- Did not rewrite git history (control 22 — Paul's decision, PROMPT 15).
- Did not change `licence_status` or any FAO-related field (control 21).
- Did not change GitHub branch-protection settings (control 20) — reported
  the exact current configuration only, since PROMPT 14 item 9 explicitly
  says not to claim CI is required merely because a workflow exists, and
  not to change settings without separate authorisation. This also
  satisfies `prompts.txt` PROMPT 16 item 2, which asked for the same check
  independently — done once here, not duplicated.
- Did not run a real `--apply` against production or any non-disposable
  database.
