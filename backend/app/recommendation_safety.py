""""Safety, clinical boundaries and explanation rules" — prompt 11 of the
nutrient-gap recommendation feature (see
docs/nutrient-gap-recommendations.md).

Centralises the rules every `recommend_*` module and the `/api/
recommendations/*` router must follow, so no module has to independently
re-decide them:

1. Never diagnose a nutrient deficiency — enforced by
   `nutrient_gap_analysis.NutrientStatus`'s vocabulary (below/near/within/
   above_preferred/above_upper_limit), never "deficient"/"excess".
2. Never claim a recommendation treats or prevents disease — enforced by
   wording convention across every `_explain()` in the `recommend_*`
   modules ("helps close the remaining X gap", never "treats X").
3. Never override a medically prescribed diet — `dietary_filter.py` never
   reads or acts on a `category="medical"` `DietaryConstraint` at all
   (see its module docstring); this module additionally surfaces
   `MEDICAL_CONSTRAINT_PRESENT` so a caller can display an explicit "this
   doesn't know your prescribed diet" notice rather than silent omission.
4. Never recommend a supplement — `candidate_metadata.py`'s curated
   table has no supplement entries and nothing in this feature queries
   a supplement category.
5. Never recommend exceeding a tolerable upper limit —
   `recommendation_scoring.py`'s `upper_limit_penalty` is large enough
   that `score_candidate` should never rank an upper-limit breach highly
   (see its adversarial regression tests); this module additionally
   tightens the upper limit itself for pregnancy/lactation (see
   `nutrient_targets.PREGNANCY_LACTATION_UPPER_LIMIT_MARGIN`).
6. Treat pregnancy, childhood, and other stored sensitive contexts
   conservatively — this module is where that's centralised (see
   `assess_eligibility` below).
7. Where target logic is insufficient for a sensitive profile, disable
   recommendations with a clear explanation rather than guessing — a
   profile below `MINIMUM_RECOMMENDATION_AGE` gets `enabled=False` here,
   since `energy_goal.py`/`protein_requirement.py`'s formulas are adult
   equations not validated for a growing child.
8/9/10. Estimates/variation/absorption disclaimers and the medical-advice
   boundary are the `SafetyWarningCode`s below, attached to every
   recommendation response rather than repeated in every card's prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy.orm import Session

from .energy import calculate_age
from .models import DietaryConstraint, Profile

# Below this age, the app's personalised energy (Mifflin-St Jeor-style EER)
# and protein (per-kg factor) target formulas are standard adult
# equations — not validated for a growing child, whose requirements don't
# scale the same way and change quickly with development. Rather than
# feeding a wrong number into a recommendation and guessing, recommendations
# are disabled outright below this age (prompt 11 requirement 7).
MINIMUM_RECOMMENDATION_AGE = 18


class SafetyWarningCode(str, Enum):
    """Structured codes a caller (API consumer or frontend) can branch on
    without parsing prose — prompt 11's "structured warning codes rather
    than relying only on prose"."""

    DATA_IS_ESTIMATE = "data_is_estimate"
    RECIPE_NUTRIENTS_VARY = "recipe_nutrients_vary"
    ABSORPTION_VARIES = "absorption_varies"
    PREGNANCY_CONSERVATIVE = "pregnancy_conservative"
    LACTATION_CONSERVATIVE = "lactation_conservative"
    MEDICAL_CONSTRAINT_PRESENT = "medical_constraint_present"


WARNING_MESSAGES: dict[SafetyWarningCode, str] = {
    SafetyWarningCode.DATA_IS_ESTIMATE: (
        "Nutrient values come from reference food-composition data — actual "
        "content varies by brand, growing conditions and preparation."
    ),
    SafetyWarningCode.RECIPE_NUTRIENTS_VARY: (
        "A recipe's real nutrient content depends on the exact ingredients, "
        "brands and cooking method used, which can differ from what's shown here."
    ),
    SafetyWarningCode.ABSORPTION_VARIES: (
        "How much of a nutrient the body actually absorbs, and how much any "
        "individual needs, both vary — these are population reference values, "
        "not a personal measurement, and this is general nutritional "
        "information rather than medical advice."
    ),
    SafetyWarningCode.PREGNANCY_CONSERVATIVE: (
        "This profile is marked as pregnant — upper-limit comparisons are kept "
        "extra conservative here, but this remains general nutritional "
        "information, not antenatal medical advice."
    ),
    SafetyWarningCode.LACTATION_CONSERVATIVE: (
        "This profile is marked as lactating — upper-limit comparisons are kept "
        "extra conservative here, but this remains general nutritional "
        "information, not medical advice."
    ),
    SafetyWarningCode.MEDICAL_CONSTRAINT_PRESENT: (
        "This profile has a stored medical dietary consideration. This feature "
        "does not read that note and does not know your prescribed diet's "
        "specific requirements — it must not be used to override it. Check "
        "with whoever prescribed it before changing what you eat."
    ),
}


@dataclass(frozen=True)
class RecommendationEligibility:
    """Whether the recommendation engine should run at all for this
    profile, and which standing warnings apply regardless of outcome.
    `enabled=False` means the caller should show `disabled_reason` and
    skip calling suggest_ingredients/suggest_recipes/suggest_substitutions/
    suggest_pairs entirely — never a guess dressed up as a real answer."""

    enabled: bool
    disabled_reason: str | None
    warnings: list[SafetyWarningCode] = field(default_factory=list)


def assess_eligibility(profile: Profile, db: Session) -> RecommendationEligibility:
    age = calculate_age(profile)
    if age is not None and age < MINIMUM_RECOMMENDATION_AGE:
        return RecommendationEligibility(
            enabled=False,
            disabled_reason=(
                f"This profile is under {MINIMUM_RECOMMENDATION_AGE} — the energy and protein "
                "targets this feature compares against use adult formulas that aren't valid "
                "for a growing child, so recommendations are disabled here rather than "
                "guessing. A paediatric dietitian is the right source for a child's "
                "nutrition targets."
            ),
        )

    warnings = [SafetyWarningCode.DATA_IS_ESTIMATE, SafetyWarningCode.ABSORPTION_VARIES]
    if profile.is_pregnant:
        warnings.append(SafetyWarningCode.PREGNANCY_CONSERVATIVE)
    if profile.is_lactating:
        warnings.append(SafetyWarningCode.LACTATION_CONSERVATIVE)

    has_medical_constraint = (
        db.query(DietaryConstraint)
        .filter(DietaryConstraint.profile_id == profile.id, DietaryConstraint.category == "medical")
        .first()
        is not None
    )
    if has_medical_constraint:
        warnings.append(SafetyWarningCode.MEDICAL_CONSTRAINT_PRESENT)

    return RecommendationEligibility(enabled=True, disabled_reason=None, warnings=warnings)


def recipe_warnings(base: list[SafetyWarningCode]) -> list[SafetyWarningCode]:
    """Recipe-mode responses additionally warn that a recipe's real
    nutrient content depends on exact ingredients/preparation — appended
    to whatever profile-level warnings `assess_eligibility` already
    produced, never replacing them."""
    return [*base, SafetyWarningCode.RECIPE_NUTRIENTS_VARY]
