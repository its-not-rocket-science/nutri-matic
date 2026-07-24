"""Recipe-level data-quality/provenance/mapping-confidence summaries for
recipe and substitution recommendations — hardening prompt 4 (see
docs/nutrient-gap-recommendations-hardening.md).

Reuses exactly what `stock_recipes/` already persists per ingredient
(`models.RecipeIngredientProvenance` — populated only for stock-recipe
ingredients imported via the pipeline, see that model's own docstring)
and per recipe (`Recipe.match_coverage_lines`/`match_coverage_mass`/
`unresolved_ingredients`) — this module never reruns food matching, it
only aggregates rows that already exist into one summary a recommendation
response can serialise.

Keeps `match_relationship` (the *semantic* closeness of a match — exact/
regional/analogue/proxy/reviewed-substitution) strictly separate from
`match_method`/review status, per the prompt's own instruction: a
`reviewed_substitution` is a human-reviewed pairing, not automatically
"exact" — it's bucketed with `category_proxy` below, never with
`exact`/`regional_equivalent`, regardless of how much a maintainer
trusts the review.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Recipe, RecipeIngredient, RecipeIngredientProvenance

# Below this, an individual ingredient's own match is counted towards
# "unresolved_or_low_confidence" in the summary, in addition to lines
# stock_recipes/food_matching.py couldn't match to any Food at all
# (Recipe.unresolved_ingredients).
LOW_CONFIDENCE_THRESHOLD = 0.5

_EXACT_RELATIONSHIPS = {"exact", "regional_equivalent"}
_ANALOGUE_RELATIONSHIPS = {"close_analogue"}
# a reviewed_substitution is a human-approved pairing, not a semantically
# exact one — bucketed with category_proxy, never with exact/regional,
# per this module's own docstring and the hardening prompt's instruction
_PROXY_RELATIONSHIPS = {"category_proxy", "reviewed_substitution"}
# non-alias match methods that resolved by an exact/near-exact name match
# rather than any alias table — no `match_relationship` value at all
# (that field is only ever set for "alias"/"manual_review" matches), so
# they're classified by `match_method` instead
_EXACT_METHODS = {"canonical", "exact_name"}


@dataclass(frozen=True)
class RecipeQualitySummary:
    """One recipe's aggregate ingredient-mapping quality — every count is
    over the recipe's actual `RecipeIngredient` rows, never a re-derived
    estimate. `None` fields mean "not applicable" (a plain user-built
    recipe has no provenance system involved at all), not zero."""

    ingredient_count: int
    # ingredients with no RecipeIngredientProvenance row at all — either
    # a plain user-built ingredient, or a stock-recipe ingredient
    # imported before per-ingredient provenance tracking existed
    # ("legacy-null") — both look identical from here, which is honest:
    # this module can't tell you *why* provenance is missing, only that
    # it is.
    unmapped_count: int
    exact_or_regional_count: int
    analogue_count: int
    proxy_or_reviewed_count: int
    # a non-alias fuzzy-name match with no relationship tier at all —
    # counted separately since it's neither confirmed-exact nor a
    # deliberate proxy/analogue
    fuzzy_unclassified_count: int
    proportion_exact_or_regional: float | None
    proportion_analogue: float | None
    proportion_proxy_or_reviewed: float | None
    min_mapping_confidence: float | None
    # mass-weighted (by each ingredient's quantity_g) average confidence
    # — more meaningful than a flat average when ingredients vary wildly
    # in how much they actually contribute to the dish
    weighted_mapping_confidence: float | None
    fallback_resolution_count: int
    unresolved_or_low_confidence_count: int
    # Recipe.match_coverage_mass, reused verbatim (not recomputed) — how
    # much of the recipe's ingredient *mass* has real matched nutrient
    # data. None for a plain user-built recipe (no matching pipeline ever
    # ran against it), never assumed to be 1.0 here — a caller deciding
    # how to treat "no data" for scoring purposes is a separate policy
    # choice (see recommend_recipes.py), not this summary's job.
    nutrient_coverage: float | None


def compute_recipe_quality_summary(
    db: Session, recipe: Recipe, ingredients: list[RecipeIngredient],
) -> RecipeQualitySummary:
    provenance_by_ingredient_id = {
        p.recipe_ingredient_id: p
        for p in db.query(RecipeIngredientProvenance)
        .filter(RecipeIngredientProvenance.recipe_ingredient_id.in_([i.id for i in ingredients]))
        .all()
    }

    unmapped = 0
    exact_or_regional = 0
    analogue = 0
    proxy_or_reviewed = 0
    fuzzy_unclassified = 0
    fallback_count = 0
    low_confidence_count = 0
    confidences: list[tuple[float, float]] = []  # (confidence, quantity_g) for weighting

    for ingredient in ingredients:
        provenance = provenance_by_ingredient_id.get(ingredient.id)
        if provenance is None:
            unmapped += 1
            continue

        if provenance.match_relationship in _EXACT_RELATIONSHIPS:
            exact_or_regional += 1
        elif provenance.match_relationship in _ANALOGUE_RELATIONSHIPS:
            analogue += 1
        elif provenance.match_relationship in _PROXY_RELATIONSHIPS:
            proxy_or_reviewed += 1
        elif provenance.match_relationship is None and provenance.match_method in _EXACT_METHODS:
            exact_or_regional += 1
        elif provenance.match_method == "fuzzy":
            fuzzy_unclassified += 1

        if provenance.match_used_fallback:
            fallback_count += 1
        if provenance.match_confidence is not None:
            confidences.append((provenance.match_confidence, ingredient.quantity_g))
            if provenance.match_confidence < LOW_CONFIDENCE_THRESHOLD:
                low_confidence_count += 1

    classified = exact_or_regional + analogue + proxy_or_reviewed
    total = len(ingredients)

    min_confidence = min((c for c, _ in confidences), default=None)
    if confidences:
        total_mass = sum(mass for _, mass in confidences)
        weighted_confidence = (
            sum(c * mass for c, mass in confidences) / total_mass if total_mass > 0 else None
        )
    else:
        weighted_confidence = None

    unresolved_lines = len(recipe.unresolved_ingredients or [])

    return RecipeQualitySummary(
        ingredient_count=total,
        unmapped_count=unmapped,
        exact_or_regional_count=exact_or_regional,
        analogue_count=analogue,
        proxy_or_reviewed_count=proxy_or_reviewed,
        fuzzy_unclassified_count=fuzzy_unclassified,
        proportion_exact_or_regional=(exact_or_regional / classified) if classified else None,
        proportion_analogue=(analogue / classified) if classified else None,
        proportion_proxy_or_reviewed=(proxy_or_reviewed / classified) if classified else None,
        min_mapping_confidence=min_confidence,
        weighted_mapping_confidence=weighted_confidence,
        fallback_resolution_count=fallback_count,
        unresolved_or_low_confidence_count=unresolved_lines + low_confidence_count,
        nutrient_coverage=recipe.match_coverage_mass,
    )
