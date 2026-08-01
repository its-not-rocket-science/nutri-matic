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

import os
import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..email_sender import EmailNotConfigured, EmailSendFailed, send_email
from ..entitlements import PLAN_ENTERPRISE, PLAN_PROFESSIONAL, effective_plan
from ..models import ClinicianClientLink, ClinicianNote, Profile, User
from .diary import GroupBy, _compute_day_summary, _compute_trends

DEFAULT_INVITE_MESSAGE = (
    "I'd like to invite you to Nutri-Matic so I can help track your nutrition. "
    "Follow the link below to join — you'll be able to review and revoke my "
    "access at any time."
)


def _invite_join_url(token: str) -> str:
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    return f"{frontend_url.rstrip('/')}/invite/{token}"


def _invite_email_body(clinician_email: str, message: str, token: str) -> str:
    return (
        f"{message}\n\n"
        f"Join Nutri-Matic: {_invite_join_url(token)}\n\n"
        f"— sent on behalf of {clinician_email} via Nutri-Matic"
    )


def _link_out(link: ClinicianClientLink, clinician_email: str, client_email: str) -> schemas.ClinicianLinkOut:
    return schemas.ClinicianLinkOut(
        id=link.id, clinician_email=clinician_email, client_email=client_email,
        client_user_id=link.client_user_id, client_registered=link.client_user_id is not None,
        status=link.status, created_at=link.created_at, responded_at=link.responded_at,
    )


def _client_owner_profile(client_user_id: int, db: Session) -> Profile:
    """Clinician access targets the client's OWNER profile only — a
    family's other members aren't visible to the clinician yet (a
    deliberate, documented limitation, not an oversight)."""
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == client_user_id, Profile.is_account_owner.is_(True))
        .one_or_none()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Client has no owner profile")
    return profile

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
    own, regardless of who sends it.

    client_email not belonging to a registered user is no longer a 422:
    an unregistered invite is created instead (client_user_id=NULL,
    invite_email/invite_token/invite_message set), and an email is sent
    with a join link. routers/auth.py's register() resolves
    client_user_id automatically the moment that email registers — see
    models.ClinicianClientLink's docstring for why that still doesn't
    skip the explicit-accept step."""
    body_email = body.client_email.strip().lower()
    client = db.query(User).filter(User.email == body_email).one_or_none()
    if client is not None and client.id == current_user.id:
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

    if client is not None:
        existing = (
            db.query(ClinicianClientLink)
            .filter(
                ClinicianClientLink.clinician_user_id == current_user.id, ClinicianClientLink.client_user_id == client.id
            )
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
        return _link_out(link, current_user.email, client.email)

    existing = (
        db.query(ClinicianClientLink)
        .filter(
            ClinicianClientLink.clinician_user_id == current_user.id,
            ClinicianClientLink.invite_email == body_email,
            ClinicianClientLink.client_user_id.is_(None),
        )
        .one_or_none()
    )
    if existing is not None and existing.status != "revoked":
        raise HTTPException(status_code=409, detail=f"A link already exists with status '{existing.status}'")

    message = (body.message or DEFAULT_INVITE_MESSAGE).strip()
    token = secrets.token_urlsafe(32)

    if existing is not None:
        existing.status = "pending"
        existing.responded_at = None
        existing.invite_token = token
        existing.invite_message = message
        link = existing
    else:
        link = ClinicianClientLink(
            clinician_user_id=current_user.id, client_user_id=None,
            invite_email=body_email, invite_token=token, invite_message=message,
        )
        db.add(link)

    try:
        send_email(
            to=body_email,
            subject=f"{current_user.email} invited you to Nutri-Matic",
            body_text=_invite_email_body(current_user.email, message, token),
        )
    except EmailNotConfigured as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="Email sending is not configured") from e
    except EmailSendFailed as e:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Failed to send invite email: {e}") from e

    db.commit()
    db.refresh(link)
    return _link_out(link, current_user.email, body_email)


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
        _link_out(l, clinicians_by_id[l.clinician_user_id].email, current_user.email)
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
    return _link_out(link, clinician.email, current_user.email)


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
    return _link_out(link, clinician.email, current_user.email)


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
        _link_out(l, current_user.email, clients_by_id[l.client_user_id].email)
        for l in links
    ]


@router.get("/invites/sent", response_model=list[schemas.ClinicianLinkOut])
def list_sent_invites(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user's own outgoing pending invites — as the
    *clinician* side, covering both an invite still awaiting the
    (already-registered) client's accept, and one nobody has registered
    against yet. The latter has no other way to show up anywhere in this
    user's UI, unlike an already-registered invite's target (who sees it
    via list_pending_invites once they log in)."""
    links = (
        db.query(ClinicianClientLink)
        .filter(ClinicianClientLink.clinician_user_id == current_user.id, ClinicianClientLink.status == "pending")
        .all()
    )
    registered_client_ids = [l.client_user_id for l in links if l.client_user_id is not None]
    clients_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(registered_client_ids)).all()}
    return [
        _link_out(
            l, current_user.email,
            clients_by_id[l.client_user_id].email if l.client_user_id is not None else l.invite_email,
        )
        for l in links
    ]


@router.get("/invites/by-token/{token}", response_model=schemas.ClinicianInvitePreviewOut)
def get_invite_preview(token: str, db: Session = Depends(get_db)):
    """Public (no auth) — what the /invite/{token} landing page shows
    before the recipient has an account. 404s once the token's been
    consumed (client_user_id resolved — see routers/auth.py's register())
    or the invite was revoked, same as any other not-found resource in
    this app rather than a status-specific message that would leak which
    case applies to an unauthenticated caller."""
    link = (
        db.query(ClinicianClientLink)
        .filter(ClinicianClientLink.invite_token == token, ClinicianClientLink.status == "pending")
        .one_or_none()
    )
    if link is None or link.client_user_id is not None:
        raise HTTPException(status_code=404, detail="Invite not found")
    clinician = db.get(User, link.clinician_user_id)
    return schemas.ClinicianInvitePreviewOut(
        clinician_email=clinician.email, invite_email=link.invite_email, message=link.invite_message
    )


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
    day = _compute_day_summary(entry_date, _client_owner_profile(client_user_id, db), db)
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
    return _compute_trends(start_date, end_date, group_by, _client_owner_profile(client_user_id, db), db)


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
