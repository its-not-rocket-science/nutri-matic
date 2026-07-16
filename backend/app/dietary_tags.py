"""Controlled vocabulary and matching logic for dietary constraints
(allergies, intolerances, religious requirements, dietary patterns) —
Phase 3's "hard exclusions, soft preferences, unknown suitability" model.

THE HONEST LIMIT OF THIS MODULE, UP FRONT: USDA FoodData Central does not
publish structured allergen or ingredient-category data for any food in
this app — not for Foundation/SR Legacy foods, and (despite branded
products having a real ingredients list on the physical label) not in a
structured, machine-readable form in the branded_food.csv export either.
There is no dataset to look allergens up in.

So this module does the only honest thing available: it matches a food's
*name* against keyword lists for each tag. That is a real signal, but a
limited one, and its reliability varies sharply by dataset:

- Foundation/SR Legacy foods: USDA's own description essentially *is* the
  ingredient ("Milk, whole, 3.25% milkfat"). A name match here is a direct,
  fairly trustworthy signal — tagged "high" confidence below.
- Branded foods: the product name is marketing copy, not an ingredients
  list ("Grandma's Chocolate Chip Cookies" contains milk and egg; the name
  says neither). A name match here is a much weaker signal, and a *miss*
  proves nothing — tagged "low" confidence, and a food with active hard
  exclusions that doesn't match anything by name is still reported
  "unknown", never silently "ok".

This is why medical considerations and free-text preferences are never
auto-enforced (see models.DietaryConstraint's docstring) — there's no
vocabulary to check them against at all, and pretending otherwise would be
actively unsafe for something like an allergy. Nothing in this app should
be read as a substitute for reading the actual label.
"""

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["hard_exclude", "avoid"]
Confidence = Literal["high", "low"]
SuitabilityStatus = Literal["ok", "avoid", "excluded", "unknown"]

# category -> {label, keywords}. Keys are stored on DietaryConstraint.tag and
# referenced by DIETARY_PATTERNS / RELIGIOUS_REQUIREMENTS below. Keyword
# lists are deliberately simple substring matches (see module docstring for
# why nothing fancier would be more honest) — lowercase, no regex.
TAGS: dict[str, dict] = {
    "peanut": {"label": "Peanut", "keywords": ["peanut"]},
    "tree_nut": {
        "label": "Tree nuts",
        "keywords": [
            "almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut",
            "macadamia", "brazil nut", "pine nut",
        ],
    },
    "milk": {
        "label": "Milk / dairy",
        # deliberately no bare "butter": nut butters ("Peanut butter,
        # smooth", "Almond butter") vastly outnumber dishes where dairy
        # butter is the reason it's in the name, and a false "contains
        # dairy" on every nut butter would be a much worse failure than
        # missing a plain "Butter, salted" entry (still caught via "dairy"/
        # "buttermilk"/"butterfat" below, just not the bare word)
        "keywords": [
            "milk", "cheese", "buttermilk", "butterfat", "cream", "yogurt", "yoghurt", "whey", "casein", "dairy",
        ],
    },
    "egg": {"label": "Egg", "keywords": ["egg"]},
    "soy": {"label": "Soy", "keywords": ["soy", "soya", "tofu", "edamame"]},
    "wheat_gluten": {"label": "Wheat / gluten", "keywords": ["wheat", "gluten", "barley", "rye", "malt"]},
    "fish": {
        "label": "Fish",
        "keywords": ["fish", "salmon", "tuna", "cod", "anchov", "sardine", "halibut", "trout", "tilapia"],
    },
    "shellfish": {
        "label": "Shellfish",
        "keywords": ["shrimp", "prawn", "crab", "lobster", "clam", "oyster", "scallop", "mussel", "shellfish"],
    },
    "sesame": {"label": "Sesame", "keywords": ["sesame", "tahini"]},
    "meat": {
        "label": "Red meat",
        "keywords": ["beef", "pork", "lamb", "veal", "bacon", "ham", "sausage", "venison", "goat"],
    },
    "poultry": {"label": "Poultry", "keywords": ["chicken", "turkey", "duck", "goose", "poultry"]},
    "pork": {"label": "Pork", "keywords": ["pork", "bacon", "ham", "prosciutto", "lard", "pepperoni"]},
    "alcohol": {"label": "Alcohol", "keywords": ["beer", "wine", "liquor", "rum", "vodka", "whiskey", "whisky"]},
    "gelatin": {"label": "Gelatin", "keywords": ["gelatin", "gelatine"]},
    "honey": {"label": "Honey", "keywords": ["honey"]},
}

# Allergy/intolerance tags offered in the profile UI — a subset of TAGS
# (excludes the animal-product categories, which are pattern/religious
# implementation detail, not something a user picks directly as an allergy).
ALLERGEN_TAGS = [
    "peanut", "tree_nut", "milk", "egg", "soy", "wheat_gluten", "fish", "shellfish", "sesame",
]

DIETARY_PATTERNS: dict[str, dict] = {
    "vegan": {
        "label": "Vegan",
        "excludes": ["meat", "poultry", "pork", "fish", "shellfish", "milk", "egg", "honey", "gelatin"],
    },
    "vegetarian": {
        "label": "Vegetarian",
        "excludes": ["meat", "poultry", "pork", "fish", "shellfish", "gelatin"],
    },
    "pescatarian": {
        "label": "Pescatarian",
        "excludes": ["meat", "poultry", "pork", "gelatin"],
    },
    "flexitarian": {"label": "Flexitarian (mostly plant-based)", "excludes": []},
    "omnivore": {"label": "Omnivore / no pattern", "excludes": []},
}

# Real religious dietary law involves more than ingredient exclusion (halal
# and kosher both require a specific slaughter method; kosher also requires
# meat/dairy separation; Jain practice excludes root vegetables) — none of
# that is verifiable from a food name, so these map only to the
# ingredient-level subset that *can* be checked, and the UI must say so.
RELIGIOUS_REQUIREMENTS: dict[str, dict] = {
    "halal": {"label": "Halal", "excludes": ["pork", "alcohol", "gelatin"]},
    "kosher": {"label": "Kosher", "excludes": ["pork", "shellfish"]},
    "hindu_vegetarian": {
        "label": "Hindu vegetarian",
        "excludes": ["meat", "poultry", "pork", "fish", "shellfish", "egg", "gelatin"],
    },
    "jain": {
        "label": "Jain",
        "excludes": ["meat", "poultry", "pork", "fish", "shellfish", "egg", "gelatin"],
    },
}


@dataclass
class Suitability:
    status: SuitabilityStatus
    confidence: Confidence
    reasons: list[str] = field(default_factory=list)


def match_confidence(data_type: str | None) -> Confidence:
    return "high" if data_type in ("foundation_food", "sr_legacy_food") else "low"


def _name_matches_tag(name: str, tag_key: str) -> bool:
    tag = TAGS.get(tag_key)
    if tag is None:
        return False
    name_lower = name.lower()
    return any(kw in name_lower for kw in tag["keywords"])


def evaluate_food(
    name: str,
    data_type: str | None,
    dietary_pattern: str | None,
    constraint_tags: list[tuple[str, str]],
) -> Suitability:
    """constraint_tags is a list of (tag_key, severity) pairs — typically
    from a user's DietaryConstraint rows. Pattern-implied exclusions are
    folded in automatically; callers don't need to expand dietary_pattern
    themselves."""
    tags_to_check: list[tuple[str, str]] = list(constraint_tags)
    if dietary_pattern and dietary_pattern in DIETARY_PATTERNS:
        tags_to_check.extend((t, "hard_exclude") for t in DIETARY_PATTERNS[dietary_pattern]["excludes"])

    if not tags_to_check:
        return Suitability(status="ok", confidence="high")

    confidence = match_confidence(data_type)
    worst: SuitabilityStatus = "ok"
    reasons: list[str] = []
    matched_any = False

    for tag_key, severity in tags_to_check:
        if tag_key not in TAGS or not _name_matches_tag(name, tag_key):
            continue
        matched_any = True
        reasons.append(TAGS[tag_key]["label"])
        if severity == "hard_exclude":
            worst = "excluded"
        elif severity == "avoid" and worst != "excluded":
            worst = "avoid"

    if matched_any:
        return Suitability(status=worst, confidence=confidence, reasons=reasons)

    # No keyword hit. For a branded product that's weak evidence at best —
    # report unknown rather than implying it's been checked and passed.
    if confidence == "low":
        return Suitability(status="unknown", confidence=confidence)
    return Suitability(status="ok", confidence=confidence)
