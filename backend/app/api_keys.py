"""API key generation, hashing, and the auth+quota dependency for the
versioned public API (/api/v1/*) — see routers/public_api.py and
routers/api_keys.py. Separate credential system from the JWT session auth
in auth.py: a public API key is a long-lived, per-integration credential,
not a login session, and quota-metered rather than just identity-checked.
"""

import hashlib
import secrets
from datetime import date

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .billing import billing_provider
from .database import get_db
from .models import ApiKey, User

KEY_PREFIX_LENGTH = 12
QUOTA_PERIOD_DAYS = 30


def hash_api_key(key: str) -> str:
    """sha256, not bcrypt: API keys are high-entropy random tokens (256
    bits from secrets.token_urlsafe), not low-entropy human passwords —
    bcrypt's deliberately-slow hashing defends against brute-forcing a
    guessable secret, which isn't the threat model here, and would add a
    real ~100ms tax to every single API request. A fast cryptographic hash
    is the standard choice for this (the same approach GitHub and Stripe
    use for their API tokens)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, key_hash, key_prefix). full_key is meaningful
    exactly once — at creation time — and is never stored or retrievable
    again; only its hash is persisted."""
    full_key = f"nm_{secrets.token_urlsafe(32)}"
    return full_key, hash_api_key(full_key), full_key[:KEY_PREFIX_LENGTH]


def _maybe_reset_period(api_key: ApiKey) -> None:
    if (date.today() - api_key.period_started_at).days >= QUOTA_PERIOD_DAYS:
        api_key.requests_this_period = 0
        api_key.period_started_at = date.today()


def get_api_key_user(
    request: Request,
    x_api_key: str = Header(..., description="A key created via POST /api/api-keys"),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency for every /api/v1/* endpoint. Validates the key,
    enforces its rolling quota, records the request (both the real counter
    on ApiKey and the billing hook), and returns the owning User."""
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(x_api_key)).one_or_none()
    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    _maybe_reset_period(api_key)
    if api_key.requests_this_period >= api_key.quota_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Quota exceeded: {api_key.quota_limit} requests per {QUOTA_PERIOD_DAYS} days",
        )

    api_key.requests_this_period += 1
    db.commit()

    user = db.get(User, api_key.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    billing_provider.record_usage(user, api_key, request.url.path)
    return user
