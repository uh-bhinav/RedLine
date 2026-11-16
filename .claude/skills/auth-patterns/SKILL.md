---
name: auth-patterns
description: RedLine authentication patterns — require_api_key dependency, AuthContext dataclass, RBAC with require_role(), the full JWT login→refresh→rotate→logout flow, and refresh token reuse detection.
---

# RedLine Auth Patterns

Use this skill when:
- Adding auth to a new endpoint
- Debugging 401 or 403 errors
- Understanding how JWT and API key auth coexist
- Implementing the refresh token rotation flow
- Adding a new RBAC role check

---

## The `AuthContext` Dataclass

Every authenticated endpoint receives an `AuthContext` object:

```python
# apps/api/core/security.py
from dataclasses import dataclass
from typing import Optional
import uuid

@dataclass
class AuthContext:
    tenant_id: uuid.UUID
    role: str                     # "admin" | "developer" | "viewer"
    user_id: Optional[uuid.UUID]  # Set for JWT auth, None for API key auth
    api_key_id: Optional[uuid.UUID]  # Set for API key auth, None for JWT auth
```

**Use `auth.tenant_id`** to scope all DB queries to the caller's tenant.

**Use `auth.role`** for fine-grained access checks (prefer `require_role()` over manual role checking).

---

## `require_api_key` — The Dual-Auth Dependency

`require_api_key` accepts **both** Bearer JWT tokens and raw API keys in one dependency:

```python
# apps/api/core/security.py
from fastapi import Depends, HTTPException, Header
from typing import Optional

def require_api_key(
    authorization: Optional[str] = Header(None)
) -> AuthContext:
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    
    # JWT path: "Bearer eyJ..."
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        return _verify_jwt(token)
    
    # API key path: "Bearer rl_live_..."
    if authorization.startswith("Bearer rl_live_"):
        raw_key = authorization[7:]
        return _verify_api_key(raw_key)
    
    raise HTTPException(401, "Invalid Authorization format")
```

**Using it on any endpoint:**

```python
@router.get("/eval-runs/{run_id}")
def get_eval_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_api_key),  # ← this
):
    eval_run = db.execute(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.tenant_id == auth.tenant_id  # ← always scope to tenant
        )
    ).scalar_one_or_none()
    ...
```

---

## `require_role` — RBAC Gating

Use `require_role("admin")` or `require_role("developer")` when an endpoint needs a minimum role.

```python
from apps.api.core.security import require_role

# Only admin can revoke API keys
@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),
):
    ...

# Developer or admin can create eval runs
@router.post("/eval-runs")
def create_eval_run(
    body: EvalRunCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_role("developer")),
):
    ...
```

**Role hierarchy enforcement inside `require_role`:**

```python
ROLE_HIERARCHY = {"admin": 3, "developer": 2, "viewer": 1}

def require_role(minimum_role: str):
    def dependency(auth: AuthContext = Depends(require_api_key)) -> AuthContext:
        if ROLE_HIERARCHY[auth.role] < ROLE_HIERARCHY[minimum_role]:
            raise HTTPException(403, f"Role '{minimum_role}' required, got '{auth.role}'")
        return auth
    return dependency
```

---

## Full Auth Flow: Login → Access → Refresh → Rotate → Logout

### Step 1: Login (`POST /auth/login`)

```
Client → POST /auth/login {email, password}
Server:
  1. Load User by email
  2. pwd_context.verify(password, user.hashed_password)
  3. Create access_token (15 min, type="access")
  4. Create refresh_token (7 days, type="refresh")
  5. Store SHA256(refresh_token) in refresh_tokens table
  6. Return {access_token, refresh_token}
Client stores both tokens.
```

### Step 2: Authenticated Requests

```
Client → GET /eval-runs/...
  Authorization: Bearer <access_token>
Server:
  1. require_api_key() extracts Bearer token
  2. jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
  3. Verifies "type" == "access"
  4. Returns AuthContext(tenant_id, role, user_id, api_key_id=None)
```

### Step 3: Refresh (`POST /auth/refresh`)

```
Client → POST /auth/refresh {refresh_token: "<raw_token>"}
Server:
  1. Compute token_hash = SHA256(raw_refresh_token)
  2. SELECT * FROM refresh_tokens WHERE token_hash = '<hash>'
  
  IF NOT FOUND:
    → 401 "Invalid refresh token"
  
  IF FOUND but revoked_at IS NOT NULL:
    → REUSE DETECTED
    → UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = '<user_id>'
       (revokes ALL sessions for this user — see reuse detection below)
    → 401 "Token already used — all sessions revoked"
  
  IF FOUND and active:
    → Revoke old token: UPDATE ... SET revoked_at = now() WHERE id = '<old_id>'
    → Issue new access_token + new refresh_token
    → Store SHA256(new_refresh_token) in refresh_tokens
    → Return {access_token, refresh_token}
```

### Step 4: Logout (`POST /auth/logout`)

```
Client → POST /auth/logout
  Authorization: Bearer <access_token>
Server:
  1. Identify user from JWT
  2. Revoke ALL refresh tokens: UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = ...
  3. Return 204 No Content
```

---

## Refresh Token Reuse Detection

Reuse detection is a **security feature, not a bug**.

**Scenario:** If a refresh token is stolen and the attacker replays it after the legitimate user has already rotated it:

1. The legitimate user has already used the token — it's revoked
2. The attacker's replay hits a revoked token
3. Server recognizes this as a potential session hijacking event
4. Server revokes **all** refresh tokens for that user
5. The legitimate user is logged out on their next request
6. The user re-authenticates, getting fresh tokens

**Why revoke ALL sessions?** Because the server cannot know which sessions the attacker may have obtained tokens for. Revoking all sessions forces a clean re-auth from all devices.

**This will sometimes frustrate legitimate users** (e.g., two browser tabs both try to refresh simultaneously). This is accepted behavior — the security benefit outweighs the UX cost. Document it in user-facing error messages.

---

## Debugging Auth Errors

**401 "Missing Authorization header"**
→ Client is not sending `Authorization: Bearer ...` header

**401 "Invalid or expired token"**
→ JWT signature mismatch (wrong `JWT_SECRET_KEY`) or token expired

**401 "Invalid token type"**
→ Client sent a refresh token where an access token is expected. Check `"type"` claim.

**403 "Admin role required"**
→ Caller has `developer` or `viewer` role. Use the admin API key for this operation.

**401 "Token already used — all sessions revoked"**
→ Refresh token was replayed. User must log in again with email + password.

**Check which API key is being used:**

```bash
psql -h localhost -p 5433 -U redline -d redline -c "
  SELECT name, role, created_at, revoked_at FROM api_keys;
"
```
