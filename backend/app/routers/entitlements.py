from fastapi import APIRouter, Depends

from .. import schemas
from ..auth import get_current_user
from ..entitlements import effective_plan
from ..models import User

router = APIRouter(prefix="/api/entitlements", tags=["entitlements"])


@router.get("", response_model=schemas.EntitlementsOut)
def get_entitlements(current_user: User = Depends(get_current_user)):
    """Primitive surface for the entitlement layer (see entitlements.py) —
    lets the frontend (or any client) know the signed-in user's plan
    without needing to guess it from which endpoints 403. Not itself a
    gated endpoint; no plan is required to check your own plan."""
    return schemas.EntitlementsOut(
        plan=current_user.plan,
        effective_plan=effective_plan(current_user),
        plan_expires_at=current_user.plan_expires_at,
    )
