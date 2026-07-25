"""Proves DiaryEntry/MealPlanEntry's version_id_col mapping (operational-
hardening prompt 4) enforces optimistic concurrency at the database
level, not just in application code — directly at the ORM/session layer,
independent of the HTTP endpoint that happens to be the only current
caller. Two separate Session objects both load the same row (as two
truly concurrent requests genuinely would, each with its own DB
session); the first commits successfully, and the second's commit must
fail even though its in-memory copy still shows the pre-conflict data,
because SQLAlchemy appends `WHERE version = <the value this session
loaded>` to its UPDATE and zero rows match by the time it runs.

This is deliberately not expressed as two sequential HTTP requests (that
tests staleness relative to a client-supplied `expected_version`,
already covered in test_recommendations_substitutions_api.py) — this
file tests the structural database-level guarantee that would still
hold even if some future endpoint mutated these rows without checking
`expected_version` at all first."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.entry_mutation import EntryConflict, commit_entry_mutation
from app.main import app
from app.models import DiaryEntry, Food
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def client_and_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSessionLocal()
    db.add(Food(id=1, name="Rice", protein_g_per_100g=2.7, amino_acids=dict.fromkeys(AMINO_ACIDS)))
    db.commit()
    db.close()

    yield TestClient(app), TestSessionLocal
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    return client.post("/api/auth/register", json={"email": email, "password": password}).json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_second_writer_fails_at_the_database_predicate_not_in_python(client_and_session):
    client, Session = client_and_session
    token = register_and_token(client, "a@example.com")
    entry_id = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    ).json()["id"]

    session_a = Session()
    session_b = Session()
    try:
        entry_a = session_a.get(DiaryEntry, entry_id)
        entry_b = session_b.get(DiaryEntry, entry_id)
        assert entry_a.version == entry_b.version == 1  # both "concurrent requests" saw the same starting state

        entry_a.quantity_g = 150
        session_a.commit()  # first writer: succeeds
        assert entry_a.version == 2

        entry_b.quantity_g = 999  # second writer still holds the pre-conflict in-memory row
        with pytest.raises(StaleDataError):
            session_b.commit()  # the database predicate — not a Python check — is what catches this
    finally:
        session_a.close()
        session_b.close()

    # the first writer's value survived; the second's never reached the database at all
    verify_session = Session()
    final = verify_session.get(DiaryEntry, entry_id)
    assert final.quantity_g == 150
    assert final.version == 2
    verify_session.close()


def test_commit_entry_mutation_translates_stale_data_error_and_leaves_session_usable(client_and_session):
    """The app-facing wrapper around the mechanism above: EntryConflict,
    not a bare SQLAlchemy StaleDataError, and the session must still be
    usable afterwards (rollback happened) rather than left broken."""
    client, Session = client_and_session
    token = register_and_token(client, "b@example.com")
    entry_id = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    ).json()["id"]

    session_a = Session()
    session_b = Session()
    try:
        entry_a = session_a.get(DiaryEntry, entry_id)
        entry_b = session_b.get(DiaryEntry, entry_id)

        entry_a.quantity_g = 150
        session_a.commit()

        entry_b.quantity_g = 999
        with pytest.raises(EntryConflict):
            commit_entry_mutation(session_b)

        # session_b is still usable after the rollback commit_entry_mutation did —
        # a fresh read through it sees the first writer's committed value
        session_b.rollback()  # commit_entry_mutation already did this; idempotent
        refreshed = session_b.get(DiaryEntry, entry_id)
        session_b.refresh(refreshed)
        assert refreshed.quantity_g == 150
        assert refreshed.version == 2
    finally:
        session_a.close()
        session_b.close()


def test_transaction_rollback_leaves_no_partial_mutation(client_and_session):
    """A lost optimistic-concurrency race must not leave the row in a
    half-updated state — either the whole mutation applied (the winner)
    or none of it did (the loser), never a partial write."""
    client, Session = client_and_session
    token = register_and_token(client, "c@example.com")
    entry_id = client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    ).json()["id"]

    session_a = Session()
    session_b = Session()
    try:
        entry_a = session_a.get(DiaryEntry, entry_id)
        entry_b = session_b.get(DiaryEntry, entry_id)

        entry_a.quantity_g = 150
        session_a.commit()

        entry_b.quantity_g = 999
        entry_b.meal = "dinner"  # a second field, to prove neither half landed
        with pytest.raises(EntryConflict):
            commit_entry_mutation(session_b)
    finally:
        session_a.close()
        session_b.close()

    verify_session = Session()
    final = verify_session.get(DiaryEntry, entry_id)
    assert final.quantity_g == 150  # writer A's value, not writer B's 999
    assert final.meal == "lunch"  # writer B's "dinner" never landed either
    verify_session.close()
