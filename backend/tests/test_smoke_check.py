"""Tests for app/smoke_check.py — public-launch hardening prompt 6."""

import httpx
import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User
from app.smoke_check import (
    _cleanup_demo_account,
    _decode_user_id_from_token,
    check_backend_health,
    check_backend_ready,
    check_demo_flow,
    check_frontend_page,
    check_frontend_static_asset,
)


def _fake_token(user_id: int) -> str:
    """A real JWT shape (any secret — the smoke check never verifies the
    signature, it just reads `sub`), matching what app/auth.py's
    create_access_token actually issues."""
    return jwt.encode({"sub": str(user_id)}, "irrelevant-secret", algorithm="HS256")


def client_with_handler(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_backend_health_ok():
    def handler(request):
        return httpx.Response(200, json={"status": "ok"})

    result = check_backend_health(client_with_handler(handler), "https://api.example.com")
    assert result.ok is True


def test_check_backend_health_failure():
    def handler(request):
        return httpx.Response(503, text="unavailable")

    result = check_backend_health(client_with_handler(handler), "https://api.example.com")
    assert result.ok is False
    assert "503" in result.detail


def test_check_backend_ready_failure_includes_body():
    def handler(request):
        return httpx.Response(503, text="database unavailable: OperationalError")

    result = check_backend_ready(client_with_handler(handler), "https://api.example.com")
    assert result.ok is False
    assert "database unavailable" in result.detail


def test_check_frontend_page_ok():
    def handler(request):
        return httpx.Response(200, text="<html></html>")

    result = check_frontend_page(client_with_handler(handler), "https://example.com", "/about")
    assert result.ok is True


def test_check_frontend_page_404():
    def handler(request):
        return httpx.Response(404)

    result = check_frontend_page(client_with_handler(handler), "https://example.com", "/missing")
    assert result.ok is False


def test_check_frontend_static_asset_requires_expected_content():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /")  # no Sitemap: line

    result = check_frontend_static_asset(
        client_with_handler(handler), "https://example.com", "/robots.txt", must_contain="Sitemap:"
    )
    assert result.ok is False
    assert "missing expected content" in result.detail


def test_check_frontend_static_asset_passes_with_expected_content():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nSitemap: https://example.com/sitemap.xml")

    result = check_frontend_static_asset(
        client_with_handler(handler), "https://example.com", "/robots.txt", must_contain="Sitemap:"
    )
    assert result.ok is True


def test_demo_flow_is_skipped_without_a_database_url():
    """Must not create unbounded retained demo data — no database_url
    means no guaranteed cleanup, so the check skips creating an account
    at all rather than risk leaving one behind."""

    def handler(request):
        raise AssertionError("no HTTP request should be made when the demo flow is skipped")

    result = check_demo_flow(client_with_handler(handler), "https://api.example.com", database_url=None)
    assert result.ok is True
    assert "skipped" in result.detail


def test_decode_user_id_from_token_reads_the_sub_claim_without_verifying_signature():
    assert _decode_user_id_from_token(_fake_token(42)) == 42


def test_decode_user_id_from_token_returns_none_for_garbage():
    assert _decode_user_id_from_token("not-a-jwt") is None


def test_demo_flow_creates_and_cleans_up_when_database_url_given(monkeypatch):
    calls = []

    def handler(request):
        if request.url.path == "/api/auth/demo":
            return httpx.Response(201, json={"access_token": _fake_token(42)})
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"id": 42, "email": "demo-x@demo.nutrimatic.local"})
        if request.url.path == "/api/profiles":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request to {request.url.path}")

    def fake_cleanup(database_url, user_id):
        calls.append((database_url, user_id))
        return f"deleted user_id={user_id}"

    monkeypatch.setattr("app.smoke_check._cleanup_demo_account", fake_cleanup)

    result = check_demo_flow(
        client_with_handler(handler), "https://api.example.com", database_url="sqlite:///:memory:"
    )
    assert result.ok is True
    assert calls == [("sqlite:///:memory:", 42)]
    assert "deleted user_id=42" in result.detail


def test_demo_flow_attempts_cleanup_even_when_verification_calls_fail(monkeypatch):
    """Cleanup must not depend on /me or /profiles succeeding — a
    timeout on either must not leave the created account behind."""
    calls = []

    def handler(request):
        if request.url.path == "/api/auth/demo":
            return httpx.Response(201, json={"access_token": _fake_token(42)})
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    def fake_cleanup(database_url, user_id):
        calls.append(user_id)
        return f"deleted user_id={user_id}"

    monkeypatch.setattr("app.smoke_check._cleanup_demo_account", fake_cleanup)

    result = check_demo_flow(
        client_with_handler(handler), "https://api.example.com", database_url="sqlite:///:memory:"
    )
    assert calls == [42]
    assert result.ok is False  # /me and /profiles never actually verified


def test_demo_flow_fails_overall_when_cleanup_is_refused(monkeypatch):
    """A refused/failed cleanup must fail the whole check, not just show
    up buried in the detail text of an otherwise-passing result."""

    def handler(request):
        if request.url.path == "/api/auth/demo":
            return httpx.Response(201, json={"access_token": _fake_token(42)})
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json={"id": 42, "email": "demo-x@demo.nutrimatic.local"})
        if request.url.path == "/api/profiles":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request to {request.url.path}")

    monkeypatch.setattr(
        "app.smoke_check._cleanup_demo_account",
        lambda database_url, user_id: f"REFUSED to delete user_id={user_id}: does not look like a demo account",
    )

    result = check_demo_flow(
        client_with_handler(handler), "https://api.example.com", database_url="sqlite:///:memory:"
    )
    assert result.ok is False
    assert "REFUSED" in result.detail


def test_cleanup_demo_account_actually_deletes_the_user(tmp_path):
    db_path = tmp_path / "smoke_check_test.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(email="demo-cleanup-test@demo.nutrimatic.local", password_hash="x", is_demo=True)
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    detail = _cleanup_demo_account(database_url, user_id)
    assert "deleted" in detail

    verify_db = Session()
    assert verify_db.query(User).filter(User.id == user_id).one_or_none() is None
    verify_db.close()


def test_cleanup_demo_account_refuses_to_delete_a_non_demo_account(tmp_path):
    """The exact scenario the P1 finding named: --database-url pointing
    at an environment where this user_id belongs to a real account.
    is_demo=False here is enough on its own to refuse deletion."""
    db_path = tmp_path / "smoke_check_test.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(email="real.person@example.com", password_hash="x", is_demo=False)
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    detail = _cleanup_demo_account(database_url, user_id)
    assert "REFUSED" in detail

    verify_db = Session()
    assert verify_db.query(User).filter(User.id == user_id).one_or_none() is not None
    verify_db.close()


def test_cleanup_demo_account_refuses_when_no_such_user_exists(tmp_path):
    db_path = tmp_path / "smoke_check_test.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)

    detail = _cleanup_demo_account(database_url, 999999)
    assert "FAILED" in detail
    assert "no such user" in detail
