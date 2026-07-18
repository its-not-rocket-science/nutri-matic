"""The fixed set of curated stock collections (prompt section 2) —
pipeline.py get-or-creates one Collection row per entry here, owned by the
system account, the first time it's needed.

No "pregnancy" collection: prompt section 11 explicitly allows omitting a
collection that isn't supportable without clinical governance this app
doesn't have, and says to document why rather than build it — nutrient
totals alone can't establish pregnancy safety (that needs e.g. a listeria/
mercury/vitamin-A-form assessment this app has no data or model for), so
building it would mean asserting a suitability claim the underlying
analysis can't actually back up.

kind:
    "themed"      — membership is curatorial (manifest-assigned); never
                     computed from ingredients.
    "educational" — same as themed, but members get a required
                     Recipe.educational_note and are labelled as such in
                     the UI rather than shown as an ordinary suggestion.
    "dietary"      — membership is *computed* at analyse-time from the
                     recipe's actual ingredients via dietary_filter's
                     existing evaluate_food (prompt section 11: "For
                     nutritional/dietary collections, calculate membership
                     from actual analysis where appropriate" and "must
                     preserve the distinctions among allowed/discouraged/
                     excluded/unknown"). A recipe only qualifies if EVERY
                     ingredient evaluates "ok" for the given pattern/tags —
                     a single "unknown" (e.g. a low-confidence branded-food
                     name match) keeps it out, never treated as safe.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionSpec:
    key: str
    name: str
    kind: str  # "themed" | "educational" | "dietary"
    description: str
    # for kind="dietary" only — passed straight to dietary_tags.evaluate_food
    dietary_pattern: str | None = None
    constraint_tags: tuple[tuple[str, str], ...] = ()  # (tag_key, "hard_exclude") pairs


COLLECTIONS: dict[str, CollectionSpec] = {
    "everyday_uk_meals": CollectionSpec(
        "everyday_uk_meals", "Everyday UK Meals", "themed",
        "Familiar, representative meals you'd recognise from a typical UK weeknight.",
    ),
    "breakfasts": CollectionSpec(
        "breakfasts", "Breakfasts", "themed", "A range of everyday UK breakfasts.",
    ),
    "plant_protein_complementarity": CollectionSpec(
        "plant_protein_complementarity", "Plant Protein and Complementarity", "themed",
        "Classic plant-protein pairings (rice + beans, dhal + rice...) that demonstrate "
        "complementary amino acid profiles — see each recipe's DIAAS/PDCAAS breakdown.",
    ),
    "high_protein_vegetarian": CollectionSpec(
        "high_protein_vegetarian", "High-Protein Vegetarian", "themed",
        "Nutritionally credible vegetarian meals built around eggs, dairy, tofu, tempeh, "
        "seitan, legumes, and complementary grains/pulses.",
    ),
    "budget_meals": CollectionSpec(
        "budget_meals", "Budget Meals", "themed",
        "Ordinary supermarket ingredients, low ingredient counts, dried/tinned pulses and "
        "frozen veg — no specific price claim is made (see docs/stock-recipes.md).",
    ),
    "iron_focused_meals": CollectionSpec(
        "iron_focused_meals", "Iron-Focused Meals", "themed",
        "Meals demonstrating haem/non-haem iron sources and vitamin C pairing. Not medical "
        "advice — see each recipe's iron robustness explanation for the absorption model used.",
    ),
    "lower_sodium_alternatives": CollectionSpec(
        "lower_sodium_alternatives", "Lower-Sodium Alternatives", "themed",
        "Recognisable meals formulated with realistic sodium reductions.",
    ),
    "mediterranean_style_meals": CollectionSpec(
        "mediterranean_style_meals", "Mediterranean-Style Meals", "themed",
        "Meals broadly consistent with Mediterranean dietary patterns. No disease-prevention "
        "claim is made.",
    ),
    "batch_cooking_meals": CollectionSpec(
        "batch_cooking_meals", "Batch-Cooking Meals", "themed",
        "Recipes that scale well and refrigerate/freeze reasonably.",
    ),
    "educational_comparisons": CollectionSpec(
        "educational_comparisons", "Educational Comparisons", "educational",
        "Paired/contrasted recipes illustrating a specific nutritional concept (e.g. rice "
        "alone vs. rice+beans). Labelled as educational examples, not ordinary suggestions.",
    ),
    "vegan": CollectionSpec(
        "vegan", "Vegan", "dietary", "Recipes where every ingredient evaluates vegan-suitable.",
        dietary_pattern="vegan",
    ),
    "vegetarian": CollectionSpec(
        "vegetarian", "Vegetarian", "dietary",
        "Recipes where every ingredient evaluates vegetarian-suitable.",
        dietary_pattern="vegetarian",
    ),
    "pescatarian": CollectionSpec(
        "pescatarian", "Pescatarian", "dietary",
        "Recipes where every ingredient evaluates pescatarian-suitable.",
        dietary_pattern="pescatarian",
    ),
    "gluten_free": CollectionSpec(
        "gluten_free", "Gluten-Free", "dietary",
        "Recipes where no ingredient name-matches wheat/gluten/barley/rye/malt.",
        constraint_tags=(("wheat_gluten", "hard_exclude"),),
    ),
    "dairy_free": CollectionSpec(
        "dairy_free", "Dairy-Free", "dietary",
        "Recipes where no ingredient name-matches milk/dairy.",
        constraint_tags=(("milk", "hard_exclude"),),
    ),
    "nut_free": CollectionSpec(
        "nut_free", "Nut-Free", "dietary",
        "Recipes where no ingredient name-matches peanuts or tree nuts.",
        constraint_tags=(("peanut", "hard_exclude"), ("tree_nut", "hard_exclude")),
    ),
}
