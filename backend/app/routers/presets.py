from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user, get_owned_profile
from ..database import get_db
from ..models import Profile, SavedFilterPreset, User
from ..search import FOOD_FILTER_KEYS, RECIPE_FILTER_KEYS

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _valid_keys_for_scope(scope: str) -> set[str]:
    return FOOD_FILTER_KEYS if scope == "food" else RECIPE_FILTER_KEYS


def _preset_out(preset: SavedFilterPreset) -> schemas.SavedFilterPresetOut:
    return schemas.SavedFilterPresetOut(
        id=preset.id,
        name=preset.name,
        scope=preset.scope,
        filters=[schemas.NutrientFilterIn(**f) for f in preset.filters],
    )


@router.post("", response_model=schemas.SavedFilterPresetOut, status_code=201)
def create_preset(
    body: schemas.SavedFilterPresetCreate,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    unknown = {f.key for f in body.filters} - _valid_keys_for_scope(body.scope)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown filter key(s) for scope '{body.scope}': {sorted(unknown)}")

    preset = SavedFilterPreset(
        user_id=current_user.id,
        profile_id=profile.id,
        name=body.name,
        scope=body.scope,
        filters=[f.model_dump() for f in body.filters],
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return _preset_out(preset)


@router.get("", response_model=list[schemas.SavedFilterPresetOut])
def list_presets(
    scope: schemas.Scope | None = None,
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    query = db.query(SavedFilterPreset).filter(SavedFilterPreset.profile_id == profile.id)
    if scope is not None:
        query = query.filter(SavedFilterPreset.scope == scope)
    presets = query.order_by(SavedFilterPreset.name).all()
    return [_preset_out(p) for p in presets]


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: int, profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    preset = db.get(SavedFilterPreset, preset_id)
    if preset is None or preset.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.delete(preset)
    db.commit()
