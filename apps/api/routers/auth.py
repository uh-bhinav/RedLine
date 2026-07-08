"""
Auth endpoints (Phase 2 Section 6).

POST /auth/login   -- email + password -> access_token (15min) + refresh_token (7d)
POST /auth/refresh -- refresh_token -> rotated pair (old token invalidated)
POST /auth/logout  -- revokes refresh_token

The access token is a signed JWT verified in-memory on every request -- no DB hit.
The refresh token is an opaque secret whose SHA256 hash is stored in `refresh_tokens`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.core.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from apps.api.core.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


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