from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..dietary_tags import ALLERGEN_TAGS, DIETARY_PATTERNS, RELIGIOUS_REQUIREMENTS, TAGS
from ..models import (
    DiaryEntry,
    DiaryMealTemplate,
    DiaryMealTemplateItem,
    DiarySnapshot,
    DietaryConstraint,
    MealPlanEntry,
    MealPlanTemplate,
    MealPlanTemplateEntry,
    Profile,
    SavedFilterPreset,
    User,
    WeightLog,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

VALID_CATEGORIES = {"allergy", "intolerance", "religious", "medical", "preference"}
VALID_SEVERITIES = {"hard_exclude", "avoid"}
# must match the frontend's shared Goal type (lib/goals.ts). weight_loss/
# visceral_fat_reduction additionally drive a real calculation — see
# energy_goal.py's WEIGHT_LOSS_GOALS — the other four are purely UI framing.
VALID_GOALS = {
    "protein_quality", "nutrient_gaps", "budget", "exploring",
    "weight_loss", "visceral_fat_reduction",
}


def _validate_profile_body(body: schemas.ProfileCreate | schemas.ProfileUpdate) -> None:
    if body.dietary_pattern is not None and body.dietary_pattern not in DIETARY_PATTERNS:
        raise HTTPException(status_code=422, detail=f"Unknown dietary_pattern: {body.dietary_pattern}")
    if body.goal is not None and body.goal not in VALID_GOALS:
        raise HTTPException(status_code=422, detail=f"goal must be one of {sorted(VALID_GOALS)}")


@router.get("", response_model=list[schemas.ProfileOut])
def list_profiles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .order_by(Profile.is_account_owner.desc(), Profile.name)
        .all()
    )


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
        goal=body.goal,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


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
    )


@router.get("/{profile_id}", response_model=schemas.ProfileOut)
def get_profile(profile_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


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
    profile.goal = body.goal
    db.commit()
    db.refresh(profile)
    return profile


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
