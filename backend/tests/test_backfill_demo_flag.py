from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import backfill_demo_flag
from app.backfill_demo_flag import apply_backfill, find_candidates, main as backfill_main
from app.database import Base
from app.demo_data import DEMO_EMAIL_DOMAIN
from app.models import User


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seeded_demo_user(email=f"demo-abc123@{DEMO_EMAIL_DOMAIN}") -> User:
    """Exactly demo_data.create_demo_account's profile-field pattern —
    the strong secondary signal, independent of the email domain."""
    return User(
        email=email, password_hash="x", is_demo=False,
        sex="female", activity_level="moderate", weight_kg=65.0, height_cm=168.0,
    )


def test_confirmed_match_requires_email_and_full_profile_match(db):
    db.add(_seeded_demo_user())
    db.commit()

    confirmed, ambiguous = find_candidates(db)
    assert len(confirmed) == 1
    assert ambiguous == []


def test_email_domain_alone_is_not_enough(db):
    """A real registration never sets profile fields at signup — a row
    matching only the email pattern but with normal/null profile fields
    must NOT be auto-marked, since register() never validates or
    restricts the email domain (see this module's docstring)."""
    db.add(User(email=f"real@{DEMO_EMAIL_DOMAIN}", password_hash="x", is_demo=False))
    db.commit()

    confirmed, ambiguous = find_candidates(db)
    assert confirmed == []
    assert len(ambiguous) == 1


def test_partial_profile_match_is_ambiguous_not_confirmed(db):
    user = _seeded_demo_user()
    user.weight_kg = 71.5  # customized after the fact — no longer an exact seed match
    db.add(user)
    db.commit()

    confirmed, ambiguous = find_candidates(db)
    assert confirmed == []
    assert len(ambiguous) == 1


def test_normal_user_email_never_matches(db):
    db.add(User(email="real@example.com", password_hash="x", is_demo=False))
    db.commit()

    confirmed, ambiguous = find_candidates(db)
    assert confirmed == []
    assert ambiguous == []


def test_already_flagged_demo_accounts_are_excluded_from_candidates(db):
    """Idempotency: a row already marked is_demo=true (e.g. created
    normally via the demo endpoint, or already backfilled) shouldn't be
    re-reported every time this runs."""
    user = _seeded_demo_user()
    user.is_demo = True
    db.add(user)
    db.commit()

    confirmed, ambiguous = find_candidates(db)
    assert confirmed == []
    assert ambiguous == []


def test_dry_run_does_not_modify_anything(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(backfill_demo_flag, "SessionLocal", Session)

    db.add(_seeded_demo_user(email="demo-x@" + DEMO_EMAIL_DOMAIN))
    db.commit()

    backfill_main([])
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "demo-x@" + DEMO_EMAIL_DOMAIN in out
    assert db.query(User).filter(User.is_demo.is_(True)).count() == 0


def test_apply_marks_only_confirmed_matches_and_sets_expiry(db):
    confirmed_user = _seeded_demo_user(email="demo-confirmed@" + DEMO_EMAIL_DOMAIN)
    ambiguous_user = User(email="demo-ambiguous@" + DEMO_EMAIL_DOMAIN, password_hash="x", is_demo=False)
    db.add_all([confirmed_user, ambiguous_user])
    db.commit()

    confirmed, ambiguous = find_candidates(db)
    n = apply_backfill(db, confirmed)
    assert n == 1

    db.refresh(confirmed_user)
    db.refresh(ambiguous_user)
    assert confirmed_user.is_demo is True
    assert confirmed_user.expires_at is not None
    assert ambiguous_user.is_demo is False


def test_cli_apply_actually_marks_rows(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(backfill_demo_flag, "SessionLocal", Session)

    user = _seeded_demo_user(email="demo-apply@" + DEMO_EMAIL_DOMAIN)
    db.add(user)
    db.commit()
    user_id = user.id

    backfill_main(["--apply"])
    out = capsys.readouterr().out
    assert "Marked 1 account(s)" in out

    verify_session = Session()
    marked = verify_session.query(User).filter(User.id == user_id).one()
    assert marked.is_demo is True
    assert marked.expires_at is not None
    verify_session.close()
