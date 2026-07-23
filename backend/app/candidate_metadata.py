"""Practical candidate metadata — prompt 5 of the nutrient-gap
recommendation feature (see docs/nutrient-gap-recommendations.md).

Confirmed by reading `models.Food`/`models.Recipe` directly during the
prompt-1 audit: neither carries anything like this at all (no food group,
no meal-type, no serving size, no "suitable as a direct suggestion" flag).
This module is what stops the scoring engine (prompt 4) from mathematically
justifying a large spoonful of dried parsley, a mug of baking powder, or a
tablespoon of cooking oil as "the most nutrient-dense way to close a gap" —
real per-100g numbers that are true and useless, because nobody eats those
things standalone in that quantity.

Layered, per the prompt's own instruction — **not** an attempt to annotate
the whole ~1.4M-row catalog:

1. `CURATED_FOODS` — a maintained, name-matched table of common
   recommendation candidates (fruit, veg, dairy, protein, grains, legumes,
   nuts/seeds, a few condiments/beverages), each with a real serving range
   a person would actually eat.
2. `EXCLUDED_KEYWORDS` — name substrings that are *never* suitable as a
   direct standalone suggestion regardless of curation (raw seasoning
   powders, leavening agents, stock cubes, supplements, plain cooking
   fats/oils) — matched before falling through to a category default, so
   an uncurated "Baking powder, double acting" doesn't slip through.
3. `CATEGORY_DEFAULTS` — a short list of broad, safe, keyword-matched
   fallback categories (a generic fruit/vegetable/dairy serving) for
   common foods this table hasn't explicitly curated yet.
4. Anything matching none of the above is excluded from direct suggestion
   by default (`suitable_for_direct_suggestion=False`, `source=
   "unknown_excluded"`) — the safe fallback prompt section 5 asks for,
   not a guess.

Name matching (like `ingredient_aliases.py`'s ALIASES) is a real, if
imperfect, signal against this app's mostly-USDA-derived catalog — see
that module's own docstring for the same caveat repeated here rather than
re-litigated: these patterns may need adjusting against whatever's
actually loaded in a given deployment's live catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import Food

MealType = str  # "breakfast" | "lunch" | "dinner" | "snack"
ALL_MEAL_TYPES: tuple[MealType, ...] = ("breakfast", "lunch", "dinner", "snack")


class CandidateKind(str, Enum):
    INGREDIENT = "ingredient"
    STANDALONE_FOOD = "standalone_food"
    SNACK = "snack"
    CONDIMENT = "condiment"
    BEVERAGE = "beverage"
    RECIPE = "recipe"


class FlavorProfile(str, Enum):
    SAVOURY = "savoury"
    SWEET = "sweet"
    NEUTRAL = "neutral"


class FoodGroup(str, Enum):
    FRUIT = "fruit"
    VEGETABLE = "vegetable"
    GRAIN = "grain"
    PROTEIN = "protein"
    DAIRY = "dairy"
    LEGUME = "legume"
    NUT_SEED = "nut_seed"
    FAT_OIL = "fat_oil"
    SPICE_SEASONING = "spice_seasoning"
    SWEET_TREAT = "sweet_treat"
    BEVERAGE = "beverage"
    OTHER = "other"


class PreparationBurden(str, Enum):
    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"


@dataclass(frozen=True)
class ServingRange:
    """A real, practical serving range in grams — never a mathematically
    optimal quantity with no basis in how the food is actually eaten. The
    scoring engine's `PracticalityInput.is_plausible_serving` is derived
    by checking a proposed quantity against this range."""

    minimum_g: float
    default_g: float
    maximum_g: float

    def __post_init__(self) -> None:
        if not (0 < self.minimum_g <= self.default_g <= self.maximum_g):
            raise ValueError(
                f"ServingRange must satisfy 0 < minimum <= default <= maximum, "
                f"got ({self.minimum_g}, {self.default_g}, {self.maximum_g})"
            )

    def contains(self, quantity_g: float) -> bool:
        return self.minimum_g <= quantity_g <= self.maximum_g


@dataclass(frozen=True)
class CandidateMetadata:
    kind: CandidateKind
    flavor_profile: FlavorProfile
    suitable_meal_types: tuple[MealType, ...]
    serving: ServingRange
    # e.g. a condiment/spread normally accompanies another food/meal rather
    # than being suggested as a bare addition on its own
    normally_added_to_another_meal: bool
    requires_preparation: bool
    preparation_burden: PreparationBurden
    food_group: FoodGroup
    pairing_tags: tuple[str, ...] = field(default_factory=tuple)
    # the prompt-5 exclusion flag — False means "never suggest this
    # directly, regardless of how well it scores nutritionally"
    suitable_for_direct_suggestion: bool = True
    # "curated" | "category_default" | "unknown_excluded" — which layer
    # produced this metadata, so a caller/reviewer can tell a deliberate
    # curation apart from a generic fallback
    source: str = "curated"


def _curated(
    kind: CandidateKind, flavor: FlavorProfile, meal_types: tuple[MealType, ...], serving: ServingRange,
    food_group: FoodGroup, *, added_to_another_meal: bool = False, requires_prep: bool = False,
    burden: PreparationBurden = PreparationBurden.NONE, pairing_tags: tuple[str, ...] = (),
    source: str = "curated",
) -> CandidateMetadata:
    return CandidateMetadata(
        kind=kind, flavor_profile=flavor, suitable_meal_types=meal_types, serving=serving,
        normally_added_to_another_meal=added_to_another_meal, requires_preparation=requires_prep,
        preparation_burden=burden, food_group=food_group, pairing_tags=pairing_tags,
        suitable_for_direct_suggestion=True, source=source,
    )


# Name-matched (substring, case-insensitive) against Food.name — a
# maintained core of common recommendation candidates, not an attempt to
# cover the catalog. Add to this as review turns up a recurring good
# suggestion this table doesn't yet recognise (see docs/
# nutrient-gap-recommendations.md's maintainer guide).
CURATED_FOODS: dict[str, CandidateMetadata] = {
    # --- fruit ---
    "bananas, raw": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SWEET, ("breakfast", "snack"),
        ServingRange(80, 120, 150), FoodGroup.FRUIT,
    ),
    "apple": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SWEET, ("breakfast", "lunch", "snack"),
        ServingRange(100, 150, 200), FoodGroup.FRUIT,
    ),
    "orange": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SWEET, ("breakfast", "snack"),
        ServingRange(100, 130, 180), FoodGroup.FRUIT,
    ),
    "strawberries, raw": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SWEET, ("breakfast", "snack"),
        ServingRange(60, 100, 150), FoodGroup.FRUIT, pairing_tags=("berries",),
    ),
    "blueberries, raw": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SWEET, ("breakfast", "snack"),
        ServingRange(50, 80, 120), FoodGroup.FRUIT, pairing_tags=("berries",),
    ),
    "raisins": _curated(
        CandidateKind.SNACK, FlavorProfile.SWEET, ("snack",), ServingRange(15, 30, 45), FoodGroup.FRUIT,
    ),
    # --- vegetables ---
    "spinach, raw": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(30, 60, 100), FoodGroup.VEGETABLE, requires_prep=True, burden=PreparationBurden.LIGHT,
        pairing_tags=("leafy_green",),
    ),
    "broccoli, raw": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(60, 90, 150), FoodGroup.VEGETABLE, requires_prep=True, burden=PreparationBurden.LIGHT,
    ),
    "carrots, raw": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SWEET, ("lunch", "snack"),
        ServingRange(50, 80, 130), FoodGroup.VEGETABLE,
    ),
    "sweet potato": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SWEET, ("lunch", "dinner"),
        ServingRange(100, 150, 220), FoodGroup.VEGETABLE, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    "tomatoes, red, ripe, raw": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SAVOURY, ("lunch", "dinner", "snack"),
        ServingRange(60, 100, 150), FoodGroup.VEGETABLE,
    ),
    # --- dairy ---
    "yogurt, greek": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.NEUTRAL, ("breakfast", "snack"),
        ServingRange(100, 150, 200), FoodGroup.DAIRY, pairing_tags=("breakfast", "protein"),
    ),
    "milk, whole": _curated(
        CandidateKind.BEVERAGE, FlavorProfile.NEUTRAL, ("breakfast", "snack"),
        ServingRange(150, 200, 300), FoodGroup.DAIRY,
    ),
    "cheddar cheese": _curated(
        CandidateKind.SNACK, FlavorProfile.SAVOURY, ("lunch", "snack"),
        ServingRange(20, 30, 50), FoodGroup.DAIRY,
    ),
    "cottage cheese": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.NEUTRAL, ("breakfast", "lunch", "snack"),
        ServingRange(80, 120, 200), FoodGroup.DAIRY, pairing_tags=("protein",),
    ),
    # --- protein ---
    "egg, whole, raw, fresh": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("breakfast", "lunch", "dinner"),
        ServingRange(50, 100, 150), FoodGroup.PROTEIN, requires_prep=True, burden=PreparationBurden.LIGHT,
    ),
    "chicken breast": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(100, 150, 220), FoodGroup.PROTEIN, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    "tofu": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.NEUTRAL, ("lunch", "dinner"),
        ServingRange(80, 120, 200), FoodGroup.PROTEIN, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    "sardine": _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.SAVOURY, ("lunch", "snack"),
        ServingRange(60, 90, 150), FoodGroup.PROTEIN,
    ),
    "salmon": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(100, 130, 200), FoodGroup.PROTEIN, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    # --- grains ---
    "oats": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.NEUTRAL, ("breakfast",),
        ServingRange(30, 50, 80), FoodGroup.GRAIN, requires_prep=True, burden=PreparationBurden.LIGHT,
    ),
    "quinoa": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.NEUTRAL, ("lunch", "dinner"),
        ServingRange(50, 80, 120), FoodGroup.GRAIN, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    "bread, whole wheat": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.NEUTRAL, ("breakfast", "lunch", "snack"),
        ServingRange(30, 60, 90), FoodGroup.GRAIN, pairing_tags=("toast",),
    ),
    "rice, brown": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.NEUTRAL, ("lunch", "dinner"),
        ServingRange(100, 150, 220), FoodGroup.GRAIN, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    # --- legumes ---
    "lentils": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(80, 130, 200), FoodGroup.LEGUME, requires_prep=True, burden=PreparationBurden.MODERATE,
    ),
    "chickpeas": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(80, 130, 200), FoodGroup.LEGUME, requires_prep=True, burden=PreparationBurden.LIGHT,
    ),
    "kidney beans": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(80, 130, 200), FoodGroup.LEGUME, requires_prep=True, burden=PreparationBurden.LIGHT,
    ),
    "black beans": _curated(
        CandidateKind.INGREDIENT, FlavorProfile.SAVOURY, ("lunch", "dinner"),
        ServingRange(80, 130, 200), FoodGroup.LEGUME, requires_prep=True, burden=PreparationBurden.LIGHT,
    ),
    # --- nuts/seeds ---
    "almonds": _curated(
        CandidateKind.SNACK, FlavorProfile.NEUTRAL, ("snack",), ServingRange(15, 25, 40), FoodGroup.NUT_SEED,
    ),
    "walnuts": _curated(
        CandidateKind.SNACK, FlavorProfile.NEUTRAL, ("snack",), ServingRange(15, 25, 40), FoodGroup.NUT_SEED,
    ),
    "sunflower seed": _curated(
        CandidateKind.SNACK, FlavorProfile.NEUTRAL, ("snack",), ServingRange(10, 20, 30), FoodGroup.NUT_SEED,
    ),
    "peanut butter": _curated(
        CandidateKind.CONDIMENT, FlavorProfile.NEUTRAL, ("breakfast", "snack"),
        ServingRange(15, 20, 32), FoodGroup.NUT_SEED, added_to_another_meal=True, pairing_tags=("spread",),
    ),
    # --- condiments/beverages ---
    "orange juice": _curated(
        CandidateKind.BEVERAGE, FlavorProfile.SWEET, ("breakfast",), ServingRange(100, 150, 250), FoodGroup.BEVERAGE,
    ),
    "honey": _curated(
        CandidateKind.CONDIMENT, FlavorProfile.SWEET, ("breakfast", "snack"),
        ServingRange(7, 15, 25), FoodGroup.SWEET_TREAT, added_to_another_meal=True,
    ),
}

# name substrings that are never suitable as a direct standalone
# suggestion, regardless of nutrient density — checked before falling
# through to a category default, per the prompt's own worked examples
# ("large quantities of dried parsley, baking powder, cooking oil, stock
# cubes, spice powders, supplements, excessive seeds or raw ingredients
# not normally eaten alone").
EXCLUDED_KEYWORDS: tuple[str, ...] = (
    "baking powder", "baking soda", "cream of tartar", "yeast",
    "stock cube", "bouillon", "gelatin", "gelatine",
    "food coloring", "food colouring", "vanilla extract", "cornstarch", "corn starch",
    "spice", "seasoning", "extract", "flavoring", "flavouring",
    "oil, olive", "oil, vegetable", "oil, sunflower", "oil, canola", "oil, coconut", "shortening", "lard",
    "supplement", "protein powder", "protein isolate",
    "salt, table", "vinegar",
)

# broad, keyword-matched safe fallbacks for common foods CURATED_FOODS
# hasn't named explicitly yet — deliberately conservative (a plain,
# unprepared, obviously-standalone-edible category), not a general food
# classifier. Checked in order; first match wins.
#
# Deliberately NOT a blanket "contains 'raw'" fallback: this app's names
# include raw meat/fish/egg ("Chicken, raw", "Salmon, raw") alongside raw
# produce, and defaulting *those* to "safe to eat as-is" would be a real
# safety problem, not just a gastronomically odd suggestion — far more
# conservative to require an explicit, reviewed category match here than
# to risk that. Every category default below is a food FORM that's
# genuinely edible unprepared.
_CATEGORY_DEFAULTS: tuple[tuple[str, CandidateMetadata], ...] = (
    ("yogurt", _curated(
        CandidateKind.STANDALONE_FOOD, FlavorProfile.NEUTRAL, ("breakfast", "snack"),
        ServingRange(100, 150, 200), FoodGroup.DAIRY, source="category_default",
    )),
)


_UNKNOWN_EXCLUDED = CandidateMetadata(
    kind=CandidateKind.INGREDIENT, flavor_profile=FlavorProfile.NEUTRAL, suitable_meal_types=(),
    serving=ServingRange(1, 1, 1), normally_added_to_another_meal=False, requires_preparation=False,
    preparation_burden=PreparationBurden.NONE, food_group=FoodGroup.OTHER, pairing_tags=(),
    suitable_for_direct_suggestion=False, source="unknown_excluded",
)


def _matches(name_lower: str, key: str) -> bool:
    return key in name_lower


def resolve_candidate_metadata(food: Food) -> CandidateMetadata:
    """Layered resolution (prompt 5): curated entry, then an explicit
    exclusion, then a safe category default, then — the default of
    defaults — excluded from direct suggestion. A branded product is
    treated the same as "unknown" here regardless of name match: this
    table is curated against generic Foundation/SR Legacy-style names,
    and a branded product's name is marketing copy (same caveat
    `dietary_tags.py` already makes about allergen matching), not a
    reliable signal of practical serving size."""
    name_lower = food.name.lower()

    # a branded product's name is marketing copy, not a reliable
    # description (same caveat dietary_tags.py makes about allergen
    # matching) — checked before curated/keyword matching so a
    # branded product can never "accidentally" match a curated generic
    # entry's name pattern.
    if food.data_type == "branded_food":
        return _UNKNOWN_EXCLUDED

    for key, metadata in CURATED_FOODS.items():
        if _matches(name_lower, key):
            return metadata

    if any(_matches(name_lower, kw) for kw in EXCLUDED_KEYWORDS):
        return _UNKNOWN_EXCLUDED

    for key, metadata in _CATEGORY_DEFAULTS:
        if _matches(name_lower, key):
            return metadata

    return _UNKNOWN_EXCLUDED


def curated_key_for(food: Food) -> str | None:
    """The `CURATED_FOODS` key that matched this food, if any — `None`
    for a branded product or anything resolved via a category default or
    the unknown-excluded fallback. Used by `recommend_pairs.py` to check
    a specific pair against `CURATED_PAIRS`, since curation is keyed by
    name pattern, not a stable id."""
    if food.data_type == "branded_food":
        return None
    name_lower = food.name.lower()
    for key in CURATED_FOODS:
        if _matches(name_lower, key):
            return key
    return None


def is_plausible_serving(metadata: CandidateMetadata, quantity_g: float) -> bool:
    """What `recommendation_scoring.PracticalityInput.is_plausible_serving`
    is derived from — never `None` (unknown) once a `CandidateMetadata`
    exists at all, since resolving one always yields a real serving range
    (even the `unknown_excluded` fallback's, which nothing should ever be
    proposing a quantity against in practice, since it's excluded upstream)."""
    return metadata.serving.contains(quantity_g)
