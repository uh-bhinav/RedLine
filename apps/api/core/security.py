"""
Authentication for RedLine.

Two kinds of caller share one tenant-scoped entry point (`get_tenant_context`):
  * the dashboard  -> `Authorization: Bearer <JWT>` issued by POST /auth/login|register
  * CLI / CI       -> `Authorization: Bearer rl_...` long-lived API key (sha256-hashed at rest)
`require_api_key` is kept for the original CLI-only routes.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from apps.api.core.config import get_settings
from apps.api.core.db import get_db
from apps.api.models import ApiKey, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_RANK = {"viewer": 0, "developer": 1, "admin": 2}


@dataclass
class TenantContext:
    tenant_id: uuid.UUID
    role: str
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None


MIN_JWT_SECRET_LENGTH = 32


def validate_jwt_secret(secret: str) -> None:
    """Raise at startup if the JWT signing key is too short to be safe."""
    if len(secret or "") < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_LENGTH} characters "
            f"(got {len(secret or '')}); generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


_hash_key = hash_api_key  # backwards-compatible alias


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(user: User) -> str:
    settings = get_settings()
    validate_jwt_secret(settings.jwt_secret_key)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "tid": str(user.tenant_id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
    return authorization.removeprefix("Bearer ").strip()


def _lookup_api_key(raw_key: str, db: Session) -> ApiKey:
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(raw_key)).first()
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    if api_key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="API key has been revoked")
    return api_key


def require_api_key(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """FastAPI dependency. Expects `Authorization: Bearer <api_key>`."""
    return _lookup_api_key(_bearer(authorization), db)


def get_tenant_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> TenantContext:
    token = _bearer(authorization)
    if token.startswith("rl_"):
        key = _lookup_api_key(token, db)
        return TenantContext(tenant_id=key.tenant_id, role=key.role, api_key_id=key.id)

    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="session expired -- please sign in again")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="user no longer exists")
    return TenantContext(tenant_id=user.tenant_id, role=user.role, user_id=user.id)


def require_tenant_role(min_role: str = "viewer"):
    """Dependency factory: caller must hold at least `min_role` (viewer < developer < admin)."""

    def _dep(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if ROLE_RANK.get(ctx.role, -1) < ROLE_RANK[min_role]:
            raise HTTPException(status_code=403, detail=f"requires role '{min_role}' or higher")
        return ctx

    return _dep
