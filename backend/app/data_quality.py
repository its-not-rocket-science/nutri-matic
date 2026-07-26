"""Detects nutrient values that are implausible by orders of magnitude —
almost certainly a source data error (a decimal/unit slip on the
manufacturer's or USDA's end), not a real property of the food.

USDA FoodData Central's Branded Foods dataset is manufacturer-submitted
and not independently verified the way Foundation/SR Legacy data is. A
handful of rows report a nutrient amount thousands of times its own daily
reference value — e.g. a pie crust listing 576,923 mcg of biotin per
100g (19,000x the adult DRV) is not a real, unusually biotin-rich food;
it's a data entry error. No real food gets anywhere near that scale for
most nutrients — but "most" is doing real work in that sentence: dried
seaweed is legitimately ~1000x the DRV for iodine per 100g, and that's a
real food, not an error. A single blanket multiple can't be right for
both of those at once — see PLAUSIBILITY_MULTIPLE below.

Public-launch hardening prompt 3 tightened this from a single flat
1000x threshold after a real production case: a branded food listing
29,733 mcg of biotin per 100g (991x the 30mcg DRV) passed the old
threshold — just under it, not because it was plausible, but because
1000x was calibrated to comfortably clear iodine-in-seaweed and ended up
far too loose for a nutrient (biotin) with no legitimately-concentrated
whole-food source at all. Every tracked nutrient now gets its own
ceiling, documented per-nutrient below, rather than one number applied
uniformly regardless of what's actually plausible for that nutrient.

Two tiers, not one:

- EXCLUDE (`is_implausible`/`implausibility_reason`, unchanged public
  API — every existing caller keeps working unmodified): excluded from
  totals, gap analysis, and candidate ranking. Still shown, loudly
  labelled, wherever the food's own data is displayed directly.
- REVIEW (`review_reason`, new, lower than EXCLUDE): NOT excluded from
  anything — a value in this band still counts normally everywhere.
  Only surfaces in the data-quality audit report
  (app/data_quality_audit.py) as "worth a human's attention", for
  values unusual enough to be worth a look without being confident
  enough to actively exclude. This is what lets a genuinely
  nutrient-dense whole food (liver, brazil nuts, oily fish) or a
  legitimate fortified/concentrated product surface for visibility
  without being silently discarded the way EXCLUDE is for data errors.

This is deliberately one of the few places raw source data is NOT used
as-is for calculations — everywhere else in this app (see
docs/brand-identity.md, methodology.py) the rule is "trust the source,
label the confidence." Here that rule would actively mislead (an
optimizer suggestion to "add 30g of pie crust for +576,923 percentage
points of biotin" is not information, it's noise) — so implausible
values are excluded from totals and suggestions, but never silently
deleted or corrected.
"""

from dataclasses import dataclass

from .nutrients import resolve_drv

# Applied to every tracked nutrient without an explicit override below.
# Two orders of magnitude above the ~10-50x DRV per 100g that even a
# genuinely concentrated whole food or fortified product realistically
# reaches (brazil nuts/selenium ~25-35x, liver/B12 ~40-65x, flaxseed/ALA
# ~25x) — comfortably clears real concentrated foods while still
# catching a source error far below the old 1000x's near-miss on a
# 991x-DRV branded biotin row.
DEFAULT_EXCLUDE_MULTIPLE = 100
# Below EXCLUDE, above this: not excluded from anything, just surfaced
# in the audit report as worth a look. Roughly "denser than an ordinary
# whole food, but not yet confidently a data error."
DEFAULT_REVIEW_MULTIPLE = 20

# Per-nutrient overrides — only where DEFAULT_EXCLUDE_MULTIPLE would be
# wrong for a *real, documented* reason, not a guess. Every entry here
# must have a cited real-world food justifying it.
EXCLUDE_MULTIPLE_OVERRIDES: dict[str, float] = {
    # Dried seaweed/kelp (nori, kombu, dulse) is a real, commonly-eaten
    # food that legitimately runs into the thousands of mcg of iodine
    # per 100g dry weight — commonly cited figures for kombu/kelp are in
    # the 1,500-4,500 mcg/100g range (roughly 10-30x the ~140mcg adult
    # DRV used here), and some dried preparations are cited well above
    # that. A ceiling generous enough to never falsely exclude a real
    # seaweed product, while still catching a genuine order-of-magnitude
    # data error (a value that would require literally being pure
    # iodine crystal by weight).
    "iodine": 5000,
}
REVIEW_MULTIPLE_OVERRIDES: dict[str, float] = {
    "iodine": 25,
}


def _exclude_multiple(nutrient_key: str) -> float:
    return EXCLUDE_MULTIPLE_OVERRIDES.get(nutrient_key, DEFAULT_EXCLUDE_MULTIPLE)


def _review_multiple(nutrient_key: str) -> float:
    return REVIEW_MULTIPLE_OVERRIDES.get(nutrient_key, DEFAULT_REVIEW_MULTIPLE)


@dataclass(frozen=True)
class PlausibilityAssessment:
    multiple: float | None  # amount_per_100g / DRV — None if no DRV to compare against
    disposition: str  # "ok" | "review" | "excluded"
    reason: str | None  # human-readable, set for "review"/"excluded" only


def assess_plausibility(nutrient_key: str, amount_per_100g: float) -> PlausibilityAssessment:
    """The single place both tiers are decided — implausibility_reason/
    is_implausible and the audit report both read this, so the two can
    never silently disagree about where a value falls."""
    if amount_per_100g <= 0:
        return PlausibilityAssessment(multiple=None, disposition="ok", reason=None)
    drv = resolve_drv(nutrient_key, profile=None)
    if not drv:
        return PlausibilityAssessment(multiple=None, disposition="ok", reason=None)

    multiple = amount_per_100g / drv
    exclude_at = _exclude_multiple(nutrient_key)
    if multiple >= exclude_at:
        return PlausibilityAssessment(
            multiple=multiple, disposition="excluded",
            reason=(
                f"{multiple:,.0f}x the daily reference value per 100g — almost certainly a source "
                "data error, not a real property of this food. Excluded from totals, gap suggestions, "
                "and the optimiser; shown here only for transparency."
            ),
        )
    review_at = _review_multiple(nutrient_key)
    if multiple >= review_at:
        return PlausibilityAssessment(
            multiple=multiple, disposition="review",
            reason=(
                f"{multiple:,.0f}x the daily reference value per 100g — unusually concentrated. "
                "Still counted normally; flagged here for a data-quality review, not excluded."
            ),
        )
    return PlausibilityAssessment(multiple=multiple, disposition="ok", reason=None)


def implausibility_reason(nutrient_key: str, amount_per_100g: float) -> str | None:
    """None if the amount looks plausible (or there's no DRV to check it
    against — nothing to flag). Otherwise a human-readable explanation to
    display directly alongside the value. Unchanged public signature —
    every existing caller (aggregation.py, diary.py, recipes.py,
    optimizer.py, the recommend_*.py family) keeps working unmodified;
    only the threshold that decides the answer changed."""
    assessment = assess_plausibility(nutrient_key, amount_per_100g)
    return assessment.reason if assessment.disposition == "excluded" else None


def is_implausible(nutrient_key: str, amount_per_100g: float) -> bool:
    return implausibility_reason(nutrient_key, amount_per_100g) is not None
