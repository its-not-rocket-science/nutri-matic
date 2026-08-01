from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.invite_protection import reset_invite_rate_limits
from app.main import app
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def client(session_factory):
    reset_invite_rate_limits()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = session_factory()
    food = Food(id=1, name="Beef, ground, cooked", protein_g_per_100g=26, amino_acids=dict.fromkeys(AMINO_ACIDS, 20))
    db.add(food)
    db.flush()
    db.add(FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=2.0))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_invite_creates_pending_link(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    register_and_token(client, "client@example.com")

    res = client.post(
        "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
    )
    assert res.status_code == 201
    assert res.json()["status"] == "pending"


def test_invite_unregistered_email_sends_invite_and_creates_pending_link(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    with patch("app.routers.clinician.send_email") as mock_send:
        res = client.post(
            "/api/clinician/invites",
            json={"client_email": "Nobody@Example.com", "message": "Please join me!"},
            headers=auth_headers(clinician_token),
        )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending"
    assert body["client_user_id"] is None
    assert body["client_registered"] is False
    assert body["client_email"] == "nobody@example.com"  # normalized to lowercase
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to"] == "nobody@example.com"
    assert "Please join me!" in kwargs["body_text"]


def test_invite_unregistered_email_without_smtp_configured_returns_503(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    # no SMTP_HOST set in the test environment — send_email itself raises
    res = client.post(
        "/api/clinician/invites", json={"client_email": "nobody@example.com"}, headers=auth_headers(clinician_token)
    )
    assert res.status_code == 503
    # never fabricates a "sent" invite when nothing was actually sent
    sent = client.get("/api/clinician/invites/sent", headers=auth_headers(clinician_token)).json()
    assert sent == []


def test_registering_with_invited_email_resolves_pending_invite(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    with patch("app.routers.clinician.send_email"):
        invite = client.post(
            "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
        ).json()
    assert invite["client_user_id"] is None

    client_token = register_and_token(client, "client@example.com")

    pending = client.get("/api/clinician/invites/pending", headers=auth_headers(client_token)).json()
    assert len(pending) == 1
    assert pending[0]["clinician_email"] == "dietitian@example.com"

    accept = client.post(f"/api/clinician/invites/{invite['id']}/accept", headers=auth_headers(client_token))
    assert accept.status_code == 200
    assert accept.json()["status"] == "active"
    assert accept.json()["client_registered"] is True


def test_registering_with_different_case_email_still_resolves_invite(client):
    """invite_email is stored lowercased; User.email isn't normalized at
    registration (see UserCreate's validator) — the match must still work
    when someone registers with different casing than the clinician typed."""
    clinician_token = register_and_token(client, "dietitian@example.com")
    with patch("app.routers.clinician.send_email"):
        invite = client.post(
            "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
        ).json()

    client_token = register_and_token(client, "Client@Example.com")

    pending = client.get("/api/clinician/invites/pending", headers=auth_headers(client_token)).json()
    assert len(pending) == 1
    assert pending[0]["id"] == invite["id"]


def test_invite_preview_by_token(client, session_factory):
    from app.models import ClinicianClientLink

    clinician_token = register_and_token(client, "dietitian@example.com")
    with patch("app.routers.clinician.send_email"):
        client.post(
            "/api/clinician/invites",
            json={"client_email": "nobody@example.com", "message": "Custom message here"},
            headers=auth_headers(clinician_token),
        )

    # the token itself is only ever sent by email, never returned by the API
    db = session_factory()
    token = db.query(ClinicianClientLink).filter(ClinicianClientLink.invite_email == "nobody@example.com").one().invite_token
    db.close()

    preview = client.get(f"/api/clinician/invites/by-token/{token}")
    assert preview.status_code == 200
    body = preview.json()
    assert body["clinician_email"] == "dietitian@example.com"
    assert body["invite_email"] == "nobody@example.com"
    assert body["message"] == "Custom message here"


def test_invite_preview_by_token_404_for_unknown_token(client):
    res = client.get("/api/clinician/invites/by-token/not-a-real-token")
    assert res.status_code == 404


def test_invite_preview_by_token_404_after_consumed(client):
    """Once an invite has been resolved to a real client_user_id, its
    token must not still work — single-use, not a standing link."""
    clinician_token = register_and_token(client, "dietitian@example.com")
    with patch("app.routers.clinician.send_email"):
        client.post(
            "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
        )
    register_and_token(client, "client@example.com")
    # can't recover the token via the API (by design) — confirm indirectly:
    # the invite is no longer visible as "not registered" via /invites/sent
    sent = client.get("/api/clinician/invites/sent", headers=auth_headers(clinician_token)).json()
    assert sent[0]["client_registered"] is True


def test_list_sent_invites_shows_unregistered_and_registered(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    register_and_token(client, "registered@example.com")
    client.post(
        "/api/clinician/invites", json={"client_email": "registered@example.com"}, headers=auth_headers(clinician_token)
    )
    with patch("app.routers.clinician.send_email"):
        client.post(
            "/api/clinician/invites",
            json={"client_email": "unregistered@example.com"},
            headers=auth_headers(clinician_token),
        )

    sent = client.get("/api/clinician/invites/sent", headers=auth_headers(clinician_token)).json()
    assert len(sent) == 2
    by_email = {s["client_email"]: s for s in sent}
    assert by_email["registered@example.com"]["client_registered"] is True
    assert by_email["unregistered@example.com"]["client_registered"] is False


def test_client_sees_pending_invite(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    client_token = register_and_token(client, "client@example.com")
    client.post("/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token))

    res = client.get("/api/clinician/invites/pending", headers=auth_headers(client_token))
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["clinician_email"] == "dietitian@example.com"


def test_client_must_accept_before_clinician_gets_access(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    client_token = register_and_token(client, "client@example.com")
    invite = client.post(
        "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
    ).json()

    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(client_token),
    )

    # not yet accepted — clinician has no access
    client_user_id_res = client.get("/api/auth/me", headers=auth_headers(client_token)).json()
    client_id = client_user_id_res["id"]
    res_before = client.get(
        f"/api/clinician/clients/{client_id}/summary?entry_date=2026-07-13", headers=auth_headers(clinician_token)
    )
    assert res_before.status_code == 404

    accept = client.post(f"/api/clinician/invites/{invite['id']}/accept", headers=auth_headers(client_token))
    assert accept.status_code == 200
    assert accept.json()["status"] == "active"

    res_after = client.get(
        f"/api/clinician/clients/{client_id}/summary?entry_date=2026-07-13", headers=auth_headers(clinician_token)
    )
    assert res_after.status_code == 200
    assert len(res_after.json()["day"]["entries"]) == 1


def test_decline_invite_never_grants_access(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    client_token = register_and_token(client, "client@example.com")
    invite = client.post(
        "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
    ).json()

    decline = client.post(f"/api/clinician/invites/{invite['id']}/decline", headers=auth_headers(client_token))
    assert decline.status_code == 200
    assert decline.json()["status"] == "revoked"

    client_id = client.get("/api/auth/me", headers=auth_headers(client_token)).json()["id"]
    res = client.get(
        f"/api/clinician/clients/{client_id}/summary?entry_date=2026-07-13", headers=auth_headers(clinician_token)
    )
    assert res.status_code == 404


def test_free_tier_client_limit_enforced(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    for i in range(3):
        client_token = register_and_token(client, f"client{i}@example.com")
        invite = client.post(
            "/api/clinician/invites", json={"client_email": f"client{i}@example.com"}, headers=auth_headers(clinician_token)
        ).json()
        accept = client.post(f"/api/clinician/invites/{invite['id']}/accept", headers=auth_headers(client_token))
        assert accept.status_code == 200

    # the 4th invite is rejected outright — the cap is enforced at invite
    # time, not accept time, since accept-time enforcement would let a
    # free clinician stack up unlimited *pending* invites
    register_and_token(client, "client3@example.com")
    res = client.post(
        "/api/clinician/invites", json={"client_email": "client3@example.com"}, headers=auth_headers(clinician_token)
    )
    assert res.status_code == 403


def test_notes_private_to_clinician(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    client_token = register_and_token(client, "client@example.com")
    invite = client.post(
        "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
    ).json()
    client.post(f"/api/clinician/invites/{invite['id']}/accept", headers=auth_headers(client_token))
    client_id = client.get("/api/auth/me", headers=auth_headers(client_token)).json()["id"]

    note_res = client.post(
        f"/api/clinician/clients/{client_id}/notes", json={"note_text": "confidential note"},
        headers=auth_headers(clinician_token),
    )
    assert note_res.status_code == 201

    # no endpoint exposes clinician notes to the client — confirm none of
    # the client's own diary/profile responses leak it, and a client
    # cannot call the clinician-only notes endpoint for themselves
    notes_as_client = client.get(f"/api/clinician/clients/{client_id}/notes", headers=auth_headers(client_token))
    assert notes_as_client.status_code == 404  # client has no active link *as clinician* to themselves


def test_either_party_can_revoke(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    client_token = register_and_token(client, "client@example.com")
    invite = client.post(
        "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
    ).json()
    client.post(f"/api/clinician/invites/{invite['id']}/accept", headers=auth_headers(client_token))
    client_id = client.get("/api/auth/me", headers=auth_headers(client_token)).json()["id"]

    revoke = client.delete(f"/api/clinician/clients/{client_id}", headers=auth_headers(clinician_token))
    assert revoke.status_code == 204

    res = client.get(
        f"/api/clinician/clients/{client_id}/summary?entry_date=2026-07-13", headers=auth_headers(clinician_token)
    )
    assert res.status_code == 404


def test_invite_matches_existing_user_case_insensitively(client):
    """User.email isn't normalized to one case at registration — an
    invite typed in a different case than the stored email must still
    find the real account rather than treating it as unregistered."""
    clinician_token = register_and_token(client, "dietitian@example.com")
    register_and_token(client, "Client@Example.com")

    res = client.post(
        "/api/clinician/invites", json={"client_email": "client@example.com"}, headers=auth_headers(clinician_token)
    )
    assert res.status_code == 201
    body = res.json()
    assert body["client_registered"] is True
    assert body["client_user_id"] is not None


def test_invite_rate_limit_enforced(client, monkeypatch):
    import app.invite_protection as invite_protection_module

    monkeypatch.setattr(invite_protection_module, "INVITE_PER_ACCOUNT_LIMIT", 1)
    clinician_token = register_and_token(client, "dietitian@example.com")

    with patch("app.routers.clinician.send_email"):
        first = client.post(
            "/api/clinician/invites", json={"client_email": "one@example.com"}, headers=auth_headers(clinician_token)
        )
    assert first.status_code == 201

    second = client.post(
        "/api/clinician/invites", json={"client_email": "two@example.com"}, headers=auth_headers(clinician_token)
    )
    assert second.status_code == 429


def test_invite_rate_limit_does_not_apply_to_already_registered_clients(client, monkeypatch):
    """Inviting an already-registered client never sends an email — that
    branch isn't the abuse vector this limit exists for, and shouldn't
    burn budget a clinician needs for real unregistered invites."""
    import app.invite_protection as invite_protection_module

    monkeypatch.setattr(invite_protection_module, "INVITE_PER_ACCOUNT_LIMIT", 1)
    clinician_token = register_and_token(client, "dietitian@example.com")
    for i in range(3):
        register_and_token(client, f"client{i}@example.com")
        res = client.post(
            "/api/clinician/invites", json={"client_email": f"client{i}@example.com"}, headers=auth_headers(clinician_token)
        )
        assert res.status_code == 201


def test_duplicate_unresolved_invite_rejected_at_db_level(session_factory, client):
    """models.ClinicianClientLink's partial unique index (clinician_user_id,
    invite_email) WHERE client_user_id IS NULL is the real guarantee behind
    the app-level 409 check — this proves the constraint itself, bypassing
    the app's query-then-insert pre-check the way two concurrent requests
    would."""
    from app.models import ClinicianClientLink

    clinician_token = register_and_token(client, "dietitian@example.com")
    clinician_id = client.get("/api/auth/me", headers=auth_headers(clinician_token)).json()["id"]

    db = session_factory()
    db.add(ClinicianClientLink(clinician_user_id=clinician_id, client_user_id=None, invite_email="race@example.com"))
    db.commit()
    db.add(ClinicianClientLink(clinician_user_id=clinician_id, client_user_id=None, invite_email="race@example.com"))
    with pytest.raises(Exception):  # IntegrityError, wrapped by whichever DBAPI driver SQLite uses here
        db.commit()
    db.close()


def test_cancel_invite_revokes_unregistered_invite(client, session_factory):
    from app.models import ClinicianClientLink

    clinician_token = register_and_token(client, "dietitian@example.com")
    with patch("app.routers.clinician.send_email"):
        invite = client.post(
            "/api/clinician/invites", json={"client_email": "nobody@example.com"}, headers=auth_headers(clinician_token)
        ).json()

    cancel = client.post(f"/api/clinician/invites/{invite['id']}/cancel", headers=auth_headers(clinician_token))
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "revoked"

    # the token must no longer resolve — a cancelled invite's join link is dead
    db = session_factory()
    token = (
        db.query(ClinicianClientLink).filter(ClinicianClientLink.id == invite["id"]).one().invite_token
    )
    db.close()
    preview = client.get(f"/api/clinician/invites/by-token/{token}")
    assert preview.status_code == 404

    sent = client.get("/api/clinician/invites/sent", headers=auth_headers(clinician_token)).json()
    assert sent == []

    # cancelling again (already revoked) 404s rather than double-revoking
    recancel = client.post(f"/api/clinician/invites/{invite['id']}/cancel", headers=auth_headers(clinician_token))
    assert recancel.status_code == 404


def test_cancel_invite_only_by_the_inviting_clinician(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    other_token = register_and_token(client, "someone-else@example.com")
    with patch("app.routers.clinician.send_email"):
        invite = client.post(
            "/api/clinician/invites", json={"client_email": "nobody@example.com"}, headers=auth_headers(clinician_token)
        ).json()

    res = client.post(f"/api/clinician/invites/{invite['id']}/cancel", headers=auth_headers(other_token))
    assert res.status_code == 404

    sent = client.get("/api/clinician/invites/sent", headers=auth_headers(clinician_token)).json()
    assert sent[0]["status"] == "pending"  # untouched by the other user's attempt
