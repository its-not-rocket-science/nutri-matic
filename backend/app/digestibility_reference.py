"""Reference DIAAS digestibility coefficients.

Two tiers, matched against a food's name in order (first match wins):

MEASURED: real per-amino-acid digestibility from a published study of that
specific food. Where the study didn't report all nine amino acids, the
missing ones are left null — scoring correctly refuses to compute a DIAAS
for a food if its limiting amino acid's digestibility is unknown, rather
than silently guessing. Deliberately small: most published digestibility
studies are either paywalled, report only 2-3 amino acids, or are pig/feed
studies on processed ingredients (soybean meal, corn gluten meal) that
don't represent the whole foods FDC lists under similar names — those were
found during research but excluded here rather than mismatched onto foods
they weren't measured on.

CATEGORY_FALLBACK: broad food-group coefficients from typical literature
ranges, applied uniformly across all nine amino acids (the same
simplification FAO permits when per-amino-acid data isn't available). Not
citable to a specific study — a coarse approximation so most ingested foods
get *some* usable DIAAS estimate, flagged digestibility_diaas_source="estimated"
so the UI can warn users it isn't food-specific data.
"""

# (requires, excludes, coefficients, citation): matches a food name if it
# contains ALL of the `requires` substrings and NONE of the `excludes`.
# coefficients is either a single float (applied to all 9 amino acids) or a
# partial dict keyed by reference_patterns.AMINO_ACIDS names — missing keys
# are left null. Checked in order, first match wins.
MEASURED: list[tuple[tuple[str, ...], tuple[str, ...], float | dict[str, float], str]] = [
    (
        ("egg, whole", "cooked"),
        ("substitute", "white", "yolk", "powder", "dried"),
        {
            "isoleucine": 0.854,
            "leucine": 0.876,
            "lysine": 0.889,
            "met_cys": 0.859,
            "phe_tyr": 0.956,
            "threonine": 0.962,
            "valine": 0.866,
        },
        "Kashyap et al. 2018, Am J Clin Nutr 108(5):980-987 (human ileal, dual "
        "stable isotope; cooked egg — raw egg protein is less digestible and "
        "not covered by this value). Histidine and tryptophan not reported.",
    ),
    (
        # "meat only, cooked" is USDA's phrasing for plain cooked cuts, which
        # excludes breaded/processed/branded chicken products and raw entries
        ("chicken", "meat only, cooked"),
        ("with added solution",),
        {
            "isoleucine": 0.888,
            "leucine": 0.891,
            "lysine": 0.955,
            "met_cys": 0.927,
            "phe_tyr": 0.944,
            "threonine": 0.937,
            "valine": 0.896,
        },
        "Kashyap et al. 2018, Am J Clin Nutr 108(5):980-987 (human ileal, dual "
        "stable isotope; cooked chicken meat). Histidine and tryptophan not reported.",
    ),
]

# (keyword, coefficient) — broad category fallback, "estimated" tier.
# Checked only after MEASURED finds no match, in order, first match wins.
CATEGORY_FALLBACK: list[tuple[str, float]] = [
    ("whey", 0.95),
    ("casein", 0.95),
    ("milk", 0.95),
    ("cheese", 0.95),
    ("yogurt", 0.95),
    ("yoghurt", 0.95),
    ("cream", 0.95),
    ("egg", 0.90),
    ("beef", 0.90),
    ("pork", 0.90),
    ("lamb", 0.90),
    ("veal", 0.90),
    ("venison", 0.90),
    ("chicken", 0.90),
    ("turkey", 0.90),
    ("duck", 0.90),
    ("sausage", 0.90),
    ("bacon", 0.90),
    ("ham,", 0.90),
    ("fish", 0.90),
    ("salmon", 0.90),
    ("tuna", 0.90),
    ("cod", 0.90),
    ("shrimp", 0.90),
    ("crab", 0.90),
    ("shellfish", 0.90),
    ("tilapia", 0.90),
    ("trout", 0.90),
    ("lobster", 0.90),
    ("scallop", 0.90),
    ("bean", 0.80),
    ("lentil", 0.80),
    ("pea,", 0.80),
    ("peas,", 0.80),
    ("chickpea", 0.80),
    ("soy", 0.80),
    ("tofu", 0.80),
    ("tempeh", 0.80),
    ("nut,", 0.80),
    ("nuts,", 0.80),
    ("almond", 0.80),
    ("peanut", 0.80),
    ("walnut", 0.80),
    ("cashew", 0.80),
    ("pistachio", 0.80),
    ("seed", 0.80),
    ("sesame", 0.80),
    ("sunflower", 0.80),
    ("wheat", 0.85),
    ("rice", 0.85),
    ("oat", 0.85),
    ("corn", 0.85),
    ("maize", 0.85),
    ("barley", 0.85),
    ("rye", 0.85),
    ("quinoa", 0.85),
    ("flour", 0.85),
    ("bread", 0.85),
    ("pasta", 0.85),
    ("noodle", 0.85),
    ("cereal", 0.85),
    ("potato", 0.80),
    ("vegetable", 0.80),
    ("carrot", 0.80),
    ("broccoli", 0.80),
    ("spinach", 0.80),
    ("tomato", 0.80),
    ("pepper,", 0.80),
    ("onion", 0.80),
    ("lettuce", 0.80),
    ("cabbage", 0.80),
    ("fruit", 0.80),
    ("apple", 0.80),
    ("banana", 0.80),
    ("orange", 0.80),
    ("berry", 0.80),
    ("berries", 0.80),
    ("grape", 0.80),
    ("melon", 0.80),
]


def lookup(food_name: str) -> tuple[float | dict[str, float], str] | None:
    """Return (coefficients, source) for a food name, or None if no rule matches.

    coefficients is a single float (apply to all amino acids) or a partial
    dict (missing amino acids should be left null downstream)."""
    name = food_name.lower()
    for requires, excludes, coefficients, _citation in MEASURED:
        if all(kw in name for kw in requires) and not any(kw in name for kw in excludes):
            return coefficients, "measured"
    for keyword, coefficient in CATEGORY_FALLBACK:
        if keyword in name:
            return coefficient, "estimated"
    return None
