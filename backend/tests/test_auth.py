import hashlib
import time

import jwt
import pytest

from app.auth import (
    DEV_JWT_SECRET,
    MIN_JWT_SECRET_LENGTH,
    PUBLISHED_JWT_SECRET_SHA256,
    InvalidToken,
    JWT_ALGORITHM,
    JWT_SECRET,
    _resolve_jwt_secret,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

REAL_SECRET = "a-real-secret-that-is-long-enough-0123456789"


def test_password_hash_round_trip():
    password = "correct horse battery staple"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)


def test_password_hash_rejects_wrong_password():
    hashed = hash_password("right password")
    assert not verify_password("wrong password", hashed)


def test_access_token_round_trip():
    token = create_access_token(user_id=42)
    assert decode_access_token(token) == 42


def test_decode_rejects_garbage_token():
    with pytest.raises(InvalidToken):
        decode_access_token("not-a-real-token")


def test_decode_rejects_expired_token():
    expired_payload = {"sub": "1", "exp": int(time.time()) - 10}
    token = jwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_decode_rejects_wrong_secret():
    token = jwt.encode({"sub": "1", "exp": int(time.time()) + 3600}, "a-different-secret", algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_resolve_jwt_secret_uses_env_value_when_set(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", REAL_SECRET)
    assert _resolve_jwt_secret() == REAL_SECRET


def test_resolve_jwt_secret_falls_back_to_dev_value_outside_production(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert _resolve_jwt_secret() == DEV_JWT_SECRET


def test_resolve_jwt_secret_raises_in_production_without_explicit_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        _resolve_jwt_secret()


def test_resolve_jwt_secret_ok_in_production_with_explicit_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", REAL_SECRET)
    monkeypatch.setenv("APP_ENV", "production")
    assert _resolve_jwt_secret() == REAL_SECRET


@pytest.mark.parametrize("app_env", ["production", "development"])
def test_resolve_jwt_secret_rejects_short_secret_in_any_environment(monkeypatch, app_env):
    monkeypatch.setenv("JWT_SECRET", "x" * (MIN_JWT_SECRET_LENGTH - 1))
    monkeypatch.setenv("APP_ENV", app_env)
    with pytest.raises(RuntimeError, match="shorter than"):
        _resolve_jwt_secret()


def test_resolve_jwt_secret_rejects_empty_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "")
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError, match="shorter than"):
        _resolve_jwt_secret()


def test_resolve_jwt_secret_accepts_exactly_minimum_length(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * MIN_JWT_SECRET_LENGTH)
    monkeypatch.setenv("APP_ENV", "production")
    assert _resolve_jwt_secret() == "x" * MIN_JWT_SECRET_LENGTH


def test_resolve_jwt_secret_rejects_published_secret(monkeypatch):
    candidate = "y" * 64
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    monkeypatch.setattr("app.auth.PUBLISHED_JWT_SECRET_SHA256", frozenset({digest}))
    monkeypatch.setenv("JWT_SECRET", candidate)
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(RuntimeError, match="published"):
        _resolve_jwt_secret()


def test_published_secret_list_holds_sha256_digests_only():
    assert PUBLISHED_JWT_SECRET_SHA256
    for digest in PUBLISHED_JWT_SECRET_SHA256:
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
