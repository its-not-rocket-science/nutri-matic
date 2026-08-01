import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import create_access_token, create_owner_profile, get_current_user, hash_password, verify_password
from ..database import get_db
from ..demo_data import create_demo_account
from ..demo_protection import enforce_demo_rate_limit
from ..models import ClinicianClientLink, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
_demo_logger = logging.getLogger("app.demo")
_auth_logger = logging.getLogger("app.auth")


def _resolve_pending_clinician_invites(db: Session, user: User) -> None:
    """A clinician can invite an email that isn't registered yet (see
    routers/clinician.py's invite_client) — such a row sits with
    client_user_id=NULL until this runs. Matches case-insensitively since
    User.email isn't normalized to a single case at registration (see
    UserCreate's validator); resolves every matching invite, not just one,
    since more than one clinician can have invited the same address. This
    only ever fills in client_user_id — status stays "pending" and still
    requires this same explicit accept_invite the client would use for an
    invite sent to an already-registered email; see
    models.ClinicianClientLink's docstring."""
    pending_invites = (
        db.query(ClinicianClientLink)
        .filter(
            ClinicianClientLink.client_user_id.is_(None),
            ClinicianClientLink.status == "pending",
            func.lower(ClinicianClientLink.invite_email) == user.email.strip().lower(),
        )
        .all()
    )
    for link in pending_invites:
        link.client_user_id = user.id
        link.invite_email = None
        link.invite_token = None


@router.post("/register", response_model=schemas.TokenOut, status_code=201)
def register(body: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    create_owner_profile(db, user)
    _resolve_pending_clinician_invites(db, user)
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
        # Public-launch hardening prompt 6: "authentication failures at
        # an aggregate level" — a reason code only (never the email/
        # password themselves, and monitoring.scrub_event redacts any
        # email that somehow reached `extra=` regardless), so this is
        # safe to log even with Sentry active. Logged at ERROR, not
        # WARNING: `LoggingIntegration`'s `event_level=logging.ERROR`
        # means a WARNING here would only ever be a breadcrumb, never an
        # actual Sentry event/alert — Sentry groups identical events into
        # one issue with a count, which is exactly the "aggregate level"
        # signal this is meant to be.
        _auth_logger.error("auth_login_failed", extra={"reason": "invalid_credentials"})
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return schemas.TokenOut(access_token=create_access_token(user.id))


@router.post("/demo", response_model=schemas.TokenOut, status_code=201)
def start_demo(request: Request, db: Session = Depends(get_db)):
    """Creates a fresh, private, pre-seeded account and logs the caller
    straight into it — see demo_data.py for what's seeded and why this is
    a real per-visitor account rather than one shared login.

    Rate-limited (see demo_protection.py) — this is the one endpoint on
    the API that creates a real account for a completely unauthenticated
    caller, so it's the one most worth capping."""
    enforce_demo_rate_limit(request)
    try:
        token = create_demo_account(db)
    except Exception:
        _demo_logger.exception("demo_creation_failed")
        raise
    _demo_logger.info("demo_created")
    return schemas.TokenOut(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
