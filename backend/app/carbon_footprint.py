"""Coarse, name-keyword food-carbon-intensity tiering (prompt 2.2's
"reduce carbon footprint" goal).

THE HONEST LIMIT OF THIS MODULE, UP FRONT: USDA FoodData Central does not
publish per-food greenhouse-gas/land-use data, and this app has no other
emissions dataset joined against its food catalogue — the prompt's other
suggested option (a supplementary per-food emissions dataset) isn't
available in this environment. So this does the only honest thing
available given that gap: the same name-keyword matching dietary_tags.py
already uses for allergen/religious matching (see that module's own
"THE HONEST LIMIT" docstring for the identical reasoning), bucketed into
four coarse tiers rather than a fabricated precise kg-CO2e-per-kg figure
this app has no real per-food source for.

Tier boundaries are anchored to the *relative ordering* consistently
reported across published food-system life-cycle-assessment literature
(most visibly popularized by Poore & Nemecek 2018, Science — "Reducing
food's environmental impacts through producers and consumers"), not to
any single food's exact number:

- very_high: ruminant meat (beef, lamb, mutton, goat) — consistently the
  highest-footprint food category by a wide margin across LCA studies,
  driven by methane from enteric fermentation and associated land use.
- high: hard/aged dairy (cheese) — the milk-to-cheese concentration
  ratio (roughly 10:1 by mass) compounds dairy's already-substantial
  footprint.
- medium: pork, poultry, fish/seafood, eggs, milk and other non-cheese
  dairy — meaningfully lower than ruminant meat/cheese, but still
  higher than most plant foods.
- low: legumes, grains, vegetables, fruit, nuts, and other whole plant
  foods — consistently the lowest-footprint category, land- and
  emissions-efficient per unit of food produced.

A food whose name matches no keyword gets tier=None ("unknown"), never a
guessed default — the same conservative direction dietary_tags.py's
confidence system takes: silence rather than a false signal. Confidence
is always "low" for a real match, never "high" — unlike some of
dietary_tags.py's Foundation/SR Legacy matches, there's no way to make a
name-keyword carbon-tier match here as trustworthy as a real per-food
LCA figure would be, and branded products' marketing-copy names make it
an even weaker signal there.

WIRED INTO CANDIDATE RANKING (follow-up pass, after the carefully-hardened
scoring code — see docs/recommendation-candidates.md for the last real
bug found there — was left alone on purpose during the same-prompt
bolt-on this module started as): `recommendation_scoring.score_candidate`
takes an optional `carbon_tier` and applies a deliberately modest bonus/
penalty (`ScoringWeights.carbon_very_high_penalty`/`carbon_high_penalty`/
`carbon_low_bonus` — "medium" and "no match" both stay neutral); both
`recommend_ingredients.suggest_ingredients` and `recommend_recipes.
suggest_recipes` only ever resolve and pass a tier when the profile has
`reduce_carbon_footprint` among its active goals (`goals.goal_keys_of`) —
an inactive goal gets exactly the same ranking as before this module
existed, never a silent nudge. The magnitude is further scaled by
`goals.goal_weight(rank)` for wherever reduce_carbon_footprint actually
sits in the profile's ranked goal list (PR review: a first pass applied
the full bonus/penalty regardless of rank, so a rank-10 goal influenced
ranking exactly as much as rank-1 — violating goals.py's own documented
1/rank multi-goal policy every other goal-driven signal follows) — see
`score_candidate`'s `carbon_priority_weight` parameter. A recipe has no
single tier of its own;
`recommend_recipes.primary_ingredient_food` (the same by-mass-dominant
ingredient already used for suggestion deduplication) stands in for "the
recipe's food name" rather than inventing a second aggregation rule.
`recommend_pairs.py` uses the larger-quantity food of the pair as the
same kind of stand-in (`recommend_pairs._primary_pair_food`) — a
condiment-plus-base pair, the common case, makes this an easy call, the
base dwarfs the condiment in mass. `recommend_substitutions.py` uses the
replacement recipe's own `primary_ingredient_food`, same as
`recommend_recipes.py`."""

from typing import Literal

# Operational-hardening prompt 3, requirement 11: bump whenever the
# keyword lists below change materially (a food's classification could
# flip tiers for a reason unrelated to any scoring-formula change) — the
# same "so a previously-seen result can be told apart from one under a
# different ruleset" contract recommendation_scoring.
# RECOMMENDATION_MODEL_VERSION already has for the formula itself. Kept
# separate from that constant deliberately: a keyword-list edit here
# doesn't change the scoring formula, and a formula change doesn't
# reclassify any food, so the two must be able to move independently.
CARBON_CLASSIFICATION_VERSION = 1

CarbonTier = Literal["very_high", "high", "medium", "low"]

_VERY_HIGH_KEYWORDS = ["beef", "lamb", "mutton", "goat", "veal", "bison"]
_HIGH_KEYWORDS = ["cheese", "cheddar", "mozzarella", "parmesan", "brie", "feta", "halloumi"]
_MEDIUM_KEYWORDS = [
    "pork", "bacon", "ham", "sausage", "chicken", "turkey", "duck", "poultry",
    "fish", "salmon", "tuna", "cod", "shrimp", "prawn", "seafood", "shellfish",
    "egg", "milk", "yogurt", "yoghurt", "butter", "cream",
]
_LOW_KEYWORDS = [
    "bean", "beans", "lentil", "chickpea", "pea", "tofu", "tempeh", "soy",
    "rice", "oat", "wheat", "barley", "quinoa", "bread", "pasta",
    "vegetable", "spinach", "broccoli", "carrot", "potato", "tomato", "onion", "pepper",
    "fruit", "apple", "banana", "berry", "orange",
    "nut", "almond", "walnut", "peanut", "cashew", "seed",
]

# Checked in this order — highest-footprint tier first — so a mixed name
# like "beef stock cube with vegetables" tags as very_high (the dominant
# ingredient), not low (matched on "vegetables").
_TIERED_KEYWORDS: list[tuple[CarbonTier, list[str]]] = [
    ("very_high", _VERY_HIGH_KEYWORDS),
    ("high", _HIGH_KEYWORDS),
    ("medium", _MEDIUM_KEYWORDS),
    ("low", _LOW_KEYWORDS),
]


def carbon_tier_for_food(name: str) -> CarbonTier | None:
    """First-match-wins keyword lookup against a food's name. None means
    no keyword matched at all — an honest "don't know", never a guess."""
    name_lower = name.lower()
    for tier, keywords in _TIERED_KEYWORDS:
        if any(k in name_lower for k in keywords):
            return tier
    return None


def carbon_tier_confidence(tier: CarbonTier | None) -> Literal["low"] | None:
    """Always "low" for a real match — see module docstring for why a
    name-keyword match can never be reported as high-confidence here."""
    return "low" if tier is not None else None
