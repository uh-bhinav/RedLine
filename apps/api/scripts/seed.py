"""
Seeds one tenant, one admin user, and one API key for local development.

Run from the repo root:
    python -m apps.api.scripts.seed
"""
import hashlib
import secrets

from passlib.context import CryptContext

from apps.api.core.db import SessionLocal
from apps.api.models import ApiKey, Tenant, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_TENANT_NAME = "Default Tenant"
DEFAULT_ADMIN_EMAIL = "admin@redline.local"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def main() -> None:
    db = SessionLocal()
    try:
        existing = db.query(Tenant).filter(Tenant.name == DEFAULT_TENANT_NAME).first()
        if existing is not None:
            print(f"Seed data already exists (tenant_id={existing.id}). Skipping.")
            return

        tenant = Tenant(name=DEFAULT_TENANT_NAME)
        db.add(tenant)
        db.flush()  # need tenant.id before creating dependents

        admin = User(
            tenant_id=tenant.id,
            email=DEFAULT_ADMIN_EMAIL,
            hashed_password=pwd_context.hash(DEFAULT_ADMIN_PASSWORD),
            role="admin",
        )
        db.add(admin)

        raw_key = f"rl_live_{secrets.token_urlsafe(32)}"
        api_key = ApiKey(
            tenant_id=tenant.id,
            name="seed-default-key",
            key_hash=hash_api_key(raw_key),
            role="admin",
        )
        db.add(api_key)

        db.commit()

        print("Seed complete.")
        print(f"  tenant_id : {tenant.id}")
        print(f"  admin     : {DEFAULT_ADMIN_EMAIL} / {DEFAULT_ADMIN_PASSWORD}")
        print(f"  api_key   : {raw_key}")
        print("  (raw API key shown ONCE — only its sha256 hash is stored. Save it now.)")
    finally:
        db.close()


if __name__ == "__main__":
    main()