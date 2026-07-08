"""
JWT authentication core (Phase 2 Section 6 -- Holy Grail §10.2).

Issues short-lived access tokens (15 min) + longer-lived refresh tokens (7 days)
with rotation: every refresh call invalidates the old token and issues a new one.
A leaked refresh token can only be used once; the second use invalidates the session.

Token design:
  access_token  -- signed JWT, verified in-memory (no DB lookup on every request)
  refresh_token -- opaque random secret, SHA256-hashed before storage (same pattern
                   as API keys -- raw value shown once, hash stored in DB)
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from apps.api.core.config import get_settings
from apps.api.models import RefreshToken, User

_settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7


# ---------- Password hashing ----------

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


# ---------- Access token (JWT) ----------

def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, _settings.jwt_secret_key, algorithm=_settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises JWTError on invalid/expired token."""
    payload = jwt.decode(
        token,
        _settings.jwt_secret_key,
        algorithms=[_settings.jwt_algorithm],
    )
    if payload.get("type") != "access":
        raise JWTError("not an access token")
    return payload


# ---------- Refresh token (opaque + DB-persisted) ----------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_refresh_token(
    db: Session, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str
) -> str:
    """Generates a raw refresh token, stores its hash, returns the raw value (shown once)."""
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw)
    expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    record = RefreshToken(
        user_id=user_id,
        tenant_id=tenant_id,
        token_hash=token_hash,
        role=role,
        expires_at=expires,
    )
    db.add(record)
    db.commit()
    return raw


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[str, str]:
    """Validates the raw refresh token, revokes it, issues a new pair.

    Returns (new_access_token, new_refresh_token).
    Raises ValueError on invalid, expired, or already-revoked token.
    """
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash
    ).first()

    if record is None:
        raise ValueError("refresh token not found")
    if record.revoked_at is not None:
        # Token reuse detected -- this should never happen for a legitimate client.
        # A legitimate client rotates exactly once. If reuse is detected, revoke
        # all tokens for this user (session hijacking response).
        _revoke_all_for_user(db, record.user_id)
        raise ValueError("refresh token already used -- all sessions revoked")
    if datetime.now(timezone.utc) > record.expires_at.replace(tzinfo=timezone.utc):
        raise ValueError("refresh token expired")

    # Revoke the old token
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()

    # Issue fresh pair
    access = create_access_token(record.user_id, record.tenant_id, record.role)
    refresh = create_refresh_token(db, record.user_id, record.tenant_id, record.role)
    return access, refresh


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Revokes a single refresh token (logout)."""
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash
    ).first()
    if record and record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        db.commit()


def _revoke_all_for_user(db: Session, user_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()


# ---------- User lookup ----------

def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user