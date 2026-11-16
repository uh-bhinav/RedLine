"""
Mints a fresh API key for a tenant.
Run from the repo root:
    python -m apps.api.scripts.create_api_key --name "cli-key"
    python -m apps.api.scripts.create_api_key --name "cli-key" --tenant acme-corp
"""
import argparse
import hashlib
import secrets

from apps.api.core.db import SessionLocal
from apps.api.models import ApiKey
from apps.api.scripts._tenant import resolve_tenant


def create_api_key(name: str, tenant_arg: str | None = None) -> None:
    db = SessionLocal()
    try:
        tenant = resolve_tenant(db, tenant_arg)

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

        print(f"API key created for tenant '{tenant.name}' (name='{name}'):")
        print(f"  {raw_key}")
        print("  (shown ONCE -- only the sha256 hash is stored)")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="cli-key")
    parser.add_argument(
        "--tenant", default=None,
        help="Tenant name or UUID. Required once more than one tenant exists.",
    )
    args = parser.parse_args()
    create_api_key(args.name, args.tenant)