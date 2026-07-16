"""Password hashing and JWT issuance/verification.

Access-token-only (no refresh tokens) — see docs/auth-model-review.md for
the full reasoning, revisited now that commercial use is on the table.
Short version: refresh-token rotation is complexity nobody's confirmed
demand for yet, and this app's real revocation exposure is smaller than it
looks because the token only ever carries identity (`sub: user_id`), never
tier/permissions — those get checked against live DB state on every
request (see the entitlement layer in routers), so a stale-but-unexpired
token doesn't grant stale privileges, only continued access as that user.
Given that, the cheap lever that actually matters is a short expiry, not a
refresh-token system. Tokens are carried via the Authorization header, not
cookies, matching the frontend's CSR-only architecture.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

DEV_JWT_SECRET = "dev-secret-change-me"  # never valid when APP_ENV=production — see _resolve_jwt_secret


def _resolve_jwt_secret() -> str:
    """JWT_SECRET must be set explicitly whenever APP_ENV=production — the
    dev fallback below is a fixed, public string (it's right here in the
    source), so silently using it in production would let anyone forge a
    valid token for any user id. APP_ENV defaults to "development" so local
    runs and the test suite don't need to set anything. See DEPLOYMENT.md
    for the full list of required production environment variables."""
    secret = os.environ.get("JWT_SECRET")
    if secret is not None:
        return secret
    if os.environ.get("APP_ENV", "development") == "production":
        raise RuntimeError(
            "JWT_SECRET is not set and APP_ENV=production — refusing to start with the "
            "public dev fallback secret. Set JWT_SECRET to a real, private value. See DEPLOYMENT.md."
        )
    return DEV_JWT_SECRET


JWT_SECRET = _resolve_jwt_secret()
JWT_ALGORITHM = "HS256"
# Shortened from 7 days per docs/auth-model-review.md — there's no
# revocation mechanism, so this is the main lever against a stolen token
# staying valid for a long window. 24h balances that against not forcing
# a stuck-open frontend to re-prompt login mid-session.
JWT_EXPIRY = timedelta(hours=24)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + JWT_EXPIRY,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class InvalidToken(ValueError):
    pass


def decode_access_token(token: str) -> int:
    """Returns the user id encoded in the token, or raises InvalidToken."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as e:
        raise InvalidToken(str(e)) from e


_bearer = HTTPBearer()
_optional_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """For endpoints usable both signed-out and signed-in (e.g. food search)
    where a logged-in user's dietary constraints should apply but the
    endpoint itself doesn't require auth. Unlike get_current_user, a
    missing/invalid/expired token here just means "anonymous", never a 401
    — the caller gets an unfiltered result instead."""
    if credentials is None:
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidToken:
        return None
    return db.get(User, user_id)
