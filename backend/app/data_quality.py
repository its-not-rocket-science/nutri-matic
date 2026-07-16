"""Detects nutrient values that are implausible by orders of magnitude —
almost certainly a source data error (a decimal/unit slip on the
manufacturer's or USDA's end), not a real property of the food.

USDA FoodData Central's Branded Foods dataset is manufacturer-submitted
and not independently verified the way Foundation/SR Legacy data is. A
handful of rows report a nutrient amount thousands of times its own daily
reference value — e.g. a pie crust listing 576,923 mcg of biotin per
100g (19,000x the adult DRV) is not a real, unusually biotin-rich food;
it's a data entry error. No real food, including concentrated supplements
or fortified products, runs anywhere near that scale — those top out
around 10-50x DRV per 100g. A threshold two orders of magnitude above
that (1000x) comfortably separates "genuinely nutrient-dense" from
"someone's data entry slipped a decimal or a unit."

This is deliberately the one place raw source data is NOT used as-is for
calculations — everywhere else in this app (see docs/brand-identity.md,
methodology.py) the rule is "trust the source, label the confidence."
Here that rule would actively mislead (an optimizer suggestion to "add
30g of pie crust for +576,923 percentage points of biotin" is not
information, it's noise) — so implausible values are excluded from
totals and suggestions, but never silently deleted or corrected: they're
still shown, loudly labelled, wherever the food's own data is displayed
directly (its provenance/nutrient page), exactly like the measured/
estimated tagging used elsewhere.
"""

from .nutrients import resolve_drv

IMPLAUSIBLE_DRV_MULTIPLE = 1000


def implausibility_reason(nutrient_key: str, amount_per_100g: float) -> str | None:
    """None if the amount looks plausible (or there's no DRV to check it
    against — nothing to flag). Otherwise a human-readable explanation to
    display directly alongside the value."""
    if amount_per_100g <= 0:
        return None
    drv = resolve_drv(nutrient_key, profile=None)
    if not drv:
        return None
    multiple = amount_per_100g / drv
    if multiple < IMPLAUSIBLE_DRV_MULTIPLE:
        return None
    return (
        f"{multiple:,.0f}x the daily reference value per 100g — almost certainly a source "
        "data error, not a real property of this food. Excluded from totals, gap suggestions, "
        "and the optimiser; shown here only for transparency."
    )


def is_implausible(nutrient_key: str, amount_per_100g: float) -> bool:
    return implausibility_reason(nutrient_key, amount_per_100g) is not None
