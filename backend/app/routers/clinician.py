"""Clinician dashboard (Phase 4.2) — client management, per-client
micronutrient/protein-quality/bioavailability views, longitudinal
trends, and private clinician notes. See docs/professional-dashboard-scope.md
for exactly which of these are gated to the Professional plan versus
available to any account.

This app has no license-verification mechanism — "clinician" here means
"any registered user acting in that role," not a verified credential. See
the scope doc for why that's an explicit, disclosed limitation rather
than a claim of clinical verification.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..entitlements import PLAN_ENTERPRISE, PLAN_PROFESSIONAL, effective_plan
from ..models import ClinicianClientLink, ClinicianNote, User
from .diary import GroupBy, _compute_day_summary, _compute_trends

router = APIRouter(prefix="/api/clinician", tags=["clinician"])

# Any account can manage a small number of clients — this is the "available
# to any registered professional account" tier from the prompt. Beyond this,
# a Professional/Enterprise plan is required (see FREE_TIER_CLIENT_LIMIT
# usage below). Not enforced via entitlements.FEATURE_ENTITLEMENTS since
# that primitive is boolean allow/deny, not a numeric cap.
FREE_TIER_CLIENT_LIMIT = 3


def _require_active_link(clinician_id: int, client_user_id: int, db: Session) -> ClinicianClientLink:
    link = (
        db.query(ClinicianClientLink)
        .filter(
            ClinicianClientLink.clinician_user_id == clinician_id,
            ClinicianClientLink.client_user_id == client_user_id,
            ClinicianClientLink.status == "active",
        )
        .one_or_none()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="No active client link for that user")
    return link


@router.post("/invites", response_model=schemas.ClinicianLinkOut, status_code=201)
def invite_client(
    body: schemas.ClinicianInviteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Creates a pending link — access only becomes active once the client
    explicitly accepts (see accept_invite). Never grants access on its
    own, regardless of who sends it."""
    client = db.query(User).filter(User.email == body.client_email).one_or_none()
    if client is None:
        raise HTTPException(status_code=422, detail="No user with that email")
    if client.id == current_user.id:
        raise HTTPException(status_code=422, detail="Cannot invite yourself")

    active_count = (
        db.query(ClinicianClientLink)
        .filter(ClinicianClientLink.clinician_user_id == current_user.id, ClinicianClientLink.status == "active")
        .count()
    )
    if active_count >= FREE_TIER_CLIENT_LIMIT and effective_plan(current_user) not in (
        PLAN_PROFESSIONAL,
        PLAN_ENTERPRISE,
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Free accounts are limited to {FREE_TIER_CLIENT_LIMIT} active clients — "
                "upgrade to Professional for unlimited clients"
            ),
        )

    existing = (
        db.query(ClinicianClientLink)
        .filter(ClinicianClientLink.clinician_user_id == current_user.id, ClinicianClientLink.client_user_id == client.id)
        .one_or_none()
    )
    if existing is not None and existing.status != "revoked":
        raise HTTPException(status_code=409, detail=f"A link already exists with status '{existing.status}'")

    if existing is not None:
        existing.status = "pending"
        existing.responded_at = None
        link = existing
    else:
        link = ClinicianClientLink(clinician_user_id=current_user.id, client_user_id=client.id)
        db.add(link)
    db.commit()
    db.refresh(link)

    return schemas.ClinicianLinkOut(
        id=link.id, clinician_email=current_user.email, client_email=client.email, client_user_id=client.id,
        status=link.status, created_at=link.created_at, responded_at=link.responded_at,
    )


@router.get("/invites/pending", response_model=list[schemas.ClinicianLinkOut])
def list_pending_invites(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user's own pending invites — as the *client* side (an
    invite someone else sent them), so they can review who's asking for
    access before accepting."""
    links = (
        db.query(ClinicianClientLink)
        .filter(ClinicianClientLink.client_user_id == current_user.id, ClinicianClientLink.status == "pending")
        .all()
    )
    clinicians_by_id = {u.id: u for u in db.query(User).filter(User.id.in_([l.clinician_user_id for l in links])).all()}
    return [
        schemas.ClinicianLinkOut(
            id=l.id, clinician_email=clinicians_by_id[l.clinician_user_id].email, client_email=current_user.email,
            client_user_id=current_user.id,
            status=l.status, created_at=l.created_at, responded_at=l.responded_at,
        )
        for l in links
    ]


@router.post("/invites/{link_id}/accept", response_model=schemas.ClinicianLinkOut)
def accept_invite(link_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = db.get(ClinicianClientLink, link_id)
    if link is None or link.client_user_id != current_user.id or link.status != "pending":
        raise HTTPException(status_code=404, detail="No pending invite found")
    link.status = "active"
    link.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(link)
    clinician = db.get(User, link.clinician_user_id)
    return schemas.ClinicianLinkOut(
        id=link.id, clinician_email=clinician.email, client_email=current_user.email,
        client_user_id=current_user.id,
        status=link.status, created_at=link.created_at, responded_at=link.responded_at,
    )


@router.post("/invites/{link_id}/decline", response_model=schemas.ClinicianLinkOut)
def decline_invite(link_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = db.get(ClinicianClientLink, link_id)
    if link is None or link.client_user_id != current_user.id or link.status != "pending":
        raise HTTPException(status_code=404, detail="No pending invite found")
    link.status = "revoked"
    link.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(link)
    clinician = db.get(User, link.clinician_user_id)
    return schemas.ClinicianLinkOut(
        id=link.id, clinician_email=clinician.email, client_email=current_user.email,
        client_user_id=current_user.id,
        status=link.status, created_at=link.created_at, responded_at=link.responded_at,
    )


@router.delete("/clients/{client_user_id}", status_code=204)
def revoke_client(client_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Either party (clinician or client) can revoke an active link."""
    link = (
        db.query(ClinicianClientLink)
        .filter(
            ClinicianClientLink.client_user_id == client_user_id,
            ClinicianClientLink.clinician_user_id == current_user.id,
            ClinicianClientLink.status == "active",
        )
        .one_or_none()
    )
    if link is None:
        # maybe current_user is the client revoking their own clinician
        link = (
            db.query(ClinicianClientLink)
            .filter(
                ClinicianClientLink.clinician_user_id == client_user_id,
                ClinicianClientLink.client_user_id == current_user.id,
                ClinicianClientLink.status == "active",
            )
            .one_or_none()
        )
    if link is None:
        raise HTTPException(status_code=404, detail="No active link found")
    link.status = "revoked"
    link.responded_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/clients", response_model=list[schemas.ClinicianLinkOut])
def list_clients(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    links = (
        db.query(ClinicianClientLink)
        .filter(ClinicianClientLink.clinician_user_id == current_user.id, ClinicianClientLink.status == "active")
        .all()
    )
    clients_by_id = {u.id: u for u in db.query(User).filter(User.id.in_([l.client_user_id for l in links])).all()}
    return [
        schemas.ClinicianLinkOut(
            id=l.id, clinician_email=current_user.email, client_email=clients_by_id[l.client_user_id].email,
            client_user_id=l.client_user_id,
            status=l.status, created_at=l.created_at, responded_at=l.responded_at,
        )
        for l in links
    ]


@router.get("/clients/{client_user_id}/summary", response_model=schemas.ClinicianClientSummaryOut)
def get_client_summary(
    client_user_id: int,
    entry_date: date,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Micronutrient gaps, protein quality, and bioavailability at a glance
    for one client's day — reuses exactly the same live computation the
    client's own diary page uses (_compute_day_summary), just run against
    the client's profile/entries instead of the caller's own."""
    _require_active_link(current_user.id, client_user_id, db)
    client = db.get(User, client_user_id)
    day = _compute_day_summary(entry_date, client, db)
    return schemas.ClinicianClientSummaryOut(client_email=client.email, day=day)


@router.get("/clients/{client_user_id}/trends", response_model=schemas.DiaryTrendsOut)
def get_client_trends(
    client_user_id: int,
    start_date: date,
    end_date: date,
    group_by: GroupBy = "week",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Longitudinal comparison for one client — same trends computation the
    client's own /diary/trends uses."""
    _require_active_link(current_user.id, client_user_id, db)
    client = db.get(User, client_user_id)
    return _compute_trends(start_date, end_date, group_by, client, db)


@router.post("/clients/{client_user_id}/notes", response_model=schemas.ClinicianNoteOut, status_code=201)
def create_note(
    client_user_id: int,
    body: schemas.ClinicianNoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Private to the clinician — never exposed to the client via any
    endpoint (there is no GET route a client-side token could use to read
    another user's clinician notes about them)."""
    _require_active_link(current_user.id, client_user_id, db)
    note = ClinicianNote(clinician_user_id=current_user.id, client_user_id=client_user_id, note_text=body.note_text)
    db.add(note)
    db.commit()
    db.refresh(note)
    return schemas.ClinicianNoteOut(id=note.id, note_text=note.note_text, created_at=note.created_at)


@router.get("/clients/{client_user_id}/notes", response_model=list[schemas.ClinicianNoteOut])
def list_notes(client_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_active_link(current_user.id, client_user_id, db)
    notes = (
        db.query(ClinicianNote)
        .filter(ClinicianNote.clinician_user_id == current_user.id, ClinicianNote.client_user_id == client_user_id)
        .order_by(ClinicianNote.created_at.desc())
        .all()
    )
    return [schemas.ClinicianNoteOut(id=n.id, note_text=n.note_text, created_at=n.created_at) for n in notes]
