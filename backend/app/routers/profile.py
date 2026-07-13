from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=schemas.UserOut)
def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("", response_model=schemas.UserOut)
def update_profile(
    body: schemas.ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.sex = body.sex
    current_user.birth_year = body.birth_year
    current_user.activity_level = body.activity_level
    current_user.is_pregnant = body.is_pregnant
    current_user.is_lactating = body.is_lactating
    current_user.weight_kg = body.weight_kg
    current_user.height_cm = body.height_cm
    db.commit()
    db.refresh(current_user)
    return current_user
