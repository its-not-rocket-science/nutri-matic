from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import create_access_token, create_owner_profile, get_current_user, hash_password, verify_password
from ..database import get_db
from ..demo_data import create_demo_account
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenOut, status_code=201)
def register(body: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    create_owner_profile(db, user)
    db.commit()
    db.refresh(user)
    return schemas.TokenOut(access_token=create_access_token(user.id))


@router.post("/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).one_or_none()
    # is_system accounts (the stock-recipe library's owner — see
    # models.User.is_system) are never a valid login target, regardless of
    # password: nobody is meant to know that password (it's a random value
    # generated once at bootstrap, same pattern as demo_data.py), but this
    # is a second, explicit layer rather than relying on secrecy alone.
    if user is None or user.is_system or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return schemas.TokenOut(access_token=create_access_token(user.id))


@router.post("/demo", response_model=schemas.TokenOut, status_code=201)
def start_demo(db: Session = Depends(get_db)):
    """Creates a fresh, private, pre-seeded account and logs the caller
    straight into it — see demo_data.py for what's seeded and why this is
    a real per-visitor account rather than one shared login."""
    return schemas.TokenOut(access_token=create_demo_account(db))


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
