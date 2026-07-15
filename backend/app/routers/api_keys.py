from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..api_keys import generate_api_key
from ..auth import get_current_user
from ..database import get_db
from ..entitlements import API_QUOTA_BY_PLAN, DEFAULT_API_QUOTA, effective_plan
from ..models import ApiKey, User

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _key_out(key: ApiKey) -> schemas.ApiKeyOut:
    return schemas.ApiKeyOut(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
        quota_limit=key.quota_limit,
        requests_this_period=key.requests_this_period,
        period_started_at=key.period_started_at,
    )


@router.post("", response_model=schemas.ApiKeyCreatedOut, status_code=201)
def create_api_key(body: schemas.ApiKeyCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Creates a new public-API credential for /api/v1/*. The raw key is
    returned exactly once, here — it's never stored (only its hash is) and
    can never be retrieved again after this response.

    quota_limit is set from the user's plan *at creation time* (see
    entitlements.API_QUOTA_BY_PLAN) — upgrading later doesn't retroactively
    raise an already-issued key's quota; create a new key to pick up a new
    plan's quota. A simple, honest limitation rather than a background job
    to keep every key in sync with a plan that may have changed."""
    quota_limit = API_QUOTA_BY_PLAN.get(effective_plan(current_user), DEFAULT_API_QUOTA)
    full_key, key_hash, key_prefix = generate_api_key()
    key = ApiKey(
        user_id=current_user.id, name=body.name, key_hash=key_hash, key_prefix=key_prefix, quota_limit=quota_limit
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    return schemas.ApiKeyCreatedOut(**_key_out(key).model_dump(), key=full_key)


@router.get("", response_model=list[schemas.ApiKeyOut])
def list_api_keys(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    keys = db.query(ApiKey).filter(ApiKey.user_id == current_user.id).order_by(ApiKey.created_at.desc()).all()
    return [_key_out(k) for k in keys]


@router.delete("/{key_id}", status_code=204)
def revoke_api_key(key_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revokes (does not delete) a key — get_api_key_user rejects any key
    with revoked_at set, but the row (and its usage history) is kept."""
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
