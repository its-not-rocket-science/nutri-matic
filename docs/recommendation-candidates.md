# Ingredient candidate generation: filter order and bounds

Public-launch hardening prompt 4. Fixes: "Add foods" (`GET
/api/recommendations/ingredients`) could return "No safe or useful
addition found" even when ordinary, practical foods that would have
helped genuinely existed in the catalogue.

## Root cause

`recommend_ingredients._candidate_pool` ranked candidates by raw
per-100g nutrient value, took the top `CANDIDATE_POOL_PER_NUTRIENT`
(12), and only *then* checked eligibility — `candidate_metadata.
resolve_candidate_metadata`'s practicality (a small curated allowlist of
~40 common foods; everything else, including every branded product,
defaults to `suitable_for_direct_suggestion=False`) and dietary
exclusion. The top-12-by-raw-value for almost any nutrient is
disproportionately branded/exotic/extreme rows — ordinary useful foods
(lentils, chickpeas, spinach) are rarely *the* single highest per-100g
figure for anything, so they often never made it into the pool at all.
When the whole pool of 12 got rejected on eligibility, the result was
an empty suggestion list — not because no useful candidate existed, but
because eligibility was checked too late to matter.

## Fix: documented filter order, applied before truncation

`_candidate_pool` (`app/recommend_ingredients.py`) now applies every
hard-eligibility filter to an **over-fetched** window, in this order,
before truncating to the final pool size — so the top N kept are the
top N *eligible* candidates, not the top N *overall* with eligibility
checked afterward:

1. **Visibility/source eligibility** — non-branded only, pushed into the
   SQL query itself (`Food.data_type != "branded_food"`, allowing
   `NULL` for manually-entered foods). `resolve_candidate_metadata`
   excludes every branded product unconditionally regardless of name
   anyway, so there's no reason to even fetch one. This also
   structurally prevents near-identical branded product lines from
   crowding the pool (prompt 4 item 3) — they're never in it.
2. **Data-quality eligibility** — `data_quality.is_implausible`.
3. **Dietary exclusions** — the same `is_hard_excluded` logic
   `filter_excluded_foods` uses elsewhere, with constraint tags loaded
   **once per call**, not once per shortfall nutrient (bounded query
   count).
4. **Direct-suggestion practicality** — `candidate_metadata.
   resolve_candidate_metadata(...).suitable_for_direct_suggestion`, and
   (also moved earlier, same reasoning) meal-type suitability when a
   `meal_type` was given.
5. **Plausible serving constraints** — structurally satisfied rather
   than separately checked: a candidate is always trialled at a
   quantity drawn from its own curated `ServingRange`
   (`default_g`/`maximum_g`), so `is_plausible_serving` is true by
   construction. Unchanged by this prompt.
6. **Nutrient relevance** — falls out of the SQL ordering: rows are
   fetched highest-`amount_per_100g`-first, and the first
   `CANDIDATE_POOL_PER_NUTRIENT` to pass every filter above are kept.
7. **Scoring and deterministic tie-breaking** — unchanged, happens in
   `suggest_ingredients`'s main loop exactly as before (score
   descending, then food name).

Every ineligible row encountered during pool-building is still recorded
in `IngredientSuggestionResult.rejected` with a `reason_code`
(`"implausible_value"` | `"dietary_exclusion"` | `"impractical"` |
`"meal_type_mismatch"`, extended by `"energy_limit"` |
`"no_improvement"` from the scoring loop) — nothing is silently
discarded, matching this module's existing convention.

## Bounded query count/runtime (item 4)

Exactly one `FoodNutrient` + `Food` join query per shortfall nutrient,
each capped at `CANDIDATE_POOL_PER_NUTRIENT * CANDIDATE_FETCH_MULTIPLIER`
(12 × 25 = 300) rows — a fixed ceiling, not a fraction of the catalogue,
so cost doesn't grow as the ingested FDC catalogue grows. Plus one
constraint-tags query total. Regression-tested in
`tests/test_recommend_ingredients.py::test_bounded_query_count_independent_of_junk_candidate_volume`
(asserts query count stays under a fixed ceiling regardless of how many
ineligible rows exist for the shortfall nutrient).

## Stable reason codes when nothing is suggested (item 6)

`IngredientSuggestionsOut.no_suggestion_reason_code` (new field, only
set when `suggestions` is empty and the engine wasn't disabled outright
— `disabled_reason_code` covers that separate case):

| Code | Meaning |
|---|---|
| `no_shortfall` | Nothing tracked is below/near target — no gap to close. |
| `no_eligible_candidates` | Every shortfall nutrient's candidate window had no food that was simultaneously non-branded, plausible, dietarily eligible, and practical. |
| `energy_limit` | Every eligible candidate would have exceeded `max_additional_energy`. |
| `no_meaningful_improvement` | Eligible, energy-permitted candidates existed but none scored above zero (low data coverage, meal-type mismatch, or just not enough impact). |

Frontend: `ImproveThis.svelte` shows a specific message per code
(`recommendationSafety.ts::noSuggestionReasonMessage`, same
code-to-message pattern already used for `SafetyWarningCode`) instead of
always showing the generic "No safe or useful addition found" — that
generic text is now only the fallback for an unmapped/future code.

## What this prompt deliberately did not change

- `candidate_metadata.py`'s curated-foods allowlist itself — widening it
  is a content/curation task, not a pipeline-ordering one. The fix here
  is that the *existing* curated foods are actually reachable now.
- Recipe/pair/substitution candidate generation (`recommend_recipes.py`,
  `recommend_pairs.py`, `recommend_substitutions.py`) — separate
  pipelines, not touched; their test suites pass unmodified (see prompt
  4's final test run).
- Scoring formula/weights (`recommendation_scoring.py`) — unchanged.
