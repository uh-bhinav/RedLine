"""Dashboard auth: register / login / me, plus API-key management for the Settings page."""
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.core.db import get_db
from apps.api.core.security import (
    TenantContext,
    create_access_token,
    get_tenant_context,
    hash_api_key,
    hash_password,
    require_tenant_role,
    verify_password,
)
from apps.api.models import ApiKey, Tenant, User
from apps.api.schemas.dashboard import (
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email, role=user.role, tenant_id=user.tenant_id)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")

    tenant = Tenant(name=f"{payload.name}'s workspace")
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        name=payload.name,
        email=email,
        hashed_password=hash_password(payload.password),
        role="admin",  # the first user of a new workspace owns it
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user), user=_user_out(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="incorrect email or password")
    return TokenResponse(access_token=create_access_token(user), user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(get_db)) -> UserOut:
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="API keys have no user profile")
    return _user_out(db.get(User, ctx.user_id))


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    ctx: TenantContext = Depends(require_tenant_role("admin")), db: Session = Depends(get_db)
) -> ApiKeyCreated:
    raw_key = "rl_" + secrets.token_urlsafe(32)
    label = f"Key created {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    key = ApiKey(
        tenant_id=ctx.tenant_id,
        name=label,
        label=label,
        key_hash=hash_api_key(raw_key),
        last_four=raw_key[-4:],
        role="admin",
        created_by=ctx.user_id,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return ApiKeyCreated(id=key.id, key=raw_key, label=key.label, created_at=key.created_at)


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(
    ctx: TenantContext = Depends(require_tenant_role("admin")), db: Session = Depends(get_db)
) -> list[ApiKeyOut]:
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.tenant_id == ctx.tenant_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [
        ApiKeyOut(
            id=k.id,
            label=k.label or k.name,
            masked_key=f"rl_{'•' * 12}{k.last_four or '····'}",
            created_at=k.created_at,
            revoked=k.revoked_at is not None,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_role("admin")),
    db: Session = Depends(get_db),
) -> None:
    key = db.get(ApiKey, key_id)
    if key is None or key.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
