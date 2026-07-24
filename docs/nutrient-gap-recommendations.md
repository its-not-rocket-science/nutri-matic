# Nutrient-gap recommendations — architecture audit and design

This is the audit deliverable for the "Nutrient-Gap Suggestions for Meals
and Meal Plans" prompt set, prompt 1: what already exists, what's missing,
and the proposed module boundaries for prompts 2 onward. Written *before*
any recommendation-engine code beyond what already existed — see "Existing
reusable services" below, which is substantial.

The feature must never diagnose a medical deficiency. Every nutrient
comparison is described as below, near, within, or above the app's
applicable target or reference range — never "deficient" or "excess
disease risk."

## 1. Existing reusable services

This app already has a working, narrower version of this feature, and a
full set of the primitives a broader one needs:

- **`aggregation.py`** — `WeightedFood`, `aggregate_nutrients`,
  `aggregate_amino_acids`, `compute_protein_quality_with_coverage`,
  `expand_entries_to_weighted_foods`. The last one is generic over any
  `QuantifiedEntry`-shaped row (`food_id`+`quantity_g` XOR
  `recipe_id`+`quantity_servings`) — `DiaryEntry` and `MealPlanEntry` both
  satisfy it already, so day/meal-plan-day aggregation is *already* one
  shared code path, not two. `compute_protein_quality_with_coverage`
  already embodies the "missing data reduces confidence, never counts as
  zero" principle prompt sections 2/3 ask for generally — its
  `coverage_fraction`/`excluded_foods` shape is the pattern to reuse, not
  reinvent.
- **`nutrients.py`** — `NUTRIENTS`/`resolve_drv`: a profile-aware (sex,
  pregnancy, lactation) daily reference value per nutrient, each carrying
  a `drv_source` and `drv_confidence` ("live_confirmed" |
  "secondary_source"). **No upper-limit field exists at all** — see
  section 3.
- **`energy_goal.py`** / **`protein_requirement.py`** — personalised
  energy and protein targets (BMR × activity, weight × activity factor)
  used instead of a flat DRV for those two keys specifically. Already the
  precedent for "a target can be a calculation, not a table lookup."
- **`dietary_filter.py` + `dietary_tags.py`** — `filter_excluded_foods` /
  `filter_excluded_recipes` (hard exclusion — allergy/religious/pattern),
  `food_dietary_status` / `recipes_dietary_status` (soft "avoid"/"unknown"
  display, worst-ingredient-wins for recipes). This is the hard-filter
  layer prompts 4/6/7 must run every candidate through.
- **`stock_recipes/ingredient_aliases.py` + `food_matching.py`** — the
  `AliasRelationship` (exact/regional_equivalent/close_analogue/
  category_proxy/reviewed_substitution) + confidence + rationale system
  from the previous work is exactly "ingredient-mapping confidence" (prompt
  4 point 6, prompt 13 case 9) — already a first-class, tested, API-exposed
  concept. Nothing new needed here except *reading* it as a scoring input.
- **`stock_recipes/robustness.py`** — Monte Carlo robustness ratings per
  recipe, with an established "`not_calculated_reason`, never a fabricated
  score" convention — the model for recipe-level uncertainty in prompt 7.
- **`routers/diary.py`** — `_compute_nutrient_gaps`, `_find_worst_gap`,
  `_rank_foods_by_nutrient`, `_rank_recipes_by_nutrient`, and
  **`optimizer.py`**'s `suggest_meal_optimizations` are a real, working,
  *single-nutrient* version of this whole feature already: pick the day's
  worst-%DRV nutrient, rank real foods/recipes by how much of it they
  carry (dietary-filtered, implausible-value-filtered, with a supporting
  DB index), and simulate real before/after totals through
  `aggregate_nutrients` for add/swap/add-recipe actions — never estimated
  from a candidate's raw content alone. This is the foundation to
  *generalise* (multi-nutrient, meal-plan-scoped, richer candidate
  metadata), not replace. It currently lives as private (`_`-prefixed)
  functions inside one router, not a shared service module.
- **`data_quality.py`** — `is_implausible`: already filters absurd
  per-100g source values out of ranking/totals. Reusable for "poor
  nutrient-data coverage" penalties.
- **`optimizer.load_prices_by_food_id`** — the established pattern for an
  *optional*, user-entered, never-fabricated extra signal (cost): present
  when data exists, `None` (not 0, not excluded) when it doesn't. The
  model to follow for candidate metadata in prompt 5.
- **`methodology.py`** — `SCORING_METHODOLOGY_VERSION` /
  `DRV_METHODOLOGY_VERSION`, bumped whenever a change would alter a
  previously-computed figure for the same inputs. `DiarySnapshot` (a frozen
  JSON blob per day, versioned by both) is the precedent for prompt 12's
  cache-key/invalidation design.

## 2. Missing services

- **Tolerable upper limits.** Nothing in `NUTRIENTS` carries one at all.
  Sodium is handled as a special "no upward DRV — see
  `food_chemistry.py`'s sodium:potassium ratio" case, not a general UL
  system. Prompt 2 must add an optional UL (+ source/confidence, same
  honesty convention as the existing DRV fields) per nutrient where one is
  confidently known — several, not all, will end up `None` rather than a
  guessed figure.
- **Structured nutrient status.** No below/near/within/above categorisation
  exists anywhere — today's UI only has the raw `percent_drv` number and
  colours it ad hoc (`NutrientBars.svelte`). Prompt 3 introduces this as a
  first-class enum.
- **Meal-plan-day and multi-day gap analysis.** `_compute_nutrient_gaps`
  only ever runs against `DiaryEntry` rows for one day. Extending it to
  `MealPlanEntry` is close to free (same `QuantifiedEntry` shape); multi-day
  needs DRV × day-count scaling, which doesn't exist yet in any form.
- **A genuine multi-nutrient scoring engine.** `optimizer.py` optimises
  *one* nutrient (the day's single worst gap) at a time. Prompt 4 wants a
  candidate scored across several prioritised nutrients simultaneously,
  with upper-limit penalties, provenance-confidence weighting, energy-
  overshoot penalties, and a full breakdown — a materially larger model.
- **Food-group/meal-type/serving/practicality metadata.** Confirmed by
  reading `models.Food`/`models.Recipe` directly: neither carries anything
  of the kind (no food group, no meal-type, no serving-size, no
  "suitable as a direct suggestion" flag). `RecipeTag` (free text) and
  `Collection`/`CollectionRecipe` (curated + computed-dietary groupings)
  are the only categorisation that exists, and neither covers meal-type or
  serving size. Prompt 5 is building this from nothing.
- **Structured warning codes.** Every existing explanation
  (`optimizer.OptimizationSuggestion.rationale`, etc.) is a plain prose
  string. Prompt 11 needs a coded taxonomy underneath the prose.
- **Caching for this class of computation.** Everything today is computed
  live per request; `DiarySnapshot`'s frozen-JSON + methodology-version
  approach is the only real precedent to extend, not an existing cache
  layer to plug into.
- **Two-item combination scoring and whole-recipe substitution.** Neither
  exists. The closest analogue to substitution is `optimizer.py`'s "swap"
  action, which replaces one *food ingredient* inside a meal with a
  same-family food — not a whole recipe for another whole recipe (prompt
  8's actual scope).

## 3. Nutrients: targets, upper limits, informational-only, coverage

- **Valid lower/target DRV today:** ~35 keys in `NUTRIENTS`, profile-aware
  via `resolve_drv`.
- **No DRV at all** (`nutrients.NO_DRV`): `iron_heme`, `iron_non_heme`,
  `beta_carotene`, `vitamin_k2`, `monounsaturated_fat`,
  `polyunsaturated_fat`, `epa`, `dha`, `arachidonic_acid`,
  `resistant_starch`, `inulin`, `beta_glucan`, `sodium` (deliberately — see
  below), plus `energy`/`protein` (personalised elsewhere, not a table
  value).
- **Upper limits:** none defined anywhere yet. This is the single biggest
  content gap prompt 2 has to fill, and the one requiring the most care —
  every UL added must cite a real UK COMA/EFSA/US IOM figure with the same
  `drv_confidence`-style honesty tag, defaulting to "not established" rather
  than invented wherever the true figure isn't confidently known.
- **Informational-only (no independent optimisation target makes sense):**
  `sodium` (a "don't exceed" nutrient the current %DRV machinery is built
  the wrong way round for — already documented in `nutrients.py`), and
  every "subset of X" nutrient (`iron_heme`/`iron_non_heme` are subsets of
  `iron`; `fiber_soluble`/`fiber_insoluble` are subsets of `fiber_total`;
  `beta_carotene` contributes to `vitamin_a`). These must never be
  independently optimisation-eligible — they'd double-count against their
  parent nutrient.
- **Insufficiently reliable coverage:** can't be quantified without a live
  ingested catalog in this environment (not available in this session — see
  prior "Not run" disclosure pattern); qualitatively, micronutrient
  `FoodNutrient` coverage is sparser than macronutrient coverage across
  FDC. The gap-analysis service (prompt 3) tracks `coverage`/confidence
  generically per candidate rather than hardcoding an assumption about
  which nutrients are "reliable enough" — that's a property of the actual
  data at query time, not a fixed list.

## 4. How targets differ by profile and period

`resolve_drv` already varies by (sex, pregnancy, lactation); energy/protein
are fully personalised calculations. **No period scaling exists at all** —
every existing target is implicitly "for one day." A meal currently gets
compared against the *whole day's* target using the day's other entries as
context (see `get_meal_optimization`, which pulls every entry that day, not
just the meal) — this is already, informally, "remaining daily target when
diary context exists" (prompt 2's requirement), just not named or
generalised as such. Multi-day needs DRV × day-count; nothing like that
exists yet.

## 5. How meal-plan portions are represented

`MealPlanEntry` mirrors `DiaryEntry` exactly: `plan_date` + `meal`
("breakfast"/"lunch"/"dinner"/"snack") + exactly one of
(`food_id`+`quantity_g`) or (`recipe_id`+`quantity_servings`), enforced by a
`CheckConstraint`. `MealPlanTemplateEntry` is the same shape again, minus a
concrete date (a `day_offset` instead). `expand_entries_to_weighted_foods`/
`scale_recipe_ingredients` already handle both entry kinds generically —
this is the reason meal-plan-day analysis is a small extension of
diary-day analysis, not a parallel implementation.

## 6. How recipes are filtered by dietary constraints

Ingredient-level: `filter_excluded_recipes` drops a recipe with *any*
hard-excluded ingredient; `recipes_dietary_status` reports the worst
("avoid" > "unknown" > "ok") status across ingredients for recipes that
remain, for display. Both take an optional `Profile` (household-aware) and
no-op for an anonymous caller or a profile with nothing configured.

## 7. How candidate foods can be queried efficiently

`_rank_foods_by_nutrient` (routers/diary.py) already does: filter by
`nutrient_key`, sort by `amount_per_100g` descending (`FoodNutrient` has a
supporting composite index — `ix_food_nutrients_key_amount`, added after a
measured 137ms→0.2ms improvement on 222k rows), drop
`data_quality`-implausible rows, over-fetch before hard-filtering by diet so
exclusions don't silently shrink the result below the caller's limit. This
generalises to "multi-nutrient weighted candidate query" in prompt 4/6, but
the single-nutrient version and its index are already proven at realistic
scale.

## 8. Where provenance and uncertainty can be preserved

- Per-ingredient: `AliasRelationship`/confidence/rationale
  (`ingredient_aliases.py`), already API-exposed.
- Per-recipe: `RobustnessResult` (immutable history, `is_latest`,
  `not_calculated_reason` per metric).
- Per-protein-score: `ProteinQualityResult.coverage_fraction`/
  `excluded_foods`.
- Per-raw-value: `data_quality.implausibility_reason`.
- Per-DRV-figure: `NutrientDef.drv_source`/`drv_confidence`.

Every one of these already exists as a queryable, typed value — the
recommendation engine's job is to *read* them into its scoring/explanation
output, not invent a parallel uncertainty representation.

## 9. Food-group/meal-type/serving metadata

Confirmed absent from both `Food` and `Recipe` (see section 2). The only
categorisation that exists at all is `RecipeTag` (free text, user-defined)
and `Collection`/`CollectionRecipe` (curated "themed"/"educational", or
computed "dietary" membership via `dietary_filter.evaluate_food` — see
`stock_recipes/collections_config.py`). Neither is meal-type or serving-size
metadata. Prompt 5 is a genuinely new, small, curated table plus safe
category defaults — not a refactor of something that half-exists.

## 10. Safest first-release scope

1. **Target resolver** (prompt 2), generalising `resolve_drv`/energy/
   protein to meal/day/multi-day — ship with upper limits present in the
   schema but populated only where a real figure is confidently sourced,
   `None` everywhere else (never a placeholder number).
2. **Gap/excess analysis** (prompt 3), built on
   `compute_protein_quality_with_coverage`'s coverage-aware philosophy.
3. **Ingredient suggestions only** first (prompt 6), reusing
   `_rank_foods_by_nutrient`'s proven candidate pool plus a *small* curated
   practical-metadata set (tens of common foods, not the whole catalog).
4. Recipe suggestions (7), substitutions (8), and the pair optimiser (9) as
   later increments once the scoring engine (4) and metadata (5) are
   solid — each is a real jump in complexity and should land as its own
   reviewable slice.
5. Frontend (10) incrementally, one page at a time, after its backend
   endpoint exists and is tested.

**Sequencing deviation, stated explicitly:** prompt 11 ("safety, clinical
boundaries and explanation rules") is numbered last, but prompts 2-4 will
already be emitting user-facing explanation strings and status categories.
Centralising the wording/warning-code rules *after* several prompts have
already invented their own phrasing risks an inconsistent retrofit. This
audit recommends drafting the core wording constants (the never-say/
always-say rules, the below/near/within/above/above-upper vocabulary) as
part of prompt 2/3's work, then formalising the fuller structured
warning-code system in prompt 11 once there's real usage to generalise
from — noted here so the deviation from the prompt's own ordering is a
documented decision, not an oversight.

## Proposed module boundaries

| Module | Owns |
|---|---|
| `nutrient_targets.py` | Profile/period-aware target resolution (prompt 2) — the generalised, public replacement for `_compute_nutrient_gaps`'s target half. |
| `nutrient_gap_analysis.py` | Consumed-vs-target comparison, status categorisation, coverage handling (prompt 3). |
| `recommendation_scoring.py` | The general candidate-scoring engine (prompt 4) — reads alias/robustness/data-quality provenance, never recomputes it. |
| `candidate_metadata.py` | Curated + default practical metadata (prompt 5). |
| `recommend_ingredients.py` / `recommend_recipes.py` / `recommend_substitutions.py` / `recommend_pairs.py` | One mode each (prompts 6-9), all built on the three modules above plus the existing `dietary_filter`/`optimizer` primitives. |
| `recommendation_safety.py` | Centralised wording/warning-code rules (prompt 11), consumed by every `recommend_*` module. |

None of this replaces `optimizer.py`/`routers/diary.py`'s existing
single-worst-gap feature — that stays as-is (a fast, simple, already-shipped
path); the new modules are additive, reusing its proven pieces
(`_rank_foods_by_nutrient`'s query shape, `aggregate_nutrients`-based real
simulation) rather than duplicating them.

## Scope note on this prompt

No recommendation-engine code is added in this prompt, per its own
instruction — this document only. The next prompt (2) is the first to add
code: the profile-aware nutrient target resolver.

## Prompt 2: target semantics

`app/nutrient_targets.py` implements the resolver; `app/nutrients.py`
gained the metadata it reads (`target_type`, `upper_limit` +
source/confidence, `optimisation_eligible`) — additive fields with safe
defaults, so every existing caller of `NUTRIENTS`/`resolve_drv` is
unaffected (verified: `test_nutrients.py` and the full backend suite pass
unchanged).

**Target types** (`nutrients.TARGET_TYPE_*`):
- `minimum_or_adequate_intake` — the ordinary case, an RNI/AI-style figure
  to *reach*. `lower_target`/`preferred_target` are the same number (this
  app doesn't track a distinct "ideal, above the minimum" figure — see the
  dataclass comment on why `preferred_target` is still its own field).
- `maximum_guideline` — the figure is a ceiling, not a floor (sodium,
  saturated fat) — `lower_target`/`preferred_target` are always `None`;
  only `upper_target` is set.
- `personalized` — energy/protein: a calculation, not a table lookup.
- `informational` — no independent optimisation target at all (a subset
  of another tracked nutrient, or nothing established in any direction);
  `optimisation_eligible=False` with a stated `ineligibility_reason`.

**Upper limits** (`nutrients.NutrientDef.upper_limit`, resolved via
`resolve_upper_limit`) are commonly-cited EFSA/US IOM/UK-derived
population figures — **not medical advice**, and deliberately absent
(`None`) for several nutrients rather than guessed:
- **Form-specific ULs not applied to this app's tracked (food-only, or
  combined) figure**: niacin (the UL concerns supplemental nicotinic
  acid), folate (concerns synthetic folic acid; this app tracks combined
  DFE), magnesium (concerns supplemental intake).
- **Renal-clearance-dependent, not a general-population risk**:
  phosphorus, potassium — this app has no renal-function data to condition
  on, so no UL is asserted (see prompt 11's "sensitive contexts" handling).
- **Genuine disagreement between bodies** (EFSA vs US IOM, often ~2x
  apart): zinc, iodine — the more conservative (EFSA) figure is used,
  stated explicitly in `upper_limit_source`, rather than silently picking
  one.
- **Uncertain/possibly outdated**: vitamin B6 (EFSA's 2023 re-evaluation
  substantially changed prior guidance; this module can't verify which
  figure currently stands without a live source), manganese (EFSA
  concluded data were insufficient to set one at all).
- **vitamin_a/retinol**: the general adult UL is used for every profile
  variant, including pregnancy — a distinct, confidently-sourced
  pregnancy-specific numeric UL wasn't available to this module, so rather
  than invent one, pregnancy is left as a sensitive context to be handled
  conservatively (prompt 11), not a different number here.

**Periods**: `AnalysisPeriod.MEAL`/`DAY` always resolve one day's worth as
a flat figure — a meal is never automatically treated as one-third of a
day (explicitly disallowed by the prompt); `MULTI_DAY` multiplies by
`day_count`. `resolve_meal_comparison_target` is the actual meal-specific
machinery: pass `already_consumed_today` for a "remaining daily target"
comparison when diary context exists, or `explicit_share` (e.g. `1/3`) for
reviewing a meal/recipe with no such context — a caller supplying neither
gets the plain day figure back (`comparison_mode="full_daily"`), left for
the caller to interpret.

## Prompt 3: gap analysis

`app/nutrient_gap_analysis.py`. Six statuses only — `insufficient_data`,
`below_target`, `near_target`, `within_target`, `above_preferred`,
`above_upper_limit` — chosen so the word "deficient"/"excess" never has to
appear anywhere in this module or anything downstream of it. Coverage
(fraction of consumed mass with a known, non-implausible value for that
nutrient) below 50% forces `insufficient_data` regardless of the raw
number, so a total built from mostly-missing data is never presented with
false confidence. `optimisation_weight` is 0 for `energy` unconditionally
(matches the existing `_find_worst_gap`'s exclusion — a calorie target
isn't a "gap" in the same sense) and capped at 1.0 per nutrient so an
enormous shortfall can't be rewarded disproportionately once prompt 4's
scoring engine sums these.

## Prompt 4: scoring engine

`app/recommendation_scoring.py`. Scores one already-simulated candidate
(before/after `NutrientGapResult` lists) — it never aggregates or fetches
anything itself. Every weight lives in one `ScoringWeights` dataclass
(`DEFAULT_WEIGHTS`), overridable per call. The two most safety-relevant
design choices, stated explicitly:
- **Upper-limit breaches are penalised ~10x more heavily than merely
  exceeding the preferred amount** (`upper_limit_penalty_weight=4.0` vs
  `above_preferred_penalty_weight=0.4`), and only ever for excess the
  candidate itself *creates or worsens* — a pre-existing excess the
  candidate didn't cause earns no penalty (not this candidate's doing) but
  earns no credit either.
- **A gap already resolved before the candidate was added contributes
  nothing to `weighted_gap_reduction`** — the cap lives in
  `nutrient_gap_analysis`'s `optimisation_weight` (already 0 for anything
  at/above target), and this module never re-introduces unbounded reward
  on top of it (see `test_adversarial_extreme_oversupply_does_not_
  blow_up_the_score`).

## Prompt 5: candidate metadata

`app/candidate_metadata.py`. Layered: `CURATED_FOODS` (a maintained,
name-matched table of common recommendation candidates) → `EXCLUDED_
KEYWORDS` (leavening agents, stock cubes, raw seasoning, supplements,
plain fats/oils — never suitable standalone regardless of curation) →
`_CATEGORY_DEFAULTS` (a short, deliberately conservative list of generic
fallbacks) → excluded from direct suggestion by default. A branded
product's `data_type` is checked *before* any name match at all — its name
is marketing copy, not a reliable description, so it can never
"accidentally" match a curated generic entry.

**Safety note, stated explicitly because it was a real bug caught by this
module's own test suite during development**: there is deliberately no
blanket "name contains 'raw'" category default. This app's catalog
includes raw meat/fish/egg ("Chicken, raw", "Salmon, raw") alongside raw
produce, and a generic "raw things are edible as-is" fallback would have
marked those as safe to suggest standalone — a real safety problem, not
just a gastronomically odd one. Every category default is instead an
explicitly reviewed, genuinely-edible-unprepared food form. See
`test_raw_meat_and_fish_never_fall_through_to_a_safe_default`, kept as a
permanent regression guard.

### Maintainer guide: extending the curated candidate table

Add an entry to `CURATED_FOODS` keyed by a lowercase substring that
matches the target `Food.name` (USDA-style, e.g. `"bananas, raw"`, not
`"banana"` alone unless that's genuinely unambiguous) via the `_curated()`
helper — set a real `ServingRange` a person would actually eat, the
correct `FoodGroup`/`CandidateKind`/meal types, and `requires_prep`/
`burden` honestly (never mark something requiring cooking as needing no
preparation). Run `test_candidate_metadata.py` after any addition — the
raw-meat regression guard and the branded-food/excluded-keyword tests all
re-run against the full table automatically.

## Prompt 6: suggest additional ingredients

`app/recommend_ingredients.py` + `GET /api/recommendations/ingredients`
(`app/routers/recommendations.py`). Ties prompts 2-5 together into the
first user-facing mode: pool candidates from whichever nutrients are
currently `below_target`/`near_target`
(`nutrient_gap_analysis`), hard-filter by dietary constraints
(`dietary_filter.filter_excluded_foods` — the same function search/
discovery already uses) and `candidate_metadata`'s suitability flag,
simulate each survivor's real before/after effect at its curated serving
size, and rank with `recommendation_scoring.score_candidate`. Works
identically for a diary day or a meal-plan day (`source=diary`/
`meal_plan` query param) — the function itself never queries
`DiaryEntry`/`MealPlanEntry`, the router does, exactly like every existing
diary/meal-plan endpoint's own `expand_entries_to_weighted_foods` reuse.

**A real bug found and fixed while writing this prompt's tests**, worth
recording because it's a subtle instance of a principle repeated
throughout this feature ("missing data must reduce confidence, never
count as zero"): adding a candidate with *no data at all* for some
unrelated nutrient increases that nutrient's total consumed **mass**
without adding any new **information** about it, which can dilute its
`coverage` below the judgeable threshold and demote its status to
`insufficient_data`. The scoring engine's `_gap_reduction` was initially
counting that status-change's weight drop as an "improvement" (weight did
go from something to 0), which is exactly backwards — the candidate made
this app *less* able to judge that nutrient, not more. Fixed by excluding
`insufficient_data`-after nutrients from `_gap_reduction` entirely; kept
as a permanent regression test
(`test_coverage_dilution_to_insufficient_data_is_never_counted_as_improvement`).

## Prompt 7: suggest recipes

`app/recommend_recipes.py` + `GET /api/recommendations/recipes`. Same
candidate → filter → simulate → score shape as prompt 6, generalised to
whole recipes at their own serving size. Reuses ownership/visibility
exactly as `routers/diary.py`'s existing `_rank_recipes_by_nutrient`
(own + shared + public, dietary-filtered) — broadened from one nutrient
to the full scoring engine, not reinvented.

**`is_stock` is the owning account's `is_system` flag** (matching
`routers/recipes.py`'s own `_recipe_out` exactly), not `import_slug`
presence — a real bug caught by this prompt's own tests (a test recipe
with `import_slug` set but an ordinary non-system owner was wrongly
reporting `is_stock=True` before the fix). `import_slug` is still the
right signal for a narrower question — whether the stock-recipe pipeline
ever computed `match_coverage_lines`/robustness data for this recipe at
all — used separately to decide whether `ingredient_confidence`/
`candidate_data_coverage` have anything real to feed the scoring engine.

Recipes carry no meal-type/category metadata at all (confirmed in the
prompt-1 audit), so `meal_type` filtering — which
`recommend_ingredients.py` gets from `candidate_metadata.py` — is a
documented gap here, not a silent no-op. Diversity (prompt 7's "avoid
near-duplicate recipes") is done by primary ingredient (the ingredient
contributing the most mass) — a real, inspectable signal, the same kind
`optimizer.py`'s own family-based swap logic already relies on, rather
than a fabricated "recipe similarity" score.

## Prompt 8: substitutions

`app/recommend_substitutions.py` + `GET /api/recommendations/substitutions`.
Removes an already-logged recipe hypothetically (the day's/plan's *other*
entries become the fixed baseline), ranks real replacement recipes at a
servings count chosen to land close to the original's own energy
contribution (nearest half-serving, clamped to 0.5-3.0x), and rejects
outright (not just penalises) any replacement that would push a nutrient
newly above its upper limit that wasn't already there. No apply endpoint
exists or is planned here — applying a suggestion is the existing
delete-then-recreate diary/meal-plan flow, on purpose (see the module
docstring: a second write path would be a duplicate source of truth for
the same mutation).

**A second real bug found by this prompt's own tests**: the function
initially trusted the caller-supplied `nutrients_by_food_id` to already
include the recipe *being replaced*'s own ingredients — true in the real
router (which loads the whole day before splitting out "the other
entries"), but not guaranteed for any other caller, and the test suite
caught it immediately by using a minimal fixture that didn't happen to
include it, silently zeroing that recipe's own contribution. Fixed by
defensively fetching missing ingredient nutrient data for the recipe
being replaced, the same `missing_food_ids` pattern `recommend_recipes.py`
already uses for its own candidates — now correct regardless of what a
caller supplies, not just the one router that happens to supply enough
by construction.

Recipe-visibility filtering here reused `recommend_recipes.py`'s
`visible_recipes`/`load_recipe_ingredients` directly (renamed from
`_visible_recipes`/`_recipe_ingredients` to make them a proper shared
API) rather than re-implementing the same own/shared/public/dietary
query a third time.

## Prompt 9: two-item combination optimiser

`app/recommend_pairs.py` + `GET /api/recommendations/pairs`. Deliberately
not unrestricted combinatorial search: a pair is only ever formed if
`candidate_metadata.py`'s own practical metadata already supports it (a
condiment paired with a non-condiment base — the general rule that
already covers "wholemeal toast + peanut butter" for free) or the exact
pair is named in `CURATED_PAIRS` (yoghurt + berries, lentils + spinach —
real, common combinations, not inferred from nutrient content). Both the
candidate pool (`CANDIDATE_POOL_SIZE`) and total pair evaluations
(`MAX_PAIR_EVALUATIONS`) are hard-bounded regardless of how large the
underlying shortfall candidate pool grows — `test_performance_bounded_
pair_evaluations` stress-tests this with 40 extra candidate foods and
asserts both the bound and a wall-clock ceiling.

The pair is scored as one candidate — `score_candidate` on the *combined*
before/after gaps — never as the sum of two independently-computed
scores. `test_combined_scoring_rejects_upper_limit_breach_even_when_
both_solo_are_fine` is the reason that distinction matters operationally,
not just conceptually: two foods that would each individually look like a
good, safe suggestion can still combine to push a nutrient over its upper
limit, and only scoring the real combined effect catches that.

## Bugfix: meal-scoped requests were comparing against the flat daily target

Found while starting prompt 10's frontend reconnaissance, not tied to a
single numbered prompt: `resolve_nutrient_target(key, profile,
AnalysisPeriod.MEAL, ...)` deliberately returns the *same* flat figure as
`AnalysisPeriod.DAY` (see prompt 2 — no automatic one-third-of-the-day
assumption), and `resolve_meal_comparison_target` already existed to let
a caller ask for "remaining room" explicitly. But none of the three
`recommend_*` suggestion modes actually called it — a lunch-scoped
`/api/recommendations/ingredients?meal=lunch` request was comparing the
meal's own totals against the whole day's target, so a nutrient already
fully covered at breakfast still showed as a shortfall at lunch.

Fixed with a new `nutrient_targets.adjust_target_for_remaining(target,
already_consumed)` that subtracts already-consumed amounts from a target's
lower/preferred/upper figures (never below zero, `None` fields stay
`None`), and a new `already_consumed_by_key: dict[str, float] | None`
parameter threaded through `suggest_ingredients`, `suggest_recipes`, and
`suggest_pairs` — applied only when `period == AnalysisPeriod.MEAL`, so
day/multi-day analysis is unaffected. `routers/recommendations.py`'s
`/ingredients` endpoint (the only one of the four that currently accepts
a `meal` parameter) now loads the whole day's entries, splits out "the
other meals," aggregates their nutrient totals, and passes that in as
`already_consumed_by_key`. `recommend_recipes.suggest_recipes` and
`recommend_pairs.suggest_pairs` accept the same parameter for when a
`meal` scope is added to those endpoints later, but nothing currently
passes it since neither endpoint takes a `meal` parameter yet.

Regression tests: `test_adjust_target_for_remaining_*` (`test_nutrient_
targets.py`), `test_meal_period_uses_remaining_room_not_flat_daily_target`
(`test_recommend_ingredients.py`), and `test_meal_scoped_request_uses_
remaining_room_not_flat_daily_target` (`test_recommendations_api.py`,
logging a fibre-filling breakfast and confirming a fibre-focused lunch
request comes back empty).

## Prompt 10 prep: recipe-detail and multi-day plan scopes

Before building the frontend, two backend gaps were closed so every page
prompt 10 lists would have something real to call:

- `GET /api/recommendations/ingredients` gained `recipe_id`+`servings` as
  a third scope (alongside `entry_date` and `start_date`+`end_date`) —
  the recipe's own scaled ingredients stand in for "the current meal",
  via a new `_recipe_as_items()` helper in `routers/recommendations.py`.
  No diary/meal-plan entry is involved at all.
- Both `/ingredients` and `/recipes` gained `start_date`+`end_date` (with
  `source=meal_plan`) as an alternative to `entry_date`, resolving
  `AnalysisPeriod.MULTI_DAY` with the correct `day_count` — this had
  been supported by `resolve_nutrient_target`/`suggest_ingredients`/
  `suggest_recipes` since prompt 2, just never wired to an endpoint.

Each endpoint now validates that exactly one scope was given (422
otherwise). See `test_recommendations_api.py`/`test_recommendations_
recipes_api.py` for the new scope-selection tests.

## Prompt 10: the frontend "Improve this…" experience

Three new frontend files, reused across all four pages the prompt names:

- `lib/nutrientLabels.ts` — nutrient key -> UK-English display label
  (`fiber_total` -> "Fibre"). The recommendation endpoints return bare
  keys, not names, so this is a small necessary frontend-only mapping —
  not a second source of nutritional truth, just presentation.
- `lib/components/RecommendationCard.svelte` — one card layout shared by
  ingredient/recipe/substitution suggestions: title, serving/energy,
  "helps close the remaining X gap" (never "treats X deficiency"),
  above-preferred/upper-limit warnings, a coverage/confidence note, and
  a native `<details>` disclosure for the full explanation and remaining
  shortfalls — expandable, not shown by default (prompt 10's "do not
  overwhelm by default").
- `lib/components/ImproveThis.svelte` — the actual panel: fetches
  nothing until opened, offers a priority preset (mirroring
  `recommend_recipes.GOAL_PRESETS`, a UI-only grouping kept in sync by
  hand, not a nutritional value), a max-extra-energy cap, and up to
  three mode tabs (add foods / suggest recipes / replace this meal —
  the last only shown when the caller supplies a substitutable entry
  id). Every apply action goes through a `confirm()` dialog first (the
  same convention `recipes/[id]` and `profile` pages already use for
  destructive actions) — required since applying changes a diary or
  plan. Applying and re-fetching afterwards is delegated to the parent
  page via `onApplyIngredient`/`onApplyRecipe`/`onApplySubstitution`
  callbacks, because only the parent knows *where* a day-level or
  plan-level addition should land — reusing the exact "wherever the
  entry form's date/meal selectors are currently set" convention the
  existing "Optimize this plan" feature already established, rather than
  inventing a second one.

Wired in:
- **Diary day** (`routes/diary`): "Improve this day" (day-scoped, lands
  in whatever meal the manual add-entry form currently has selected) and
  a per-meal "Improve this meal" (meal-scoped, remaining-room-aware —
  see the bugfix above — with "replace this meal" enabled whenever that
  meal contains a recipe entry).
- **Meal-plan day/multi-day summary** (`routes/meal-plan`, which is
  already a 7-day week view): "Improve this plan" for the whole visible
  week (`start_date`+`end_date`), "Improve this day" per weekday, and
  "Improve this meal" per meal-group within a day — same
  wherever-the-form-is-set convention as the existing plan optimiser.
- **Recipe detail** (`routes/recipes/[id]`): "Improve this recipe",
  ingredients-only (`allowRecipes={false}` — recommending a second
  recipe to eat alongside a recipe isn't wired, stated as a deliberate
  scope limit rather than silently omitted), applying via the same
  `addIngredient` the manual "Add ingredient" form already uses. Only
  shown to `recipe.is_owner`, matching every other edit affordance on
  that page.

Frontend tests: `lib/nutrientLabels.test.ts` (label mapping) and new
cases in `lib/api.test.ts` covering the three new scope shapes
(day/range/recipe), priority-nutrient comma-joining, and the
substitutions/recipes query-string wiring — component-level rendering
has no test harness in this repo yet (no `@testing-library/svelte`), so
`ImproveThis.svelte`/`RecommendationCard.svelte` were instead verified by
hand: full backend+frontend test suites (750 + 11 passing), a clean
`svelte-check`/production build, and a live walkthrough in a real
browser against a throwaway backend+SQLite instance (never the
project's own docker-compose stack) — logging a food, opening "Improve
this day"/"Improve this meal" on the diary page, confirming a
meal-restricted request correctly excludes a food outside its curated
meal types, creating a recipe and confirming "Improve this recipe"
recommends a real candidate, and confirming the empty-plan "Improve this
plan" panel renders its correct empty state.

## Prompt 11: safety, clinical boundaries and explanation rules

`app/recommendation_safety.py` centralises the rules every `recommend_*`
module and the router should already have been following implicitly,
rather than leaving each one to independently re-decide them:

- **Never diagnose / never claim to treat disease** — already enforced
  by `nutrient_gap_analysis.NutrientStatus`'s vocabulary and every
  `_explain()`'s "helps close the remaining X gap" wording; this module
  doesn't re-implement that, just documents it as the standing rule.
- **Never override a medically prescribed diet** — `dietary_filter.py`
  already never reads a `category="medical"` `DietaryConstraint`'s free
  text. What was missing: the recommendation response gave no visible
  sign such a constraint existed at all. Fixed with a new
  `MEDICAL_CONSTRAINT_PRESENT` warning code, detected by checking for any
  `medical`-category constraint row — never reading its `note`, only its
  existence.
- **Never recommend a supplement** — structurally true (`candidate_
  metadata.py`'s curated table has no supplement entries); no code
  change needed, stated here as the standing rule.
- **Never recommend exceeding a tolerable upper limit, treat pregnancy/
  lactation conservatively** — `recommendation_scoring.py`'s upper-limit
  penalty already discourages this, but "conservative" wasn't measurably
  different for a pregnant/lactating profile before this prompt. Added
  `nutrient_targets.PREGNANCY_LACTATION_UPPER_LIMIT_MARGIN` (0.9): every
  upper target/ceiling this app resolves for a pregnant or lactating
  profile is now scaled down by a further 10% — this app's own added
  caution, explicitly documented as *not* a sourced clinical figure in
  its own right (most nutrients here have no confirmed pregnancy-specific
  UL at all), paired with `PREGNANCY_CONSERVATIVE`/`LACTATION_
  CONSERVATIVE` warning codes so a caller can say so. This changed two
  existing test expectations (`test_profile_variants_resolve_different_
  drv`'s pregnant-iron-UL case) — a deliberate, documented behaviour
  change, not a regression.
- **Disable rather than guess for a profile a target formula wasn't
  built for** — a real gap found while building this: nothing anywhere
  guarded `energy_goal.py`/`protein_requirement.py`'s adult-only EER/
  protein formulas against a child profile. `assess_eligibility()` now
  returns `enabled=False` with a clear reason for any profile under
  `MINIMUM_RECOMMENDATION_AGE` (18), and all four `/api/recommendations/*`
  endpoints check this first and return an empty, `disabled_reason`-set
  response rather than calling into `suggest_ingredients`/etc at all.
  Missing `birth_year` is treated as "unknown", never assumed a child —
  disabling a real adult with an incomplete profile would be its own
  kind of unsafe guess.
- **Estimates/recipe-variation/absorption disclaimers, structured over
  prose** — `SafetyWarningCode` (a str enum) plus `WARNING_MESSAGES`;
  every enabled response carries a `warnings: list[str]` of codes
  (`data_is_estimate`/`absorption_varies` always, plus whichever of
  `pregnancy_conservative`/`lactation_conservative`/`medical_constraint_
  present` apply), and recipe-mode responses additionally get
  `recipe_nutrients_vary`. `IngredientSuggestionsOut`/`RecipeSuggestionsOut`/
  `SubstitutionSuggestionsOut`/`PairSuggestionsOut` all gained `warnings`
  and `disabled_reason` fields (additive — existing consumers unaffected).

Frontend: `lib/recommendationSafety.ts` mirrors the same code->message
mapping for display, and `ImproveThis.svelte` shows `disabled_reason`
prominently in place of the mode tabs/results (never alongside a false
"no suggestions" empty state), and `warnings` once per panel in a
collapsed `<details>` — never repeated on every card.

Tests: `test_recommendation_safety.py` (the module in isolation) and
`test_recommendations_safety_api.py` (all four endpoints, both the
under-18 disable and the medical-constraint/pregnancy warning paths),
plus new `test_nutrient_targets.py` cases for the upper-limit margin.

## Prompt 12: performance, caching and invalidation

**Decision: no caching layer was added.** This codebase has no existing
request-level cache anywhere (no Redis, no `lru_cache`-wrapped endpoint,
nothing) to build on, and every recommendation response depends on the
current diary/meal-plan state, which changes on every add/remove/mark-
eaten — a correct cache here would need exactly the invalidation surface
the prompt describes (profile, diary entries, meal plans, recipes, alias
mappings, food data, scoring parameters, target-reference data) and one
missed invalidation path would silently serve a stale/wrong
recommendation, which is a worse failure mode than "the request took an
extra 20ms". Benchmarked below, the uncached path is already fast enough
for interactive use, so the honest answer to "add caching only where
correct and useful" is: not yet useful, and risky to get wrong. If a
future profile shows this is actually slow at real scale, the version
constants below are already in place so a cache can be added with a
correct key rather than retrofitted.

What this feature does instead — **bounded, deterministic retrieval**,
which was already built prompts 6-9 and is verified here, not newly
added:
- `recommend_ingredients.CANDIDATE_POOL_PER_NUTRIENT`,
  `recommend_recipes.CANDIDATE_POOL_PER_NUTRIENT`, `recommend_pairs.
  CANDIDATE_POOL_SIZE`/`MAX_PAIR_EVALUATIONS` all cap how much of the
  catalog a single request ever touches, regardless of catalog size.
- `test_recommendation_performance.py`'s `test_ingredient_query_count_
  does_not_scale_with_catalog_size` proves this isn't just "there's a
  LIMIT in the code somewhere" — it actually counts SQL statements (via
  a `before_cursor_execute` listener) against a 20-food and a 300-food
  catalog and asserts the counts are within 2 of each other.
- `test_missing_robustness_data_degrades_gracefully`
  (`test_recommend_recipes.py`) confirms a recipe with no
  `RobustnessResult` row at all (never computed, not merely low) still
  comes back as a normal suggestion with `robustness_rating=None` and an
  honest note, never an error — prompt 12's "graceful degradation if
  robustness data are unavailable".

**Benchmark** (measured on this development machine, in-memory SQLite,
single request, no warm cache of any kind — see `test_recommendation_
performance.py` for the exact setup):

| Call | Catalog size | Wall time | SQL queries |
|---|---|---|---|
| `suggest_ingredients` | 301 foods | ~15ms | 4 |
| `suggest_recipes` | 120 stock recipes | ~31ms | 14 |
| `suggest_pairs` | 301 foods | <1ms | 3 |

301 foods and 120 recipes are already larger than this app's current
stock-recipe library — the first request is fast enough for interactive
use without any caching, confirming the decision above.

**Versioning, for if a cache is added later**:
`recommendation_scoring.RECOMMENDATION_MODEL_VERSION` — bump whenever
`ScoringWeights`' defaults or the scoring formula change materially. A
correct cache key would need this plus profile id, the selected meal/
day/plan identity, current nutrient totals (or an equivalent diary/
meal-plan version signal), dietary constraints, a candidate-catalogue
version (food/recipe/alias data), recommendation mode, energy cap, and
priority nutrients — exactly the prompt's list — and must never be a
globally-shared cache keyed on anything less specific than one profile's
one request.
plan" panel renders its correct empty state.
