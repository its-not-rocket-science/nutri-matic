import time

import jwt
import pytest

from app.auth import (
    InvalidToken,
    JWT_ALGORITHM,
    JWT_SECRET,
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
