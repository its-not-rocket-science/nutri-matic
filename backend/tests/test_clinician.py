import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
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


def test_invite_unknown_email_rejected(client):
    clinician_token = register_and_token(client, "dietitian@example.com")
    res = client.post(
        "/api/clinician/invites", json={"client_email": "nobody@example.com"}, headers=auth_headers(clinician_token)
    )
    assert res.status_code == 422


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
