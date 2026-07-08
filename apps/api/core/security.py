"""
Auth + authorization dependency (Phase 2 Section 6).

require_api_key() now accepts EITHER:
  - Bearer <api_key>   -- long-lived, for CLI and CI pipelines (unchanged from Phase 1)
  - Bearer <jwt>       -- short-lived access token, for the dashboard

Both resolve to (tenant_id, user_id | None, role) so downstream code never needs
to know which credential type was used. RBAC enforcement is in require_role().
"""
from __future__ import annotations

import hashlib
import uuid

from fastapi import Depends, Header, HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from apps.api.core.auth import decode_access_token
from apps.api.core.db import get_db
from apps.api.models import ApiKey, Tenant, User


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthContext:
    """Resolved identity from either an API key or a JWT."""

    def __init__(
        self,
        tenant_id: uuid.UUID,
        role: str,
        user_id: uuid.UUID | None = None,
        api_key_id: uuid.UUID | None = None,
    ):
        self.tenant_id = tenant_id
        self.role = role
        self.user_id = user_id
        self.api_key_id = api_key_id


def require_api_key(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """Accepts both API keys and JWT access tokens. Raises 401 on any failure."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing or malformed Authorization header",
        )

    raw = authorization.removeprefix("Bearer ").strip()

    # Try JWT first (JWTs contain dots; API keys start with 'rl_live_')
    if not raw.startswith("rl_live_"):
        try:
            payload = decode_access_token(raw)
            tenant_id = uuid.UUID(payload["tenant_id"])
            user_id = uuid.UUID(payload["sub"])
            role = payload["role"]
            # Verify the tenant and user still exist (token replay after deletion)
            tenant = db.get(Tenant, tenant_id)
            user = db.get(User, user_id)
            if tenant is None or user is None:
                raise HTTPException(status_code=401, detail="user or tenant not found")
            return AuthContext(tenant_id=tenant_id, role=role, user_id=user_id)
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"invalid token: {e}")

    # Fall through to API key verification
    key_hash = _hash_key(raw)
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    if api_key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="API key has been revoked")

    return AuthContext(
        tenant_id=api_key.tenant_id,
        role=api_key.role,
        api_key_id=api_key.id,
    )


def require_role(*allowed_roles: str):
    """Dependency factory for RBAC. Usage: Depends(require_role('admin', 'developer'))"""
    def _check(ctx: AuthContext = Depends(require_api_key)) -> AuthContext:
        if ctx.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"role '{ctx.role}' is not allowed; required: {list(allowed_roles)}",
            )
        return ctx
    return _check