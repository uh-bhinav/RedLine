"""
API key authentication (Phase1 roadmap core/security.py).

JWT issuing/verification for the dashboard's human login is intentionally NOT
built here -- that's scoped to Section 14 (dashboard), the only thing that needs
it so far. This covers API key verification only, which is what the CLI
(machine-to-machine, Section 13) actually needs right now.
"""
from __future__ import annotations

import hashlib

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.models import ApiKey


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def require_api_key(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """FastAPI dependency. Expects `Authorization: Bearer <api_key>`."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")

    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = _hash_key(raw_key)

    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    if api_key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="API key has been revoked")

    return api_key