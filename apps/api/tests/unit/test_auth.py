"""
Unit tests for JWT auth and RBAC (Phase 2 Section 6).

Pure logic -- no DB, no network.
Run from the repo root:
    pytest apps/api/tests/unit/test_auth.py -v
"""
import time
import uuid

import pytest
from jose import jwt as jose_jwt

from apps.api.core.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from apps.api.core.config import get_settings

pytestmark = pytest.mark.unit

_settings = get_settings()


# ---------- Password hashing ----------

def test_password_hash_and_verify():
    h = hash_password("CorrectPassword1!")
    assert verify_password("CorrectPassword1!", h) is True


def test_wrong_password_rejected():
    h = hash_password("CorrectPassword1!")
    assert verify_password("WrongPassword!", h) is False


def test_different_plaintexts_produce_different_hashes():
    h1 = hash_password("PasswordA1!")
    h2 = hash_password("PasswordB2@")
    assert h1 != h2


# ---------- Access token round-trip ----------

def test_access_token_round_trip():
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id, tenant_id, "admin")
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_expired_access_token_rejected():
    user_id = uuid.uuid4()
    # Craft a token with exp in the past
    bad = jose_jwt.encode(
        {"sub": str(user_id), "type": "access", "role": "admin",
         "tenant_id": str(uuid.uuid4()), "exp": time.time() - 1},
        _settings.jwt_secret_key,
        algorithm=_settings.jwt_algorithm,
    )
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token(bad)


def test_tampered_token_rejected():
    token = create_access_token(uuid.uuid4(), uuid.uuid4(), "admin")
    # Flip one character in the signature
    tampered = token[:-3] + "XXX"
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token(tampered)


def test_refresh_token_type_rejected_as_access():
    """A token crafted with type=refresh must not pass as an access token."""
    bad = jose_jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "role": "admin",
         "tenant_id": str(uuid.uuid4()), "exp": time.time() + 3600},
        _settings.jwt_secret_key,
        algorithm=_settings.jwt_algorithm,
    )
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token(bad)


def test_different_users_get_different_tokens():
    t1 = create_access_token(uuid.uuid4(), uuid.uuid4(), "admin")
    t2 = create_access_token(uuid.uuid4(), uuid.uuid4(), "admin")
    assert t1 != t2


# ---------- RBAC ----------

def test_require_role_allows_correct_role():
    from apps.api.core.security import AuthContext, require_role
    ctx = AuthContext(tenant_id=uuid.uuid4(), role="admin")
    checker = require_role("admin", "developer")
    # Call the inner function directly -- FastAPI Depends is not needed for unit tests
    result = checker.__wrapped__(ctx) if hasattr(checker, "__wrapped__") else checker(ctx)
    assert result.role == "admin"


def test_require_role_blocks_wrong_role():
    from apps.api.core.security import AuthContext, require_role
    from fastapi import HTTPException
    ctx = AuthContext(tenant_id=uuid.uuid4(), role="viewer")
    checker = require_role("admin", "developer")
    with pytest.raises(HTTPException) as exc_info:
        checker(ctx)
    assert exc_info.value.status_code == 403