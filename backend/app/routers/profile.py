from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..dietary_tags import ALLERGEN_TAGS, DIETARY_PATTERNS, RELIGIOUS_REQUIREMENTS, TAGS
from ..models import DietaryConstraint, User

router = APIRouter(prefix="/api/profile", tags=["profile"])

VALID_CATEGORIES = {"allergy", "intolerance", "religious", "medical", "preference"}
VALID_SEVERITIES = {"hard_exclude", "avoid"}


@router.get("", response_model=schemas.UserOut)
def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("", response_model=schemas.UserOut)
def update_profile(
    body: schemas.ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.dietary_pattern is not None and body.dietary_pattern not in DIETARY_PATTERNS:
        raise HTTPException(status_code=422, detail=f"Unknown dietary_pattern: {body.dietary_pattern}")

    current_user.sex = body.sex
    current_user.birth_year = body.birth_year
    current_user.activity_level = body.activity_level
    current_user.is_pregnant = body.is_pregnant
    current_user.is_lactating = body.is_lactating
    current_user.weight_kg = body.weight_kg
    current_user.height_cm = body.height_cm
    current_user.dietary_pattern = body.dietary_pattern
    db.commit()
    db.refresh(current_user)
    return current_user


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


@router.get("/dietary-constraints", response_model=list[schemas.DietaryConstraintOut])
def list_dietary_constraints(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(DietaryConstraint)
        .filter(DietaryConstraint.user_id == current_user.id)
        .order_by(DietaryConstraint.category, DietaryConstraint.id)
        .all()
    )


@router.post("/dietary-constraints", response_model=schemas.DietaryConstraintOut, status_code=201)
def create_dietary_constraint(
    body: schemas.DietaryConstraintCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
            DietaryConstraint.user_id == current_user.id,
            DietaryConstraint.category == body.category,
            DietaryConstraint.tag == body.tag,
        )
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This constraint already exists")

    constraint = DietaryConstraint(
        user_id=current_user.id,
        category=body.category,
        tag=body.tag,
        severity=body.severity,
        note=body.note,
    )
    db.add(constraint)
    db.commit()
    db.refresh(constraint)
    return constraint


@router.delete("/dietary-constraints/{constraint_id}", status_code=204)
def delete_dietary_constraint(
    constraint_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    constraint = db.get(DietaryConstraint, constraint_id)
    if constraint is None or constraint.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Constraint not found")
    db.delete(constraint)
    db.commit()
