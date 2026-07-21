from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user, get_owned_profile
from ..database import get_db
from ..models import Profile, User, WeightLog

router = APIRouter(prefix="/api/weight-logs", tags=["weight-logs"])


@router.post("", response_model=schemas.WeightLogOut, status_code=201)
def log_weight(
    body: schemas.WeightLogCreate,
    current_user: User = Depends(get_current_user),
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    log = (
        db.query(WeightLog)
        .filter(WeightLog.profile_id == profile.id, WeightLog.log_date == body.log_date)
        .one_or_none()
    )
    if log is None:
        log = WeightLog(user_id=current_user.id, profile_id=profile.id, log_date=body.log_date)
        db.add(log)
    log.weight_kg = body.weight_kg

    # keep the profile's weight_kg (used by energy.py's BMR/EER calc) in sync with
    # whatever the most recently *dated* log is — not necessarily the one just
    # logged, since a user might backfill an earlier missed day after the fact
    latest = (
        db.query(WeightLog)
        .filter(WeightLog.profile_id == profile.id)
        .order_by(WeightLog.log_date.desc())
        .first()
    )
    if latest is None or body.log_date >= latest.log_date:
        profile.weight_kg = body.weight_kg

    db.commit()
    db.refresh(log)
    return schemas.WeightLogOut(id=log.id, log_date=log.log_date, weight_kg=log.weight_kg)


@router.get("", response_model=list[schemas.WeightLogOut])
def list_weight_logs(
    start_date: date,
    end_date: date,
    profile: Profile = Depends(get_owned_profile),
    db: Session = Depends(get_db),
):
    logs = (
        db.query(WeightLog)
        .filter(
            WeightLog.profile_id == profile.id,
            WeightLog.log_date >= start_date,
            WeightLog.log_date <= end_date,
        )
        .order_by(WeightLog.log_date)
        .all()
    )
    return [schemas.WeightLogOut(id=log.id, log_date=log.log_date, weight_kg=log.weight_kg) for log in logs]


@router.delete("/{log_id}", status_code=204)
def delete_weight_log(log_id: int, profile: Profile = Depends(get_owned_profile), db: Session = Depends(get_db)):
    log = db.get(WeightLog, log_id)
    if log is None or log.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Weight log not found")
    db.delete(log)
    db.commit()
