""""Safety, clinical boundaries and explanation rules" — prompt 11 of the
nutrient-gap recommendation feature, strengthened by hardening prompt 5
(see docs/nutrient-gap-recommendations.md and
docs/nutrient-gap-recommendations-hardening.md).

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
   (see its module docstring). Hardening prompt 5 goes further: a
   profile with any medical constraint has the *entire engine* disabled
   by default (see `assess_eligibility`), not merely warned — re-enabling
   it requires an explicit, stored, revocable acknowledgement
   (`models.MedicalRecommendationAcknowledgement`), never a request
   parameter.
4. Never recommend a supplement — `candidate_metadata.py`'s curated
   table has no supplement entries and nothing in this feature queries
   a supplement category.
5. Never recommend exceeding a tolerable upper limit —
   `recommendation_scoring.py`'s `upper_limit_penalty` is large enough
   that `score_candidate` should never rank an upper-limit breach highly
   (see its adversarial regression tests); this module additionally
   tightens the upper limit itself for pregnancy/lactation (see
   `nutrient_targets.PREGNANCY_LACTATION_UPPER_LIMIT_MARGIN`).
6. Treat pregnancy, childhood, medical constraints, and other stored
   sensitive contexts conservatively — this module is where that's
   centralised (see `assess_eligibility` below).
7. Where target logic is insufficient for a sensitive profile, disable
   recommendations with a clear explanation rather than guessing — a
   profile below `MINIMUM_RECOMMENDATION_AGE`, or one with an
   unacknowledged medical constraint, gets `enabled=False` here (with a
   structured `disabled_reason_code` alongside the prose), rather than
   silently proceeding.
8/9/10. Estimates/variation/absorption disclaimers and the medical-advice
   boundary are the `SafetyWarningCode`s below, attached to every
   recommendation response rather than repeated in every card's prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.orm import Session

from .energy import calculate_age
from .models import DietaryConstraint, MedicalRecommendationAcknowledgement, Profile

# Below this age, the app's personalised energy (Mifflin-St Jeor-style EER)
# and protein (per-kg factor) target formulas are standard adult
# equations — not validated for a growing child, whose requirements don't
# scale the same way and change quickly with development. Rather than
# feeding a wrong number into a recommendation and guessing, recommendations
# are disabled outright below this age (prompt 11 requirement 7).
MINIMUM_RECOMMENDATION_AGE = 18

# Bump whenever the medical-acknowledgement's wording/scope changes
# materially — a past acknowledgement stamped with an older version no
# longer counts as active (see MedicalRecommendationAcknowledgement's own
# docstring), so a profile has to actively re-acknowledge under the new
# terms rather than being silently grandfathered in.
MEDICAL_ACKNOWLEDGEMENT_POLICY_VERSION = 1


class DisabledReasonCode(str, Enum):
    """Structured companion to `RecommendationEligibility.disabled_
    reason`'s prose — hardening prompt 5's "a structured reason code and
    a clear explanation", so a caller can branch on *why* the engine is
    disabled without parsing text."""

    UNDER_MINIMUM_AGE = "under_minimum_age"
    UNACKNOWLEDGED_MEDICAL_CONSTRAINT = "unacknowledged_medical_constraint"


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
    `enabled=False` means the caller should show `disabled_reason`
    (+ `disabled_reason_code`) and skip calling suggest_ingredients/
    suggest_recipes/suggest_substitutions/suggest_pairs entirely — never
    a guess dressed up as a real answer."""

    enabled: bool
    disabled_reason: str | None
    disabled_reason_code: DisabledReasonCode | None = None
    warnings: list[SafetyWarningCode] = field(default_factory=list)


def has_medical_constraint(profile: Profile, db: Session) -> bool:
    return (
        db.query(DietaryConstraint)
        .filter(DietaryConstraint.profile_id == profile.id, DietaryConstraint.category == "medical")
        .first()
        is not None
    )


def has_active_medical_acknowledgement(profile: Profile, db: Session) -> bool:
    """An acknowledgement counts as active only under the *current*
    policy version — see MEDICAL_ACKNOWLEDGEMENT_POLICY_VERSION's own
    docstring for why an older one doesn't carry forward automatically."""
    return (
        db.query(MedicalRecommendationAcknowledgement)
        .filter(
            MedicalRecommendationAcknowledgement.profile_id == profile.id,
            MedicalRecommendationAcknowledgement.revoked_at.is_(None),
            MedicalRecommendationAcknowledgement.policy_version == MEDICAL_ACKNOWLEDGEMENT_POLICY_VERSION,
        )
        .first()
        is not None
    )


def acknowledge_medical_constraints(profile: Profile, db: Session) -> MedicalRecommendationAcknowledgement:
    """Records a new, explicit opt-in — never mutates a past row (see the
    model's own docstring for why: a full history, not just current
    state). Does not itself check that a medical constraint exists;
    acknowledging when there's nothing to acknowledge is harmless (it
    simply has no effect, since `assess_eligibility` only ever consults
    this when `has_medical_constraint` is true)."""
    ack = MedicalRecommendationAcknowledgement(
        profile_id=profile.id, policy_version=MEDICAL_ACKNOWLEDGEMENT_POLICY_VERSION,
    )
    db.add(ack)
    db.commit()
    db.refresh(ack)
    return ack


def revoke_medical_acknowledgements(profile: Profile, db: Session) -> int:
    """Revokes every currently-active acknowledgement for this profile —
    always fully revocable, per hardening prompt 5's explicit
    requirement. Returns the number of rows revoked (0 if none were
    active)."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(MedicalRecommendationAcknowledgement)
        .filter(
            MedicalRecommendationAcknowledgement.profile_id == profile.id,
            MedicalRecommendationAcknowledgement.revoked_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.revoked_at = now
    db.commit()
    return len(rows)


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
            disabled_reason_code=DisabledReasonCode.UNDER_MINIMUM_AGE,
        )

    warnings = [SafetyWarningCode.DATA_IS_ESTIMATE, SafetyWarningCode.ABSORPTION_VARIES]
    if profile.is_pregnant:
        warnings.append(SafetyWarningCode.PREGNANCY_CONSERVATIVE)
    if profile.is_lactating:
        warnings.append(SafetyWarningCode.LACTATION_CONSERVATIVE)

    if has_medical_constraint(profile, db):
        warnings.append(SafetyWarningCode.MEDICAL_CONSTRAINT_PRESENT)
        if not has_active_medical_acknowledgement(profile, db):
            return RecommendationEligibility(
                enabled=False,
                disabled_reason=(
                    "This profile has a stored medical dietary consideration, so "
                    "recommendations are disabled by default — this feature doesn't know "
                    "what your prescribed diet actually requires and must not be used to "
                    "override it. If you understand this and still want general "
                    "nutritional suggestions, you can explicitly acknowledge this in your "
                    "profile settings; hard dietary exclusions and upper-limit safeguards "
                    "stay fully enforced either way, and acknowledging this is not medical "
                    "clearance."
                ),
                disabled_reason_code=DisabledReasonCode.UNACKNOWLEDGED_MEDICAL_CONSTRAINT,
                warnings=warnings,
            )
        # acknowledged and active — engine runs, but the warning keeps
        # showing on every response regardless (prompt 5: "continue to
        # show the warning"), never silently dropped once acknowledged

    return RecommendationEligibility(enabled=True, disabled_reason=None, warnings=warnings)


def recipe_warnings(base: list[SafetyWarningCode]) -> list[SafetyWarningCode]:
    """Recipe-mode responses additionally warn that a recipe's real
    nutrient content depends on exact ingredients/preparation — appended
    to whatever profile-level warnings `assess_eligibility` already
    produced, never replacing them."""
    return [*base, SafetyWarningCode.RECIPE_NUTRIENTS_VARY]
