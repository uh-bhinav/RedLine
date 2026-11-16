"""
Shared tenant resolution for operator bootstrap scripts (create_api_key.py,
register_agent_version.py, push_suite.py).

These scripts run outside any request/auth context -- there is no AuthContext to
derive a tenant from the way every API router does (Phase 3 Section 1). Before
this, all three independently did `db.query(Tenant).first()`, which is correct
only while exactly one tenant exists and silently picks an arbitrary tenant
(whichever was inserted first) the moment a second one is created. That is not a
request-path leak (nothing here is reachable by an untrusted caller), but it is a
real operator footgun waiting for the first multi-tenant setup.

resolve_tenant() keeps today's single-tenant convenience (no --tenant needed while
there is only one) and demands disambiguation the moment there is more than one,
rather than silently guessing.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from apps.api.models import Tenant


def resolve_tenant(db: Session, tenant_arg: str | None) -> Tenant:
    """Resolves the tenant a bootstrap script should operate on.

    tenant_arg may be a tenant UUID or an exact tenant name. If omitted, falls
    back to "the only tenant" -- and raises a clear, actionable error the moment
    that assumption stops holding (zero tenants, or more than one).
    """
    if tenant_arg:
        tenant: Tenant | None = None
        try:
            tenant = db.get(Tenant, uuid.UUID(tenant_arg))
        except ValueError:
            pass
        if tenant is None:
            tenant = db.query(Tenant).filter(Tenant.name == tenant_arg).first()
        if tenant is None:
            raise RuntimeError(
                f"tenant '{tenant_arg}' not found (tried it as a UUID and as a tenant name)"
            )
        return tenant

    tenants = db.query(Tenant).all()
    if not tenants:
        raise RuntimeError("no tenant found -- run `python -m apps.api.scripts.seed` first")
    if len(tenants) > 1:
        listing = ", ".join(f"'{t.name}' ({t.id})" for t in tenants)
        raise RuntimeError(
            f"multiple tenants exist ({listing}) -- pass --tenant <name-or-id> to disambiguate"
        )
    return tenants[0]
