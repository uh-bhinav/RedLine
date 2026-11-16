"""
Auth + authorization dependency (Phase 2 Section 6, Phase 3 Section 1).

require_api_key() now accepts EITHER:
  - Bearer <api_key>   -- long-lived, for CLI and CI pipelines (unchanged from Phase 1)
  - Bearer <jwt>       -- short-lived access token, for the dashboard

Both resolve to (tenant_id, user_id | None, role) so downstream code never needs
to know which credential type was used. RBAC enforcement is in require_role().

Phase 3 Section 1 adds get_tenant_context(), which resolves the *authenticated*
tenant row. Before Phase 3, two routers resolved the tenant with
`db.query(Tenant).first()` -- correct only while exactly one tenant exists, and a
silent cross-tenant read the moment a second one does. That call must never
reappear: every tenant comes from the auth context, never from the database's
insertion order and never from a client-supplied parameter.
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


class TenantContext:
    """The authenticated tenant, resolved from AuthContext -- never from a client parameter.

    Carries the AuthContext through so a router that needs the role or user_id does
    not have to declare a second dependency.
    """

    def __init__(self, tenant: Tenant, auth: AuthContext):
        self.tenant = tenant
        self.auth = auth

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id

    @property
    def role(self) -> str:
        return self.auth.role

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.auth.user_id


def get_tenant_context(
    auth: AuthContext = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> TenantContext:
    """Resolves the tenant row for the authenticated caller.

    404 rather than 500 on a missing tenant: the credential is structurally valid but
    its tenant has been deleted, which from the caller's perspective is "your tenant
    is not there," not "the server is broken."
    """
    tenant = db.get(Tenant, auth.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return TenantContext(tenant=tenant, auth=auth)


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


def require_tenant_role(*allowed_roles: str):
    """RBAC + resolved tenant in one dependency.

    Usage: Depends(require_tenant_role('admin', 'developer'))

    Exists so a mutating route does not have to declare both require_role and
    get_tenant_context and then reconcile two objects that must agree.
    """
    def _check(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if ctx.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"role '{ctx.role}' is not allowed; required: {list(allowed_roles)}",
            )
        return ctx
    return _check