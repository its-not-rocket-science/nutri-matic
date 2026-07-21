"""Reference digestibility coefficients for DIAAS and PDCAAS.

Each score method has two tiers, matched against a food's name in order
(first match wins):

MEASURED_*: real digestibility from a published study of that specific
food (or, for PDCAAS, the standard literature reference table — see note
below). Deliberately small — most published digestibility studies are
either paywalled, report only 2-3 amino acids, or are pig/feed studies on
processed ingredients (soybean meal, corn gluten meal) that don't represent
the whole foods FDC lists under similar names. Those were found during
research but excluded here rather than mismatched onto foods they weren't
measured on. Where a source didn't report every amino acid, the missing
ones are left null — DIAAS scoring correctly refuses to compute a score
for a food if its limiting amino acid's digestibility is unknown, rather
than silently guessing.

CATEGORY_FALLBACK: broad food-group coefficients from typical literature
ranges, applied uniformly (as a single overall coefficient for PDCAAS, or
broadcast across all 9 amino acids for DIAAS — the same simplification FAO
permits when per-amino-acid data isn't available). Not citable to a
specific study — a coarse approximation so most ingested foods get *some*
usable score, flagged digestibility_*_source="estimated" so the UI can
warn users it isn't food-specific data. Shared between DIAAS and PDCAAS
since both represent the same underlying idea (how digestible is this
food's protein) at the same coarse grain.

MEASURED_PDCAAS provenance note: except for rice (cross-checked directly
against an FAO document citing WHO 1985 / Hopkins 1981 human data), these
values come from the "true digestibility" table commonly reproduced across
nutrition literature and traced to FAO (1991) *Protein Quality Evaluation*,
Rome. Every attempt to fetch that report or a reproduction of its exact
table directly (ScienceDirect, the original Journal of Nutrition paper,
Genesis R&D, an ADPI PDF) was blocked or unreadable; the values here are
corroborated by the numbers being consistently reproduced across multiple
independent secondary sources, not independently verified against the
primary document page-by-page.
"""

# (requires, excludes, coefficients, citation): matches a food name if it
# contains ALL of the `requires` substrings and NONE of the `excludes`.
# coefficients is either a single float (applied to all 9 amino acids) or a
# partial dict keyed by reference_patterns.AMINO_ACIDS names — missing keys
# are left null. Checked in order, first match wins.
MEASURED_DIAAS: list[tuple[tuple[str, ...], tuple[str, ...], float | dict[str, float], str]] = [
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

# (prefixes, excludes, coefficient, citation): matches a food name if it
# STARTS WITH any of `prefixes` and contains NONE of the `excludes`. Prefix
# anchoring (rather than a bare substring) is what keeps "Rice," (the plain
# commodity) from also matching "Babyfood, cereal, rice, ..." or "Beverages,
# rice milk, ...", which a plain "rice" substring would. Checked in order,
# first match wins. Single overall crude-protein digestibility coefficient
# per food — see the module docstring for sourcing/provenance.
MEASURED_PDCAAS: list[tuple[tuple[str, ...], tuple[str, ...], float, str]] = [
    (
        ("egg, whole",),
        ("substitute", "white", "yolk", "powder", "dried", "raw"),
        0.97,
        "Classic FAO (1991) true digestibility table, as widely reproduced "
        "in nutrition literature.",
    ),
    (
        ("rice,",),
        (),
        0.88,
        "FAO doc fdc_id t0567e (Rice in Human Nutrition), Table 28, citing "
        "Hopkins 1981 / WHO 1985 — human/mixed data, mean digestibility of "
        "milled rice.",
    ),
    (
        ("corn, sweet", "corn, dried", "corn, white", "corn, yellow"),
        (),
        0.85,
        "Classic FAO (1991) true digestibility table (maize), as widely "
        "reproduced in nutrition literature.",
    ),
    (
        ("oats,",),
        (),
        0.86,
        "Classic FAO (1991) true digestibility table (oatmeal), as widely "
        "reproduced in nutrition literature.",
    ),
    (
        ("peanuts,", "peanut,"),
        (),
        0.95,
        "Classic FAO (1991) true digestibility table (peanut butter), as "
        "widely reproduced in nutrition literature.",
    ),
    (
        ("soybeans,",),
        (),
        0.90,
        "Classic FAO (1991) true digestibility table (soybean flour "
        "86% / soy protein isolate 95%, midpoint used since whole soybeans "
        "aren't distinguished in that source), as widely reproduced in "
        "nutrition literature.",
    ),
    (
        ("beans,",),
        ("snap", "wax", "yellow bean"),
        0.78,
        "Classic FAO (1991) true digestibility table (kidney beans), as "
        "widely reproduced in nutrition literature.",
    ),
    (
        ("lentils,", "chickpeas,"),
        (),
        0.78,
        "Classic FAO (1991) true digestibility table (beans, as a legume "
        "proxy — lentils/chickpeas not separately listed in that source), "
        "as widely reproduced in nutrition literature.",
    ),
]

# (prefixes, coefficient) — same idea as CATEGORY_FALLBACK below (broad,
# "estimated" tier, not citable to a specific study), but prefix-anchored
# like MEASURED_PDCAAS rather than bare-substring. A plain substring
# ("butter" anywhere in the name) is unsafe here: it also matches
# "Butterfinger Bar", "Butterscotch", "Butterbur" (a plant), margarine
# spreads, and peanut/almond/cocoa butter — none of which are dairy
# butter. Checked before CATEGORY_FALLBACK_SUBSTRING, first match wins.
#
# Coefficients extend existing precedent rather than introduce new
# methodology: 0.95 already covers every other dairy category here
# (milk/cheese/cream/yogurt) and butter's residual protein is the same
# casein/whey; 0.80 already covers several individually-named spices
# (cumin, turmeric, paprika, curry) as "general plant food" — this just
# widens that same bucket to the FDC "Spices," category as a whole
# instead of naming each one.
CATEGORY_FALLBACK_PREFIX: list[tuple[tuple[str, ...], float]] = [
    (("butter,",), 0.95),
    (("spices,",), 0.80),
]

# (keyword, coefficient) — broad category fallback, "estimated" tier.
# Checked only after the MEASURED_* tier finds no match, in order, first
# match wins.
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
    ("cauliflower", 0.80),
    ("spinach", 0.80),
    ("tomato", 0.80),
    ("pepper,", 0.80),
    ("peppers,", 0.80),
    ("onion", 0.80),
    ("shallot", 0.80),
    ("garlic", 0.80),
    ("ginger", 0.80),
    ("mushroom", 0.80),
    ("lettuce", 0.80),
    ("cabbage", 0.80),
    ("parsley", 0.80),
    ("cilantro", 0.80),
    ("coriander", 0.80),
    ("thyme", 0.80),
    ("cumin", 0.80),
    ("turmeric", 0.80),
    ("paprika", 0.80),
    ("curry", 0.80),
    ("fruit", 0.80),
    ("apple", 0.80),
    ("banana", 0.80),
    ("orange", 0.80),
    ("berry", 0.80),
    ("berries", 0.80),
    ("grape", 0.80),
    ("melon", 0.80),
    # found missing while checking the real live database's remaining
    # DIAAS/PDCAAS gaps — same "general plant food" tier as the entries
    # just above, just omitted from the original list rather than a new
    # category being invented
    ("celery", 0.80),
    ("cucumber", 0.80),
    ("squash", 0.80),
    ("zucchini", 0.80),
    ("courgette", 0.80),
    ("olive", 0.80),
    ("watercress", 0.80),
    ("rutabaga", 0.80),
    ("rosemary", 0.80),
    ("basil", 0.80),
    ("dill", 0.80),
    ("lemon", 0.80),
    ("lime", 0.80),
    # honey is a trace-protein edge case (0.3g/100g) rather than a real
    # "food category" the way the others above are, but it's a natural
    # product with the same coarse-estimate rationale, not a manufactured
    # ingredient — included for consistency rather than left as a gap
    ("honey", 0.80),
    # found while checking the real live database's remaining DIAAS/PDCAAS
    # gaps — these had complete amino acid data already but no digestibility
    # coefficient at all, purely because their name doesn't contain any
    # existing keyword above ("bulgur" is a wheat product, "falafel" a
    # legume-based fried food, "muffin" a baked grain good, "avocado" a
    # fruit) — same tier as their closest existing category, not a new one
    ("bulgur", 0.85),
    ("falafel", 0.80),
    ("muffin", 0.85),
    ("avocado", 0.80),
    # same pattern, next round of remaining real DIAAS/PDCAAS blockers:
    # complete amino acid data already, just no digestibility coefficient
    # because the name doesn't contain any existing keyword
    ("couscous", 0.85),  # wheat semolina, same tier as bulgur/wheat
    ("crouton", 0.85),  # baked bread, same tier as bread
    ("liver", 0.90),  # organ meat, similar digestibility to muscle meat
    ("mussel", 0.90),  # shellfish, same tier as the other shellfish above
    ("edamame", 0.80),  # immature soybean, same tier as soy
]


def _category_fallback(name: str) -> tuple[float, str] | None:
    for prefixes, coefficient in CATEGORY_FALLBACK_PREFIX:
        if any(name.startswith(p) for p in prefixes):
            return coefficient, "estimated"
    for keyword, coefficient in CATEGORY_FALLBACK:
        if keyword in name:
            return coefficient, "estimated"
    return None


def lookup_diaas(food_name: str) -> tuple[float | dict[str, float], str] | None:
    """Return (coefficients, source) for a food name, or None if no rule matches.

    coefficients is a single float (apply to all amino acids) or a partial
    dict (missing amino acids should be left null downstream)."""
    name = food_name.lower()
    for requires, excludes, coefficients, _citation in MEASURED_DIAAS:
        if all(kw in name for kw in requires) and not any(kw in name for kw in excludes):
            return coefficients, "measured"
    return _category_fallback(name)


def lookup_pdcaas(food_name: str) -> tuple[float, str] | None:
    """Return (coefficient, source) for a food name, or None if no rule matches."""
    name = food_name.lower()
    for prefixes, excludes, coefficient, _citation in MEASURED_PDCAAS:
        if any(name.startswith(p) for p in prefixes) and not any(kw in name for kw in excludes):
            return coefficient, "measured"
    return _category_fallback(name)
