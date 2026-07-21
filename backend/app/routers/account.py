from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("", response_model=schemas.UserOut)
def get_account(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("", response_model=schemas.UserOut)
def update_account(
    body: schemas.AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.currency is not None and (len(body.currency) != 3 or not body.currency.isalpha()):
        raise HTTPException(status_code=422, detail="currency must be a 3-letter ISO 4217 code (e.g. USD, GBP)")

    current_user.currency = body.currency.upper() if body.currency is not None else None
    db.commit()
    db.refresh(current_user)
    return current_user
