import time

import jwt
import pytest

from app.auth import (
    DEV_JWT_SECRET,
    InvalidToken,
    JWT_ALGORITHM,
    JWT_SECRET,
    _resolve_jwt_secret,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


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
    monkeypatch.setenv("JWT_SECRET", "a-real-secret")
    assert _resolve_jwt_secret() == "a-real-secret"


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
    monkeypatch.setenv("JWT_SECRET", "a-real-secret")
    monkeypatch.setenv("APP_ENV", "production")
    assert _resolve_jwt_secret() == "a-real-secret"
