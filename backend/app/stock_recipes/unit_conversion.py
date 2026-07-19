"""Converts a parsed ingredient's quantity+unit to grams.

Nothing in the rest of the app does household-unit conversion — every
existing RecipeIngredient is already in grams (built one food at a time
through the recipe editor, where the user types a gram amount directly).
This module exists purely for the stock-recipe importer, and every
non-exact conversion is provenance-tracked: convert() always returns a
`confidence` tier and, for anything beyond an exact mass unit, a
`conversion_assumptions` dict recording exactly what was assumed — nothing
here is silently guessed.

Confidence tiers:
    "exact"     — g/kg/oz/lb: no assumption made, this is just unit maths.
    "measured"  — a standard volume-to-mass conversion (tsp/tbsp/cup -> ml,
                  then a density either looked up for this specific
                  ingredient or falling back to water's) or a specific
                  ingredient+count unit-weight (e.g. "egg" -> 50g) drawn
                  from commonly published reference figures.
    "estimated" — a generic, not-ingredient-specific unit-weight (e.g. an
                  unrecognised "tin" defaulting to 400g) — the kind of
                  broad approximation prompt section 7 asks to flag as an
                  estimate rather than conceal.

A bare count with no recognisable ingredient-specific or generic weight
(e.g. "3 lengths of X" for an ingredient never seen before) returns None —
never a fabricated number. That ingredient line is then unresolved for
mass, not silently dropped or guessed at (see food_matching.py /
pipeline.py for how an unresolved-for-mass line is handled).
"""

from __future__ import annotations

from dataclasses import dataclass

MASS_UNIT_GRAMS: dict[str, float] = {"g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}
VOLUME_UNIT_ML: dict[str, float] = {"ml": 1.0, "l": 1000.0, "tsp": 5.0, "tbsp": 15.0, "cup": 240.0}

# grams per ml, by ingredient-name keyword — deliberately small and only
# for genuinely different-density staples; anything not listed falls back
# to water's density (1.0 g/ml), which is a reasonable approximation for
# most liquids used by the tsp/tbsp/cup (stock, milk, vinegar, sauces) but
# a poor one for e.g. flour or sugar, which is exactly why those are listed.
DENSITY_G_PER_ML: dict[str, float] = {
    "flour": 0.53,
    "sugar": 0.85,
    "brown sugar": 0.93,
    "icing sugar": 0.56,
    "oil": 0.92,
    "honey": 1.42,
    "butter": 0.96,
    "rice": 0.85,
    "oats": 0.41,
    "grated cheese": 0.4,
    "breadcrumbs": 0.44,
    "cocoa": 0.53,
}

# grams for one unit of a specific ingredient — checked before the generic
# COUNT_UNIT_GRAMS_DEFAULT fallback below. Figures are ordinary published
# reference averages (e.g. USDA/FSA portion-size tables), not from any one
# recipe. Keys are (ingredient-name keyword, unit) — unit is None for a
# bare count ("1 onion", "2 eggs").
INGREDIENT_UNIT_WEIGHTS: dict[tuple[str, str | None], float] = {
    ("onion", None): 110.0,
    ("shallot", None): 40.0,
    ("garlic", "clove"): 5.0,
    ("garlic", "bulb"): 50.0,
    ("egg", None): 50.0,
    ("lemon", None): 60.0,
    ("lime", None): 45.0,
    ("carrot", None): 60.0,
    ("potato", None): 150.0,
    ("tomato", None): 100.0,
    ("courgette", None): 200.0,
    ("pepper", None): 120.0,
    ("chilli", None): 15.0,
    ("chili", None): 15.0,
    ("avocado", None): 150.0,
    ("banana", None): 120.0,
    ("apple", None): 130.0,
    ("celery stick", None): 40.0,
    ("spring onion", None): 15.0,
    ("bay leaf", None): 0.2,
    ("stock cube", None): 10.0,
    ("bread", "slice"): 35.0,
    ("bacon", "slice"): 25.0,
    ("cheese", "slice"): 20.0,
    ("chopped tomatoes", "tin"): 400.0,
    ("plum tomatoes", "tin"): 400.0,
    ("tomatoes", "tin"): 400.0,
    ("beans", "tin"): 400.0,
    ("chickpeas", "tin"): 400.0,
    ("lentils", "tin"): 400.0,
    ("coconut milk", "tin"): 400.0,
    ("tuna", "tin"): 145.0,
    ("sweetcorn", "tin"): 300.0,
    ("butter", "knob"): 15.0,
    ("ginger", "knob"): 15.0,
    # found missing while running the real pipeline against a full FDC
    # catalog — these all matched a real Food fine but had no bare-count
    # weight to convert to grams
    ("leek", None): 150.0,
    ("cucumber", None): 300.0,
    ("bagel", None): 90.0,
    ("crumpet", None): 45.0,
    ("bread roll", None): 60.0,
    ("pitta", None): 65.0,
    ("falafel", None): 20.0,
    ("lettuce leaf", None): 10.0,
    ("chicken thigh", None): 120.0,
    ("beef sirloin steak", None): 200.0,
    ("sirloin steak", None): 200.0,
    ("salmon fillet", None): 150.0,
    ("white fish fillet", None): 150.0,
    ("fish fillet", None): 150.0,
    ("pork chop", None): 180.0,
    ("vegetarian sausage", None): 55.0,
    ("sausage", None): 55.0,
    ("mushroom", None): 15.0,
    ("rasher", None): 25.0,
    ("tortilla wrap", None): 55.0,
    ("tortilla", None): 55.0,
    ("butternut squash", None): 1000.0,
    ("cauliflower", None): 600.0,
    ("orange", None): 130.0,
    ("olive", None): 4.0,
    ("anchovy fillet", None): 4.0,
    ("english muffin", None): 60.0,
    ("muffin", None): 60.0,
    # the unit ends up folded into the name rather than parsed separately
    # for "N garlic cloves" (unit-noun after the ingredient, not before —
    # the parser only strips a *leading* unit token)
    ("garlic cloves", None): 5.0,
    ("stock pot", None): 24.0,  # concentrated jelly stock pot (e.g. Knorr), not a stock cube
}

# generic fallbacks when no ingredient-specific figure above applies —
# broad category averages, always reported with confidence="estimated".
COUNT_UNIT_GRAMS_DEFAULT: dict[str, float] = {
    "tin": 400.0,
    "jar": 350.0,
    "packet": 150.0,
    "clove": 5.0,
    "slice": 30.0,
    "sprig": 2.0,
    "bunch": 75.0,
    "handful": 30.0,
    "pinch": 0.4,
    "stick": 113.0,
    "block": 250.0,
    "head": 600.0,
    "bulb": 50.0,
    "knob": 15.0,
    "dash": 0.6,
    "splash": 5.0,
    "piece": 50.0,
}


@dataclass
class ConversionResult:
    grams: float
    confidence: str  # "exact" | "measured" | "estimated"
    assumptions: dict | None  # None for confidence == "exact"


def _density_for(ingredient_name: str) -> tuple[float, bool]:
    name = ingredient_name.lower()
    for keyword, density in DENSITY_G_PER_ML.items():
        if keyword in name:
            return density, True
    return 1.0, False  # water's density — a labelled assumption, not a guess


def _ingredient_unit_weight(ingredient_name: str, unit: str | None) -> float | None:
    name = ingredient_name.lower()
    best: tuple[int, float] | None = None  # (keyword length, grams) — longest keyword wins
    for (keyword, kw_unit), grams in INGREDIENT_UNIT_WEIGHTS.items():
        if kw_unit != unit or keyword not in name:
            continue
        if best is None or len(keyword) > best[0]:
            best = (len(keyword), grams)
    return best[1] if best else None


def convert(quantity: float, unit: str | None, ingredient_name: str) -> ConversionResult | None:
    """Converts `quantity` `unit`s of `ingredient_name` to grams. Returns
    None if there's no honest way to do so (a bare count with no known
    ingredient-specific or generic unit-weight) — never a fabricated
    figure."""
    if unit in MASS_UNIT_GRAMS:
        return ConversionResult(quantity * MASS_UNIT_GRAMS[unit], "exact", None)

    if unit in VOLUME_UNIT_ML:
        ml = quantity * VOLUME_UNIT_ML[unit]
        density, ingredient_specific = _density_for(ingredient_name)
        grams = ml * density
        return ConversionResult(
            grams,
            "measured" if ingredient_specific else "estimated",
            {
                "unit_weight_g": VOLUME_UNIT_ML[unit] * density,
                "source": "density_table" if ingredient_specific else "water_density_fallback",
                "density_g_per_ml": density,
            },
        )

    specific = _ingredient_unit_weight(ingredient_name, unit)
    if specific is not None:
        return ConversionResult(
            quantity * specific, "measured",
            {"unit_weight_g": specific, "source": "ingredient_specific_table"},
        )

    if unit is not None and unit in COUNT_UNIT_GRAMS_DEFAULT:
        each = COUNT_UNIT_GRAMS_DEFAULT[unit]
        return ConversionResult(
            quantity * each, "estimated",
            {"unit_weight_g": each, "source": "generic_count_default"},
        )

    # a bare count ("2 onions") with no ingredient-specific weight known —
    # honest failure, not a guess
    return None
