"""
Mints a fresh API key for the existing tenant.
Run from the repo root:
    python -m apps.api.scripts.create_api_key --name "cli-key"
"""
import argparse
import hashlib
import secrets

from apps.api.core.db import SessionLocal
from apps.api.models import ApiKey, Tenant


def create_api_key(name: str) -> None:
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if tenant is None:
            raise RuntimeError("no tenant found")

        raw_key = f"rl_live_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = ApiKey(
            tenant_id=tenant.id,
            name=name,
            key_hash=key_hash,
            role="admin",
        )
        db.add(api_key)
        db.commit()

        print(f"API key created (name='{name}'):")
        print(f"  {raw_key}")
        print("  (shown ONCE -- only the sha256 hash is stored)")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="cli-key")
    args = parser.parse_args()
    create_api_key(args.name)