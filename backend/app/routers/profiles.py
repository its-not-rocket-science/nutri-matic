from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..dietary_tags import ALLERGEN_TAGS, CONDITIONS, DIETARY_PATTERNS, RELIGIOUS_REQUIREMENTS, TAGS
from ..goals import VALID_GOALS, attach_goals, load_goal_keys_batch, replace_goals
from ..models import (
    DiaryEntry,
    DiaryMealTemplate,
    DiaryMealTemplateItem,
    DiarySnapshot,
    DietaryConstraint,
    MealPlanEntry,
    MealPlanTemplate,
    MealPlanTemplateEntry,
    MedicalRecommendationAcknowledgement,
    Profile,
    ProfileGoal,
    SavedFilterPreset,
    User,
    WeightLog,
)
from ..recommendation_safety import (
    MEDICAL_ACKNOWLEDGEMENT_POLICY_VERSION,
    acknowledge_medical_constraints,
    has_active_medical_acknowledgement,
    revoke_medical_acknowledgements,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

VALID_CATEGORIES = {"allergy", "intolerance", "religious", "medical", "preference"}
VALID_SEVERITIES = {"hard_exclude", "avoid"}


def _validate_profile_body(body: schemas.ProfileCreate | schemas.ProfileUpdate) -> None:
    if body.dietary_pattern is not None and body.dietary_pattern not in DIETARY_PATTERNS:
        raise HTTPException(status_code=422, detail=f"Unknown dietary_pattern: {body.dietary_pattern}")
    if body.goal is not None and body.goal not in VALID_GOALS:
        raise HTTPException(status_code=422, detail=f"goal must be one of {sorted(VALID_GOALS)}")
    if body.goals is not None:
        unknown = [g for g in body.goals if g not in VALID_GOALS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"goal must be one of {sorted(VALID_GOALS)}")


def _resolved_goals(body: schemas.ProfileCreate | schemas.ProfileUpdate) -> list[str]:
    """`goals` (the ordered, priority-carrying field) wins if given at
    all — including an explicit empty list, which clears every goal.
    Falls back to wrapping the legacy single-value `goal` field so an
    old client that only ever sends `goal` keeps working unchanged."""
    if body.goals is not None:
        return body.goals
    return [body.goal] if body.goal else []


@router.get("", response_model=list[schemas.ProfileOut])
def list_profiles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profiles = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.is_account_owner.desc(), Profile.name)
        .all()
    )
    goals_by_profile_id = load_goal_keys_batch(db, [p.id for p in profiles])
    for p in profiles:
        p.goals = goals_by_profile_id.get(p.id, [])
    return profiles


@router.post("", response_model=schemas.ProfileOut, status_code=201)
def create_profile(
    body: schemas.ProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adds a household member (partner, child) under the caller's account
    — no separate login of their own, see models.Profile's docstring."""
    _validate_profile_body(body)
    profile = Profile(
        user_id=current_user.id,
        name=body.name,
        is_account_owner=False,
        sex=body.sex,
        birth_year=body.birth_year,
        activity_level=body.activity_level,
        is_pregnant=body.is_pregnant,
        is_lactating=body.is_lactating,
        weight_kg=body.weight_kg,
        height_cm=body.height_cm,
        dietary_pattern=body.dietary_pattern,
    )
    db.add(profile)
    db.flush()
    replace_goals(db, profile, _resolved_goals(body))
    db.commit()
    db.refresh(profile)
    return attach_goals(db, profile)


@router.get("/dietary-vocabulary", response_model=schemas.DietaryVocabularyOut)
def get_dietary_vocabulary():
    """Public, static, and identical for every caller — no auth needed."""
    return schemas.DietaryVocabularyOut(
        allergen_tags=[schemas.DietaryTagOut(key=k, label=TAGS[k]["label"]) for k in ALLERGEN_TAGS],
        religious_requirements=[
            schemas.DietaryPatternOut(key=k, label=v["label"], excludes=v["excludes"])
            for k, v in RELIGIOUS_REQUIREMENTS.items()
        ],
        dietary_patterns=[
            schemas.DietaryPatternOut(key=k, label=v["label"], excludes=v["excludes"])
            for k, v in DIETARY_PATTERNS.items()
        ],
        conditions=[
            schemas.ConditionOut(
                key=k, label=v["label"], maps_to_tag=v["maps_to_tag"], default_severity=v["default_severity"],
            )
            for k, v in CONDITIONS.items()
        ],
    )


@router.get("/{profile_id}", response_model=schemas.ProfileOut)
def get_profile(profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    return attach_goals(db, profile)


@router.put("/{profile_id}", response_model=schemas.ProfileOut)
def update_profile(
    profile_id: int,
    body: schemas.ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    _validate_profile_body(body)

    profile.name = body.name
    profile.sex = body.sex
    profile.birth_year = body.birth_year
    profile.activity_level = body.activity_level
    profile.is_pregnant = body.is_pregnant
    profile.is_lactating = body.is_lactating
    profile.weight_kg = body.weight_kg
    profile.height_cm = body.height_cm
    profile.dietary_pattern = body.dietary_pattern
    replace_goals(db, profile, _resolved_goals(body))
    db.commit()
    db.refresh(profile)
    return attach_goals(db, profile)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deletes a dependent profile and everything scoped to it (diary,
    weight log, meal plan, dietary constraints) — meaningless without the
    profile. The account owner profile can't be deleted this way (delete
    the account itself instead, a separate, not-yet-built flow)."""
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.is_account_owner:
        raise HTTPException(status_code=422, detail="The account owner profile can't be deleted")

    template_ids = [t.id for t in db.query(MealPlanTemplate).filter(MealPlanTemplate.profile_id == profile.id).all()]
    if template_ids:
        db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.template_id.in_(template_ids)).delete(
            synchronize_session=False
        )
    diary_template_ids = [
        t.id for t in db.query(DiaryMealTemplate).filter(DiaryMealTemplate.profile_id == profile.id).all()
    ]
    if diary_template_ids:
        db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.template_id.in_(diary_template_ids)).delete(
            synchronize_session=False
        )

    db.query(DietaryConstraint).filter(DietaryConstraint.profile_id == profile.id).delete(synchronize_session=False)
    db.query(ProfileGoal).filter(ProfileGoal.profile_id == profile.id).delete(synchronize_session=False)
    db.query(MedicalRecommendationAcknowledgement).filter(
        MedicalRecommendationAcknowledgement.profile_id == profile.id
    ).delete(synchronize_session=False)
    db.query(DiaryEntry).filter(DiaryEntry.profile_id == profile.id).delete(synchronize_session=False)
    db.query(DiarySnapshot).filter(DiarySnapshot.profile_id == profile.id).delete(synchronize_session=False)
    db.query(WeightLog).filter(WeightLog.profile_id == profile.id).delete(synchronize_session=False)
    db.query(MealPlanEntry).filter(MealPlanEntry.profile_id == profile.id).delete(synchronize_session=False)
    db.query(MealPlanTemplate).filter(MealPlanTemplate.profile_id == profile.id).delete(synchronize_session=False)
    db.query(DiaryMealTemplate).filter(DiaryMealTemplate.profile_id == profile.id).delete(synchronize_session=False)
    db.query(SavedFilterPreset).filter(SavedFilterPreset.profile_id == profile.id).delete(synchronize_session=False)

    db.delete(profile)
    db.commit()


@router.get("/{profile_id}/dietary-constraints", response_model=list[schemas.DietaryConstraintOut])
def list_dietary_constraints(
    profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    return (
        db.query(DietaryConstraint)
        .filter(DietaryConstraint.profile_id == profile.id)
        .order_by(DietaryConstraint.category, DietaryConstraint.id)
        .all()
    )


@router.post("/{profile_id}/dietary-constraints", response_model=schemas.DietaryConstraintOut, status_code=201)
def create_dietary_constraint(
    profile_id: int,
    body: schemas.DietaryConstraintCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")

    if body.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of {sorted(VALID_CATEGORIES)}")
    if body.severity is not None and body.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=422, detail=f"severity must be one of {sorted(VALID_SEVERITIES)}")
    if body.tag is not None and body.tag not in TAGS:
        raise HTTPException(status_code=422, detail=f"Unknown tag: {body.tag}")
    # medical/free-text preference rows are informational-only and never
    # matched against a food — see dietary_tags.py's module docstring
    if body.category in ("medical",) and body.tag is not None:
        raise HTTPException(status_code=422, detail="medical constraints are free-text only (tag must be null)")

    # Dedup only makes sense for a tagged row (allergy/intolerance/
    # religious) — exactly one row per (category, tag) is the intended
    # invariant there. A free-text medical/preference row always has
    # tag=None, so "duplicate" isn't a meaningful concept for it (two
    # different notes are two different considerations, not a conflict);
    # worse, checking category+tag alone for tag=None rows means a second
    # medical/preference note of any kind would incorrectly 409 against
    # the first, and a third would make .one_or_none() raise
    # MultipleResultsFound (500) once a profile has 2+ (e.g. via prompt
    # 3.1's condition picker, which can add several medical rows).
    if body.tag is not None:
        existing = (
            db.query(DietaryConstraint)
            .filter(
                DietaryConstraint.profile_id == profile.id,
                DietaryConstraint.category == body.category,
                DietaryConstraint.tag == body.tag,
            )
            .one_or_none()
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="This constraint already exists")

    constraint = DietaryConstraint(
        user_id=current_user.id,
        profile_id=profile.id,
        category=body.category,
        tag=body.tag,
        severity=body.severity,
        note=body.note,
    )
    db.add(constraint)
    db.commit()
    db.refresh(constraint)
    return constraint


@router.delete("/{profile_id}/dietary-constraints/{constraint_id}", status_code=204)
def delete_dietary_constraint(
    profile_id: int,
    constraint_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    constraint = db.get(DietaryConstraint, constraint_id)
    if constraint is None or constraint.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Constraint not found")
    db.delete(constraint)
    db.commit()


# --- conditions (prompt 3.1) --------------------------------------------
# A condition is just a curated, labelled shortcut onto the SAME
# DietaryConstraint rows an allergy/intolerance/medical entry already
# uses (see dietary_tags.CONDITIONS' docstring) — no parallel storage, no
# new filtering codepath. A tag-mapped condition (lactose intolerance,
# gluten intolerance/coeliac) creates a category="intolerance" row that
# dietary_filter.py already enforces exactly like any other allergy; an
# informational condition (type 2 diabetes, etc.) creates a plain
# category="medical" note, never auto-enforced, same as any other
# free-text medical entry.


def _find_condition_constraint(db: Session, profile: Profile, condition: dict) -> DietaryConstraint | None:
    query = db.query(DietaryConstraint).filter(DietaryConstraint.profile_id == profile.id)
    if condition["maps_to_tag"] is not None:
        query = query.filter(
            DietaryConstraint.category == "intolerance", DietaryConstraint.tag == condition["maps_to_tag"],
        )
    else:
        query = query.filter(DietaryConstraint.category == "medical", DietaryConstraint.note == condition["label"])
    return query.one_or_none()


@router.post("/{profile_id}/conditions/{condition_key}", response_model=schemas.DietaryConstraintOut, status_code=201)
def add_condition(
    profile_id: int,
    condition_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    condition = CONDITIONS.get(condition_key)
    if condition is None:
        raise HTTPException(status_code=422, detail=f"Unknown condition: {condition_key}")

    if _find_condition_constraint(db, profile, condition) is not None:
        raise HTTPException(status_code=409, detail="This condition is already set")

    constraint = DietaryConstraint(
        user_id=current_user.id,
        profile_id=profile.id,
        category="intolerance" if condition["maps_to_tag"] is not None else "medical",
        tag=condition["maps_to_tag"],
        severity=condition["default_severity"],
        note=condition["label"],
    )
    db.add(constraint)
    db.commit()
    db.refresh(constraint)
    return constraint


@router.delete("/{profile_id}/conditions/{condition_key}", status_code=204)
def remove_condition(
    profile_id: int,
    condition_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """No-op (204, not an error) if the condition wasn't set — same
    convention as revoke_medical_acknowledgement below."""
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    condition = CONDITIONS.get(condition_key)
    if condition is None:
        raise HTTPException(status_code=422, detail=f"Unknown condition: {condition_key}")

    existing = _find_condition_constraint(db, profile, condition)
    if existing is not None:
        db.delete(existing)
        db.commit()


# --- medical recommendation acknowledgement (hardening prompt 5) -------
# The *only* way to re-enable the nutrient-gap recommendation engine for
# a profile with a stored medical dietary constraint — see
# recommendation_safety.py's module docstring. Deliberately its own
# explicit endpoint pair, never a query-string flag on the
# recommendation endpoints themselves.

@router.get(
    "/{profile_id}/medical-acknowledgement", response_model=schemas.MedicalAcknowledgementOut | None,
)
def get_medical_acknowledgement(
    profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not has_active_medical_acknowledgement(profile, db):
        return None
    return (
        db.query(MedicalRecommendationAcknowledgement)
        .filter(
            MedicalRecommendationAcknowledgement.profile_id == profile.id,
            MedicalRecommendationAcknowledgement.revoked_at.is_(None),
            MedicalRecommendationAcknowledgement.policy_version == MEDICAL_ACKNOWLEDGEMENT_POLICY_VERSION,
        )
        .order_by(MedicalRecommendationAcknowledgement.id.desc())
        .first()
    )


@router.post(
    "/{profile_id}/medical-acknowledgement", response_model=schemas.MedicalAcknowledgementOut, status_code=201,
)
def create_medical_acknowledgement(
    profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Explicit opt-in re-enabling recommendations for this profile
    despite its stored medical dietary constraint — never implies
    medical clearance, and every hard dietary exclusion/upper-limit
    safeguard stays fully enforced regardless (see recommendation_
    safety.py). Always inserts a new row rather than mutating a past
    one — a full audit trail, matching RobustnessResult's convention."""
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    return acknowledge_medical_constraints(profile, db)


@router.delete("/{profile_id}/medical-acknowledgement", status_code=204)
def revoke_medical_acknowledgement(
    profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Always fully revocable — hardening prompt 5's explicit
    requirement. A no-op (204, not an error) if nothing was active."""
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    revoke_medical_acknowledgements(profile, db)
