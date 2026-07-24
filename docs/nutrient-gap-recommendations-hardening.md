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
