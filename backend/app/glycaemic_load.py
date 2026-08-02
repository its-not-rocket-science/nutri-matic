"""Coarse, name-keyword glycaemic-impact tiering ("blood-sugar stability"
goal).

THE HONEST LIMIT OF THIS MODULE, UP FRONT: USDA FoodData Central does not
publish glycaemic index (GI) values — GI is a lab-measured value (the
blood-glucose response to a standard carbohydrate portion of the food,
relative to glucose itself) that FDC simply doesn't carry, and this app
has no other joined dataset that does either. Same honest gap
carbon_footprint.py documents for emissions data; same fix: coarse,
keyword-matched category tiering anchored to published GI research
(principally Foster-Powell, Holt & Brand-Miller's "International table
of glycemic index and glycemic load values", and the University of
Sydney's glycaemic-index database), not a fabricated per-food number.

A SECOND, SHARPER CAVEAT THAN carbon_footprint.py's: GI genuinely varies
far more *within* a single food name than carbon footprint does —
ripeness, variety, and cooking method can swing a food's real GI across
an entire tier boundary (a green vs. very ripe banana; boiled vs. baked
potato; white bread's GI is reported anywhere from the high-50s to
100+ depending on type and source). Carbon footprint's tier boundaries
are wide enough that production-method variation rarely crosses a tier;
GI's tier boundaries are not. So this module deliberately tiers only
foods whose published GI classification is consistent across sources and
not dominated by a single hard-to-infer-from-the-name variable — bread,
rice, potato, and banana are *not* tiered here at all despite being
common, high-volume carbohydrate staples, precisely because their real
GI depends on exactly the kind of preparation/variety detail a food name
alone can't reliably convey. Silence (tier=None) for these, same
conservative direction as an unmatched name, rather than a keyword match
that could be actively wrong as often as it's right.

Three tiers, the standard glucose-referenced GI classification (Foster-
Powell/Sydney convention): low (GI ≤55), medium (GI 56-69), high (GI
≥70). Foods with negligible available carbohydrate — meat, poultry,
fish, eggs, cheese, most nuts — are placed in `low` on a different basis
than the rest of that tier: GI is only defined for carbohydrate-
containing foods at all, so a near-zero-carbohydrate food isn't "tested
low", it produces negligible blood-glucose response by the same
mechanism GI itself measures. Documented here rather than silently
folded in, since it's a different kind of claim than "this food was
measured and scored low."

A food whose name matches no keyword gets tier=None ("unknown"), never a
guessed default. Confidence is always "low" for a real match, for the
same reasons carbon_footprint.py's is — a name-keyword match can never
be as trustworthy as a real per-food lab-measured GI value, and branded
products' marketing-copy names make it an even weaker signal there.

WIRED INTO CANDIDATE RANKING the same way reduce_carbon_footprint is
(see carbon_footprint.py's own docstring for the shared mechanism):
`recommendation_scoring.score_candidate` takes an optional
`glycaemic_tier`, applies a deliberately modest bonus/penalty scaled by
`goals.goal_weight(rank)` for wherever blood_sugar_stability sits in the
profile's ranked goal list, and every recommend_*.py module (ingredients,
recipes, pairs, substitutions) only ever resolves a tier when that goal
is actually active for the profile.

CLASSIFICATION BASIS, EXPOSED, NOT JUST DOCUMENTED (operational-
hardening prompt 3): `glycaemic_tier_for_food` alone can't tell an API
consumer *why* a food landed in "low" — a lentil and a chicken breast
both do, for entirely different reasons (one is a real, researched
low-GI food category; the other has negligible carbohydrate at all,
so GI doesn't meaningfully apply to it — see the paragraph above).
`glycaemic_classification_for_food` returns both the tier and which of
those two applies, threaded all the way through `recommendation_scoring.
score_candidate` into the API response, so "Meat/fish/eggs described as
negligible-carbohydrate... not as having a measured 'low GI'" is a real,
checkable property of what a caller sees, not just true of this module's
own prose."""

from dataclasses import dataclass
from typing import Literal

# Operational-hardening prompt 3, requirement 11 — see carbon_footprint.
# CARBON_CLASSIFICATION_VERSION's own docstring for why this is a
# separate constant from RECOMMENDATION_MODEL_VERSION: bump whenever the
# keyword lists below change materially, independent of any scoring-
# formula change.
GLYCAEMIC_CLASSIFICATION_VERSION = 1

GlycaemicTier = Literal["high", "medium", "low"]
# "category_match": a real, researched whole-food GI category (legumes,
# fruit, non-starchy veg, dairy, tested grains). "negligible_
# carbohydrate": GI is only defined for carbohydrate-containing foods at
# all — these aren't "tested low", they're outside what GI measures.
# Never conflated: a caller must be able to tell the two apart, not just
# see "low" for both.
GlycaemicBasis = Literal["category_match", "negligible_carbohydrate"]


@dataclass(frozen=True)
class GlycaemicClassification:
    tier: GlycaemicTier | None
    basis: GlycaemicBasis | None

# Deliberately small and conservative — see module docstring for why
# bread/rice/potato/banana are excluded entirely despite being common
# carbohydrate staples, rather than assigned a tier that preparation/
# variety/ripeness could easily make wrong.
_HIGH_GI_KEYWORDS = [
    "cornflake", "puffed rice", "rice krispies", "pretzel", "watermelon", "glucose", "dextrose",
    # PR review: refined-sugar/beverage products whose name can coincide
    # with an unrelated whole-food keyword below (a doughnut isn't a nut;
    # an orange soda isn't an orange) — checked first specifically so
    # these uncontroversially-high-GI processed foods can't be masked by
    # a LOW-tier substring collision. Not an attempt to catalogue every
    # confectionery/beverage product, just the common collision risks.
    "doughnut", "donut", "candy", "soda", "soft drink", "cola", "sports drink", "energy drink",
]
_MEDIUM_GI_KEYWORDS = [
    "raisin", "sultana", "honey", "couscous", "oat", "porridge", "muesli", "pineapple", "mango",
    # juice, checked before the LOW tier's whole-fruit keywords below —
    # without this, "orange juice" would match LOW via the substring
    # "orange" and inherit whole fruit's classification, when juice
    # (no fibre, faster absorption) is consistently rated less favourably
    # than the same fruit eaten whole
    "juice",
]
_LOW_GI_KEYWORDS = [
    "lentil", "chickpea", "bean", "pea", "soy", "tofu", "tempeh",
    "apple", "orange", "berry", "strawberr", "blueberr", "raspberr", "cherry", "pear", "plum", "grapefruit", "peach", "kiwi",
    "spinach", "broccoli", "carrot", "cabbage", "cauliflower", "cucumber", "pepper", "tomato", "onion", "lettuce",
    "kale", "courgette", "zucchini", "mushroom", "asparagus", "celery",
    # real, meaningful lactose content with published GI values — a
    # different basis than the negligible-carbohydrate group below
    "milk", "yogurt", "yoghurt",
    "quinoa", "barley", "bulgur", "pasta", "spaghetti", "noodle",
]
# Negligible available carbohydrate — GI is only defined for
# carbohydrate-containing foods, so these aren't "tested low", the
# concept doesn't meaningfully apply to them at all. Tiered "low" for
# scoring purposes (the practical effect — negligible blood-glucose
# response — is the same direction as a real low-GI food), but flagged
# with a distinct basis so a caller never presents this as a measured
# figure. Deliberately no bare "nut" keyword — it's a substring of
# "doughnut" (PR review, see _HIGH_GI_KEYWORDS), and every common nut is
# already listed individually, so it added a collision risk with no real
# coverage benefit.
_NEGLIGIBLE_CARB_KEYWORDS = [
    "cheese", "almond", "walnut", "peanut", "cashew", "pistachio", "seed",
    "egg", "chicken", "turkey", "duck", "beef", "pork", "lamb", "fish", "salmon", "tuna", "cod", "shrimp", "prawn",
]

# Checked in this order — highest-GI tier first — so a mixed name like
# "honey-roasted almonds" tags as medium (the dominant sugar coating),
# not low (matched on "almond"); same convention as carbon_footprint.py.
# Both "low"-tier keyword lists are checked together (category match
# before negligible-carb, an arbitrary but fixed tie-break order — no
# food should realistically match both) since neither can outrank high/
# medium.
_TIERED_KEYWORDS: list[tuple[GlycaemicTier, GlycaemicBasis, list[str]]] = [
    ("high", "category_match", _HIGH_GI_KEYWORDS),
    ("medium", "category_match", _MEDIUM_GI_KEYWORDS),
    ("low", "category_match", _LOW_GI_KEYWORDS),
    ("low", "negligible_carbohydrate", _NEGLIGIBLE_CARB_KEYWORDS),
]


def glycaemic_classification_for_food(name: str) -> GlycaemicClassification:
    """First-match-wins keyword lookup against a food's name — both tier
    and basis, so a caller can tell "a real researched low-GI food
    category" apart from "GI doesn't really apply here" without having
    to separately re-derive it. `GlycaemicClassification(None, None)`
    means no keyword matched at all — an honest "don't know", never a
    guess."""
    name_lower = name.lower()
    for tier, basis, keywords in _TIERED_KEYWORDS:
        if any(k in name_lower for k in keywords):
            return GlycaemicClassification(tier=tier, basis=basis)
    return GlycaemicClassification(tier=None, basis=None)


def glycaemic_tier_for_food(name: str) -> GlycaemicTier | None:
    """Tier only — see glycaemic_classification_for_food for tier+basis
    together. Kept as a thin wrapper since several call sites only ever
    needed the tier before this prompt; new callers should prefer the
    full classification."""
    return glycaemic_classification_for_food(name).tier


def glycaemic_tier_confidence(tier: GlycaemicTier | None) -> Literal["low"] | None:
    """Always "low" for a real match — see module docstring for why a
    name-keyword match can never be reported as high-confidence here."""
    return "low" if tier is not None else None
