"""
Integration test for apps.api.scripts._tenant.resolve_tenant() -- the follow-up
from Phase 3.1: create_api_key.py, register_agent_version.py, and push_suite.py
all used to do db.query(Tenant).first(), which silently picks whichever tenant
was inserted first the moment a second tenant exists.

Needs real Postgres because it exercises real multi-row Tenant queries (the whole
point is proving disambiguation actually kicks in with more than one row present).

Run from the repo root:
    pytest apps/api/tests/integration/test_tenant_resolution.py -v -m integration
"""
from __future__ import annotations

import uuid

import pytest

from apps.api.core.db import SessionLocal
from apps.api.models import Tenant
from apps.api.scripts._tenant import resolve_tenant

pytestmark = pytest.mark.integration


@pytest.fixture
def two_tenants():
    db = SessionLocal()
    try:
        a = Tenant(name=f"resolve-tenant-a-{uuid.uuid4().hex[:8]}")
        b = Tenant(name=f"resolve-tenant-b-{uuid.uuid4().hex[:8]}")
        db.add_all([a, b])
        db.commit()
        ids = {"a_id": a.id, "a_name": a.name, "b_id": b.id, "b_name": b.name}
    except Exception:
        db.rollback()
        db.close()
        raise

    yield ids

    try:
        db.query(Tenant).filter(Tenant.id.in_([ids["a_id"], ids["b_id"]])).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def test_resolves_by_exact_name(two_tenants):
    db = SessionLocal()
    try:
        tenant = resolve_tenant(db, two_tenants["a_name"])
        assert tenant.id == two_tenants["a_id"]
    finally:
        db.close()


def test_resolves_by_uuid_string(two_tenants):
    db = SessionLocal()
    try:
        tenant = resolve_tenant(db, str(two_tenants["b_id"]))
        assert tenant.id == two_tenants["b_id"]
    finally:
        db.close()


def test_unknown_tenant_name_raises_clearly(two_tenants):
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="not found"):
            resolve_tenant(db, "definitely-not-a-real-tenant-name")
    finally:
        db.close()


def test_ambiguous_without_tenant_arg_raises_and_lists_candidates(two_tenants):
    """The actual bug this fixes: with more than one tenant and no --tenant, the
    old db.query(Tenant).first() silently picked one. Now it must refuse."""
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="multiple tenants exist") as exc_info:
            resolve_tenant(db, None)
        message = str(exc_info.value)
        assert two_tenants["a_name"] in message
        assert two_tenants["b_name"] in message
        assert "--tenant" in message
    finally:
        db.close()


def test_single_tenant_still_works_with_no_tenant_arg():
    """The preserved convenience: while exactly one tenant exists, --tenant stays
    optional -- this must not regress the common single-tenant dev setup.

    Skipped rather than faked when this dev DB already has more than one tenant
    (e.g. the real seeded 'Default Tenant' plus anything else): a shared
    Postgres instance genuinely cannot be forced into "exactly one tenant"
    without deleting real data, same reasoning as the zero-tenant test below.
    """
    db = SessionLocal()
    try:
        existing = db.query(Tenant).count()
        if existing != 0:
            pytest.skip(
                f"{existing} tenant(s) already exist in this dev DB -- cannot "
                f"exercise the exactly-one-tenant path without deleting real data"
            )

        name = f"resolve-tenant-solo-{uuid.uuid4().hex[:8]}"
        tenant = Tenant(name=name)
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id

        resolved = resolve_tenant(db, None)
        assert resolved.id == tenant_id
    finally:
        db.query(Tenant).filter(Tenant.name.like("resolve-tenant-solo-%")).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()


def test_zero_tenants_raises_a_seed_hint():
    db = SessionLocal()
    try:
        existing = db.query(Tenant).count()
        if existing > 0:
            pytest.skip(
                f"{existing} tenant(s) already exist in this dev DB -- cannot "
                f"exercise the zero-tenant path without deleting real data"
            )
        with pytest.raises(RuntimeError, match="run .*seed"):
            resolve_tenant(db, None)
    finally:
        db.close()
