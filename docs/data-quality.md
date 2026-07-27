# Nutrient data quality: coverage and plausibility

Public-launch hardening prompt 3. Fixes two related, but distinct,
production symptoms:

1. The seeded demo diary presented **"Biotin (B7) — 0% of target"** when
   none of that day's logged foods actually had reliable biotin data —
   missing data displayed as a confirmed zero.
2. A branded food reporting **29,733 mcg of biotin per 100g** (991x the
   30mcg DRV) passed the old flat 1000x plausibility threshold — just
   under it — and could surface in gap-suggestion candidate rankings.

## Coverage-aware display (fixes symptom 1)

`app/nutrient_gap_analysis.py` already had a coverage concept
(`coverage_for_nutrient`, made public by this prompt — see its
docstring) for the newer recommendation engine. The legacy diary/recipe
display path (`schemas.NutrientAmountOut`/`TrendNutrientOut`,
`routers/diary.py`, `routers/recipes.py`) didn't use it at all —
`percent_drv` was plain `amount / drv * 100` with no notion of how much
of the underlying mass actually reported the nutrient.

Both schemas gained:

- `coverage: float` — fraction (0-1) of the underlying mass with a
  known, plausible value for this nutrient. Always 1.0 for a single
  food's own per-100g row (nothing to aggregate); lower for an
  aggregated total (diary day, recipe, trend bucket) where some
  contributing item didn't report it.
- `insufficient_data_reason: str | None` — set instead of trusting a
  low-coverage `percent_drv` (which is `None` whenever this is set).
  Below `nutrient_gap_analysis.MINIMUM_COVERAGE_FOR_STATUS` (0.5),
  `percent_drv`/`avg_percent_drv` is withheld rather than shown.

A genuine measured zero (every contributing item explicitly reports 0)
is unaffected — `coverage` is `1.0` in that case, so it still shows as a
real 0%, never relabelled "insufficient data". Only a nutrient with too
little of the underlying mass reporting it at all gets the new
treatment. See `tests/test_nutrient_data_quality_regression.py` for the
full set of cases (missing entirely, true zero, high partial coverage,
low partial coverage, the live demo account end-to-end).

`routers/diary.py::_find_worst_gap` (the "biggest gap" picker used by
`/gap-suggestions`, `/meal-optimize`, and the homepage widget) already
filtered on `percent_drv is not None` — so an insufficient-data nutrient
is automatically excluded from ever being picked as "the day's biggest
gap" once `percent_drv` is correctly withheld for it. No separate fix
needed there.

Frontend: `NutrientBars.svelte` gained an explicit "insufficient data"
row (distinct from the existing implausible-value warning — different
color/semantics, this isn't a data error, just not enough evidence),
and every direct `percent_drv?.toFixed(...)` call (which would have
rendered `"undefined%"` once `percent_drv` could be `null` alongside a
non-null `adult_drv`) was replaced with an explicit `!== null` check —
home page, trends chart included.

## Nutrient-aware plausibility thresholds (fixes symptom 2)

`app/data_quality.py` replaced the single flat `IMPLAUSIBLE_DRV_MULTIPLE
= 1000` with two tiers, per-nutrient rather than one number applied to
everything:

- **EXCLUDE** (`DEFAULT_EXCLUDE_MULTIPLE = 100`): excluded from totals,
  gap analysis, and candidate ranking — same behaviour
  `is_implausible`/`implausibility_reason` always had, just a tighter
  default. Comfortably clears every real concentrated whole food this
  session could confirm (brazil nuts/selenium ~25-35x, liver/B12
  ~40-65x, flaxseed/ALA ~25x), while catching the reported 991x biotin
  case with wide margin (biotin has no legitimately-concentrated
  whole-food source at all).
- **REVIEW** (`DEFAULT_REVIEW_MULTIPLE = 20`, new): not excluded from
  anything — still counts normally everywhere. Only surfaces in the new
  audit report (below) as worth a look.

**Per-nutrient override**: `iodine` gets a much higher EXCLUDE ceiling
(5000x) — dried seaweed/kelp is a real, commonly-eaten food that
legitimately runs into the thousands of mcg per 100g (commonly-cited
kombu/kelp figures are ~1,500-4,500 mcg/100g, ~10-30x the ~140mcg adult
DRV used here). The default 100x would have falsely excluded real
seaweed data. No other tracked nutrient needed an override — every
other legitimately-concentrated food this session could confirm stays
under the 100x default. Add further overrides here, not by loosening
the default, if a future real food is found to need one — each entry in
`EXCLUDE_MULTIPLE_OVERRIDES`/`REVIEW_MULTIPLE_OVERRIDES` must cite a
real food justifying it (see the comments there).

`is_implausible`/`implausibility_reason`'s public signature is
unchanged — every existing caller (`aggregation.py`, `diary.py`,
`recipes.py`, `optimizer.py`, the `recommend_*.py` family) keeps working
unmodified; only the threshold each one reads changed.

**Not implemented, deliberately scoped out**: source-aware caution
(treating `Food.data_type == "branded_food"` more strictly than
Foundation/SR Legacy) at the EXCLUDE/REVIEW decision itself. The
per-nutrient ceiling redesign alone already fixes the reported case
regardless of source (biotin's tight default excludes 991x whoever
reported it). Threading `data_type` through the ~20 existing
`is_implausible`/`aggregate_nutrients` call sites for a refinement not
required to fix the reported bug was judged not worth the blast radius
for this round — the audit report below at least gives source-grouped
visibility without touching the totals/scoring path.

## Data-quality audit report — `app/data_quality_audit.py`

```
python -m app.data_quality_audit                          # every review/excluded row
python -m app.data_quality_audit --disposition excluded    # excluded rows only
```

Read-only — lists every `FoodNutrient` row `assess_plausibility` flags
as `"review"` or `"excluded"` (never `"ok"`), with the food's
`data_type` (branded vs. Foundation/SR Legacy), the multiple of DRV, and
the disposition — plus summary counts by nutrient and by source. Both
the audit report and `is_implausible`/`implausibility_reason` read the
same `assess_plausibility` function, so they can never silently
disagree about where a value falls.
