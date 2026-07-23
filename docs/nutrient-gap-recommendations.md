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
