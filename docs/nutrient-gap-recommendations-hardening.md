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
