# Nutrient-gap recommendations — security/validation hardening pass

Companion to `docs/nutrient-gap-recommendations.md` (the original feature
build). This file tracks the "Nutri-Matic Hardening Prompts" pass: an
8-prompt security/validation review of the nutrient-gap recommendation
feature after it shipped. Same per-prompt structure as the original doc.

## Prompt 1: fix standalone recipe access control

**Real vulnerability found and fixed.** `routers/recommendations.py`'s
`_recipe_as_items()` (the `recipe_id`-scope handler behind `GET /api/
recommendations/ingredients?recipe_id=...`, added for the recipe-detail
page's "Improve this recipe") loaded the recipe via `db.get(Recipe,
recipe_id)` directly — no ownership, sharing, or public/system-owned
check at all. Any authenticated user could pass another user's private
recipe id and receive real nutrient-gap-analysis output derived from
that recipe's ingredients: a genuine information-disclosure and
enumeration bug (a private recipe returned 200 with real data; a
nonexistent id returned 404 — the difference itself confirms existence).

**Root cause**: recipe access was never treated as its own boundary
separate from profile ownership. `get_owned_profile` correctly scopes
*whose* diary/meal-plan the request is about, but nothing then checked
whether the *recipe* referenced by `recipe_id` belonged to, was shared
with, or was public/stock-owned relative to the caller.

**Fix**: extracted the recipe-visibility logic `routers/recipes.py`
already had (`_get_visible_recipe`/`_get_owned_recipe`/`_is_shared_with`)
into a new shared module, `app/recipe_access.py` — the one canonical
place this decision is made:

- `get_visible_recipe(recipe_id, current_user, db)` — read-only access:
  owner, explicitly shared-with (`RecipeShare`), or public (`is_public`,
  which also covers system-owned/stock recipes — those are always
  created with `is_public=True`, not a separate flag).
- `get_owned_recipe(recipe_id, current_user, db)` — mutating access:
  owner only.

Both raise a plain 404 for every inaccessible case (doesn't exist, or
exists but not visible) — never 403 — so a caller can't distinguish
"wrong id" from "right id, not yours" from the status code, matching
this app's existing anti-enumeration convention (`routers/recipes.py`
already did this consistently; the bug was that `routers/
recommendations.py` didn't reuse it).

`routers/recipes.py` now imports `get_visible_recipe`/`get_owned_recipe`/
`is_shared_with` from `recipe_access.py` instead of defining them
locally (aliased to the same private names at the call sites, so none of
its ~20 existing call sites needed to change) — one implementation, two
routers.

`routers/recommendations.py` changes:
- `_recipe_as_items()` now calls `get_visible_recipe()` instead of
  `db.get(Recipe, recipe_id)` — the actual fix.
- `get_substitution_suggestions()`'s `current_recipe` lookup (from
  `entry.recipe_id`, where `entry` is already scoped to the caller's own
  profile) was changed from `db.get(Recipe, ...)` to
  `get_visible_recipe(...)` too — not the same attacker-facing severity
  (the recipe id isn't attacker-suppliable there, it's derived from an
  already-profile-scoped entry), but kept consistent with "one canonical
  resolver, always used" rather than leaving a second direct-`db.get`
  code path for a reviewer to trip over later. Also degrades cleanly to
  404 if a logged recipe was later deleted or made private, instead of
  serving stale/unauthorized data.

No other endpoint in `routers/recommendations.py` accepts a direct
`recipe_id` (`/recipes` and `/pairs` are day/range-scoped only), so this
was the complete surface for this specific gap.

**Tests**: `test_recipe_access.py` (the resolver in isolation — owner,
public, system/stock, shared, inaccessible-private, nonexistent, and a
dedicated test asserting the inaccessible-private and nonexistent cases
produce byte-identical 404 responses) and three new cases in
`test_recommendations_api.py`:
`test_recipe_source_rejects_another_users_private_recipe`,
`test_recipe_source_nonexistent_and_inaccessible_return_identical_404`,
`test_recipe_source_allows_public_recipe_from_another_user`. Full backend
suite: 814 passed (up from 803 before this prompt; +11 new tests, 0
regressions).

## Prompt 2: strict API parameter validation

Every `/api/recommendations/*` query parameter now has an explicit,
enforced bound — most via FastAPI's own `Query(..., ge=, le=, gt=)`
constraints (checked by Pydantic before the endpoint body runs at all,
so a malformed request never reaches a database query), the rest via a
new shared module, `app/recommendation_params.py`, for the two checks
that don't fit a single-field constraint:

- `validate_date_range(start_date, end_date)` — rejects `start_date >
  end_date` and caps the span at `MAX_DATE_RANGE_DAYS` (90).
- `parse_priority_nutrients(raw)` — trims whitespace, drops empty
  tokens, deduplicates, caps the count at `MAX_PRIORITY_NUTRIENTS` (20),
  and rejects any key not in `nutrients.NUTRIENTS` with a 422 naming the
  unknown key(s) — a typo'd nutrient key silently behaving as "no
  priority" would be worse than an explicit rejection.

**Bounds applied** (`routers/recommendations.py`):

| Parameter | Constraint |
|---|---|
| `servings` | `0 < servings <= 20` |
| `max_suggestions` | `1 <= max_suggestions <= 10` |
| `max_additional_energy` | `0 <= value <= 5000` |
| `energy_tolerance_kcal` | `0 <= value <= 2000` |
| `recipe_id`, `entry_id` | positive integers (`gt=0`) |
| `start_date`/`end_date` | `start <= end`, span `<= 90` days |
| `priority_nutrients` | trimmed/deduped/capped at 20, every key must be real |
| `meal` | `Literal["breakfast","lunch","dinner","snack"]` |
| `source` | `Literal["diary","meal_plan"]` |
| `goal` | must be a `recommend_recipes.GOAL_PRESETS` key (dynamic, so a plain runtime check rather than a `Literal`) |

`ge`/`le` constraints reject `NaN`/`inf` for free — a `NaN` fails every
comparison (`nan >= 0` is `False`), and `inf` fails any `le` bound, so no
separate "reject non-finite" check was needed.

**Ordering fix, not just new constraints**: `get_ingredient_suggestions`
and `get_recipe_suggestions` previously called `assess_eligibility()` (a
real `DietaryConstraint` query) *before* checking the scope-combination
was even valid (`recipe_id` + `entry_date` together, a reversed date
range, etc.) — a malformed request was doing real database work before
being rejected. All four endpoints now run every shape/semantic check
(scope combination, `priority_nutrients`, date-range consistency) first,
and only reach `assess_eligibility`/entry-loading queries once the
request is known-valid. `test_invalid_scope_never_reaches_eligibility_
check` asserts this directly, by making `assess_eligibility` raise if
called and confirming a malformed request still gets a clean 422 rather
than an `AssertionError`-turned-500.

Internal candidate-pool bounds (`CANDIDATE_POOL_PER_NUTRIENT`,
`MAX_PAIR_EVALUATIONS`, etc., prompt 12) are unchanged and remain the
second line of defence regardless of what a caller requests.

**Tests**: `test_recommendation_params.py` (the two shared validators in
isolation) and `test_recommendations_param_validation.py` — a table-
driven, `pytest.mark.parametrize`d suite of 52 cases covering every row
in the bounds table above, both the rejected and the still-valid
boundary values (e.g. `max_suggestions` at exactly 1 and 10 must still
succeed). Full backend suite: 877 passed (up from 814), 0 regressions.
No frontend change needed — `lib/api.ts` never sends a value outside any
of these bounds.

## Prompt 3: expose the full explainable score breakdown

`recommendation_scoring.ScoreBreakdown` already carried every term the
formula calculates (prompt 4) — this prompt is about *exposing* it
through the public API, plus one genuine gap it surfaced: the
"multi-nutrient bonus" the conceptual formula names was never its own
number, just a multiplier folded silently into `weighted_gap_reduction`
inside `_gap_reduction()`.

**Real decomposition, not just plumbing**: `_gap_reduction()` now
returns `(base_reduction, multi_nutrient_bonus, improved)` instead of a
single bundled figure — `ScoreBreakdown` gained a `multi_nutrient_bonus`
field, and `weighted_gap_reduction` now reports the *base* per-nutrient
weight sum on its own. `weighted_gap_reduction + multi_nutrient_bonus`
together equal what the single bundled figure meant before this split;
`total` (and every existing caller reading only `total`/`score`) is
numerically unaffected. This deliberately changed `test_score_breakdown_
total_equals_component_sum`'s expected-sum formula (added `+ result.
multi_nutrient_bonus`) — a documented consequence of the split, not a
regression, and a second scenario (`..._with_multi_nutrient_bonus`) was
added specifically because the original test's fixture never actually
triggered a nonzero bonus, so it wouldn't have caught a missing term.

`ScoreBreakdown` also gained `model_version: int =
RECOMMENDATION_MODEL_VERSION` (prompt 12's constant), stamped on every
breakdown at creation time — a client can now tell which scoring-formula
version produced a given suggestion.

**API schema**: a new `schemas.ScoreBreakdownOut` (all ten numeric terms
+ `total` + `model_version`, deliberately excluding `nutrients_improved`/
`nutrients_worsened` — already exposed as each suggestion's own top-level
fields, so the breakdown never duplicates them) is now a `score_
breakdown` field on `IngredientSuggestionOut`, `RecipeSuggestionOut`,
`SubstitutionSuggestionOut`, and `PairSuggestionOut` (the combined pair
score only — `PairContributionOut.solo_score` stays a bare float, never
the ranking metric, per `recommend_pairs.py`'s own docstring). The
existing top-level `score` field is untouched — a client reading only
`score` sees no difference at all.

`routers/recommendations.py` gained one shared `_score_breakdown_out()`
converter, used by all four endpoints, so the mapping is written once.

**Tests**: `test_recommendations_score_breakdown_api.py` — one test per
suggestion mode (ingredient/recipe/substitution/pair), each asserting:
`score_breakdown.total == score` (the backwards-compatibility
invariant), every breakdown field is a plain JSON number (no leaked
internal object), `model_version` matches
`RECOMMENDATION_MODEL_VERSION`, and `total` equals the sum of the ten
named components computed from the *API response itself* (not just the
Python dataclass) — genuinely checking what a real client would receive.
Plus two new `test_recommendation_scoring.py` cases (the multi-nutrient-
bonus sum invariant, and `model_version` presence). Full backend suite:
883 passed (up from 877), 0 regressions.

**Frontend**: `lib/types.ts` gained a `ScoreBreakdown` interface and a
`score_breakdown` field on `IngredientSuggestion`/`RecipeSuggestion`/
`SubstitutionSuggestion` (no `PairSuggestion` type exists frontend-side —
pairs were never wired into the UI in prompt 10, a stated scope
decision, unchanged here). `RecommendationCard.svelte` gained an
optional `scoreBreakdown` prop and a second, separately-collapsed
`<details>` — "Why this ranked here" — listing only the *nonzero* terms
with a human label and a rounded (display-only) value, closed by
default so it doesn't overwhelm the existing "Explanation & remaining
gaps" disclosure. Verified with a clean `svelte-check` (0 errors),
`vitest run` (13 passed), and a successful production build.

## Prompt 4: expose data quality, provenance and mapping confidence

Everything this prompt asks to *reuse* already existed and was already
persisted (from the earlier alias/provenance rounds): `models.
RecipeIngredientProvenance` (`match_method`/`match_relationship`/
`match_confidence`/`match_rationale`/`match_used_fallback`/
`match_validation_warning`/`match_preferred_fdc_id`/
`match_preferred_food_id`), `Recipe.match_coverage_lines`/
`match_coverage_mass`/`unresolved_ingredients`, and `RobustnessResult.
model_version`. Nothing here reruns ingredient matching — every number
below is aggregated from rows the stock-recipe import pipeline already
wrote.

**Direct food suggestions** (`recommend_ingredients.IngredientSuggestion`)
gained `fdc_id` (USDA FoodData Central id, `None` for a manually-entered
food), `data_type` (`Food.data_type` verbatim), and `candidate_source`
(`candidate_metadata.py`'s `"curated"`/`"category_default"` tier). A
direct food suggestion involves no ingredient-*alias* matching at all —
that system is specific to stock-recipe ingredient-to-`Food` resolution
— so `candidate_source` is this mode's own analogue of a mapping-
confidence signal, documented as such rather than adding permanently-
`None` `mapping_relationship`/`mapping_confidence` fields that could
never actually apply here.

**Recipe and substitution suggestions** gained a new
`recommendation_provenance.RecipeQualitySummary` (`quality_summary` on
both `RecipeSuggestionOut` and `SubstitutionSuggestionOut`), aggregating
every ingredient's `RecipeIngredientProvenance` row (where one exists)
into: counts and proportions of exact-or-regional / analogue / proxy-or-
reviewed-substitution / fuzzy-unclassified ingredients, min and mass-
weighted mapping confidence, a fallback-resolution count, an unresolved-
or-low-confidence count (`Recipe.unresolved_ingredients` line count plus
any resolved ingredient below `LOW_CONFIDENCE_THRESHOLD`=0.5), and
`nutrient_coverage` (`Recipe.match_coverage_mass`, reused verbatim — see
`recommendation_provenance.py`'s docstring for why this isn't recomputed
or defaulted to 1.0 here, unlike the *scoring* engine's own separate
coverage-fallback policy). Both suggestion types also gained
`robustness_model_version` alongside the existing `robustness_rating`.

**A `reviewed_substitution` is never bucketed with `exact`** — per the
prompt's explicit instruction, `_PROXY_RELATIONSHIPS = {"category_proxy",
"reviewed_substitution"}` groups a human-reviewed pairing with a
proxy match, never with `exact`/`regional_equivalent`, regardless of how
confident the reviewer was. This was true of the *scoring* engine
already (an uncertainty penalty doesn't care about review status
specifically) — this prompt makes it explicit and visible in the
exposed summary too.

**Tests**: `test_recommendation_provenance.py` — 14 cases covering
exact, regional (bucketed with exact), canonical/exact_name non-alias
methods (also bucketed with exact), analogue, category_proxy,
reviewed_substitution (confirmed never exact), fallback-resolved, mixed-
quality proportions, mass-weighted-vs-flat-average confidence, legacy-
null (a stock recipe with zero provenance rows at all), a plain user
recipe (no coverage concept at all), unresolved ingredient lines, fuzzy-
unclassified, and `nutrient_coverage` reuse. Plus
`test_recommendations_provenance_api.py` — 7 end-to-end HTTP tests
covering exact-match, high-robustness, mixed-quality (regional+proxy+
fallback), missing-robustness (no `RobustnessResult` row at all),
legacy-null, ingredient `fdc_id`/`data_type`/`candidate_source`, and
substitution wiring. Full backend suite: 904 passed (up from 883), 0
regressions.

**Frontend**: `lib/types.ts` gained a `RecipeQualitySummary` interface
and the new fields on `IngredientSuggestion`/`RecipeSuggestion`/
`SubstitutionSuggestion`; no new UI surface was added this prompt (the
existing "Why this ranked here" disclosure from prompt 3 covers the
score, not ingredient provenance) — the types are ready for a future
"data quality" expandable section to consume. `svelte-check` (0
errors), `vitest run` (13 passed), and the production build all remain
green.

## Prompt 5: strengthen medical-constraint handling

**Real policy change, not just plumbing**: a `DietaryConstraint(category=
"medical")` row previously only added a `medical_constraint_present`
warning — recommendations still ran normally. It now disables the
*entire engine* by default, the same way an under-18 profile is disabled
(prompt 11) — `assess_eligibility()` returns `enabled=False` with a new
`disabled_reason_code=unacknowledged_medical_constraint`. This is a
deliberate behaviour change this prompt explicitly asked for, not a
regression — the pre-existing `test_medical_constraint_surfaces_as_
warning_not_silently_dropped` test (which asserted the *old* behaviour)
was rewritten to assert the new one.

**Re-enabling requires an explicit, stored, revocable acknowledgement —
never a request parameter.** New model, `models.
MedicalRecommendationAcknowledgement` (`profile_id`, `policy_version`,
`acknowledged_at`, `revoked_at`), and three new endpoints under `/api/
profiles/{id}/medical-acknowledgement`:

- `GET` — the currently active acknowledgement, or `null`.
- `POST` — records a new acknowledgement (201). Always inserts a new
  row rather than mutating a past one (same immutable-history
  convention as `RobustnessResult`) — a full audit trail of every
  acknowledge/revoke cycle.
- `DELETE` — revokes every currently-active acknowledgement (204,
  always, even if nothing was active — a harmless no-op). Always fully
  revocable, per the prompt's explicit requirement.

An acknowledgement only counts as *active* if its `policy_version`
matches the current `recommendation_safety.MEDICAL_ACKNOWLEDGEMENT_
POLICY_VERSION` — bump that constant whenever the acknowledgement's
wording/scope changes materially, and every existing acknowledgement
stops counting until the profile re-acknowledges under the new terms
(same versioning shape as `RECOMMENDATION_MODEL_VERSION`).

**What acknowledging does *not* do**, enforced structurally rather than
by convention: it never reads the medical constraint's free-text `note`
(no code path exists that could); every hard dietary exclusion and the
upper-limit penalty stay fully enforced regardless of acknowledgement
state (they're independent code paths in `dietary_filter.py`/
`recommendation_scoring.py`, never touched by this prompt); and the
`medical_constraint_present` warning keeps showing on every response
even once acknowledged — "continue to show the warning" is enforced by
`assess_eligibility` always appending it whenever a medical constraint
exists, before it even checks acknowledgement status.

**No query-string bypass anywhere** — confirmed by grepping `routers/
recommendations.py` for any request parameter resembling an override,
and by `test_no_query_string_bypass_for_medical_disable`, which throws
several plausible bypass-parameter names (`acknowledge_medical`,
`override_safety`, etc.) at the ingredients endpoint and confirms every
one is silently ignored — the only way to change eligibility is the
dedicated, authenticated, ownership-checked endpoint above.

**Profile-deletion cascade gap found and fixed while implementing
this**: `routers/profiles.py`'s `delete_profile` already cleaned up
`DietaryConstraint` rows for a deleted dependent profile, but the new
`MedicalRecommendationAcknowledgement` table wasn't added to that
cleanup list — a real, if minor, orphaned-row gap, fixed by adding it
alongside `DietaryConstraint`'s own deletion. Covered by extending the
existing `test_dependent_profile_can_be_deleted_and_cascades_its_data`.

**Tests**: `test_recommendation_safety.py` gained acknowledge/revoke/
policy-version-mismatch/history-preserved cases (module-level) and
`test_recommendations_safety_api.py` gained the full HTTP flow: disables
by default, re-enables on acknowledgement (warning still shown),
disables again on revocation, the status endpoint, cross-account
acknowledgement rejection, the query-string-bypass attempt, and — proving
"candidate services are not called when disabled" directly — a test that
monkeypatches `suggest_ingredients` to raise if called at all, then
confirms a disabled request still returns a clean empty response. Full
backend suite: 916 passed (up from 904), 0 regressions.

**Frontend**: `lib/api.ts` gained `getMedicalAcknowledgement`/
`acknowledgeMedicalConstraints`/`revokeMedicalAcknowledgement`;
`lib/types.ts` gained `MedicalAcknowledgement` and `disabled_reason_code`
on the three wired suggestion-list types. `ImproveThis.svelte`'s
disabled-notice now shows an "I understand — show general suggestions
anyway" button specifically for the medical-constraint case (confirmed
via a native `confirm()` dialog stating this is not medical clearance,
matching this app's existing destructive-action convention), which
calls the acknowledge endpoint and re-fetches. `vitest run` (16 passed,
+3 new `api.ts` cases), `svelte-check` (0 errors), and the production
build all remain green.
