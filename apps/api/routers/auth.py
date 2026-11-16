"""
Auth endpoints (Phase 2 Section 6 + Phase 1.1 registration).

POST /auth/register -- create new user + tenant -> auto-login with tokens
POST /auth/login    -- email + password -> access_token (15min) + refresh_token (7d)
POST /auth/refresh  -- refresh_token -> rotated pair (old token invalidated)
POST /auth/logout   -- revokes refresh_token

The access token is a signed JWT verified in-memory on every request -- no DB hit.
The refresh token is an opaque secret whose SHA256 hash is stored in `refresh_tokens`.
"""
import hashlib
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from apps.api.core.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    hash_password,
    revoke_refresh_token,
    rotate_refresh_token,
)
from apps.api.core.db import get_db
from apps.api.core.security import TenantContext, get_tenant_context, require_tenant_role
from apps.api.models import ApiKey, Tenant, User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("password must contain at least one digit")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("name must be at least 2 characters")
        return v.strip()


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes in seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    user_id: uuid.UUID | None
    tenant_id: uuid.UUID
    tenant_name: str
    email: str | None
    role: str


API_KEY_PREFIX = "rl_live_"


class ApiKeyCreate(BaseModel):
    label: str
    role: Literal["admin", "developer", "viewer"] = "developer"

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label must not be empty")
        return v


class ApiKeyItem(BaseModel):
    """Masked view -- the raw key is never retrievable after creation."""

    id: uuid.UUID
    label: str
    role: str
    masked_key: str
    key_prefix: str | None
    last_four: str | None
    created_at: datetime
    revoked: bool
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyItem):
    """Returned once, on creation only."""

    key: str


def _api_key_item(k: ApiKey) -> dict:
    prefix = k.key_prefix or API_KEY_PREFIX
    masked = f"{prefix}{'•' * 8}{k.last_four}" if k.last_four else f"{prefix}{'•' * 12}"
    return dict(
        id=k.id,
        label=k.name,
        role=k.role,
        masked_key=masked,
        key_prefix=k.key_prefix,
        last_four=k.last_four,
        created_at=k.created_at,
        revoked=k.revoked_at is not None,
        revoked_at=k.revoked_at,
    )


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    ctx: TenantContext = Depends(require_tenant_role("admin")),
    db: Session = Depends(get_db),
) -> ApiKeyCreated:
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    record = ApiKey(
        tenant_id=ctx.tenant_id,
        name=payload.label,
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        role=payload.role,
        key_prefix=API_KEY_PREFIX,
        last_four=raw[-4:],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ApiKeyCreated(**_api_key_item(record), key=raw)


@router.get("/api-keys", response_model=list[ApiKeyItem])
def list_api_keys(
    ctx: TenantContext = Depends(require_tenant_role("admin")),
    db: Session = Depends(get_db),
) -> list[ApiKeyItem]:
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.tenant_id == ctx.tenant_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [ApiKeyItem(**_api_key_item(k)) for k in keys]


@router.delete("/api-keys/{key_id}", response_model=ApiKeyItem)
def revoke_api_key(
    key_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_role("admin")),
    db: Session = Depends(get_db),
) -> ApiKeyItem:
    """Revokes (idempotent). 404 for another tenant's key, same as every other lookup."""
    key = db.get(ApiKey, key_id)
    if key is None or key.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="api key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(key)
    return ApiKeyItem(**_api_key_item(key))


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Register a new user and auto-create their workspace (tenant).

    Returns access + refresh tokens (auto-login after registration).
    Raises 400 if email already exists.
    """
    # Check if email already registered
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=400,
            detail="email already registered"
        )

    # Create tenant (workspace) for the new user
    tenant = Tenant(name=f"{payload.name}'s Workspace")
    db.add(tenant)
    db.flush()  # Get tenant.id without committing yet

    # Create user with admin role
    hashed_pwd = hash_password(payload.password)
    user = User(
        tenant_id=tenant.id,
        email=payload.email,
        hashed_password=hashed_pwd,
        role="admin",  # First user in workspace is always admin
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Auto-login: return tokens
    access = create_access_token(user.id, user.tenant_id, user.role)
    refresh = create_refresh_token(db, user.id, user.tenant_id, user.role)

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        # Same error for wrong email or wrong password -- no user enumeration
        raise HTTPException(status_code=401, detail="invalid credentials")

    access = create_access_token(user.id, user.tenant_id, user.role)
    refresh = create_refresh_token(db, user.id, user.tenant_id, user.role)

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        access, refresh = rotate_refresh_token(db, payload.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout", status_code=204)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> None:
    revoke_refresh_token(db, payload.refresh_token)


@router.get("/me", response_model=MeResponse)
def me(
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> MeResponse:
    # API-key callers have no user_id (AuthContext.user_id is None for that auth
    # path) -- email is simply absent for them, not an error.
    email = None
    if ctx.auth.user_id is not None:
        user = db.get(User, ctx.auth.user_id)
        email = user.email if user is not None else None

    return MeResponse(
        user_id=ctx.auth.user_id,
        tenant_id=ctx.tenant_id,
        tenant_name=ctx.tenant.name,
        email=email,
        role=ctx.role,
    )