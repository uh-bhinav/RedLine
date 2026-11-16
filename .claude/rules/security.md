# RedLine Security Rules

Security requirements for the RedLine platform. These are non-negotiable.

---

## Rule 1: Password Hashing — bcrypt Only

**Never:** MD5, SHA1, SHA256, plaintext.

**Always:**

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Hash a password
hashed = pwd_context.hash(raw_password)

# Verify a password
is_valid = pwd_context.verify(raw_password, hashed_password)
```

The bcrypt work factor is the default (12 rounds). Do not lower it for performance.

---

## Rule 2: API Key Generation and Storage

**Generate:**

```python
import secrets

raw_key = "rl_live_" + secrets.token_urlsafe(32)
# Example: rl_live_Xk3mNp7qR2...
```

**Store (only the hash):**

```python
import hashlib

key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
# Store key_hash in api_keys.key_hash
# NEVER store raw_key
```

**Display:** Show `raw_key` to the user exactly once in the terminal. After that, it is irrecoverable. Document this in every API key creation script.

**Verify on request:**

```python
def verify_api_key(raw_key: str, db: Session) -> Optional[ApiKey]:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked_at.is_(None)
        )
    ).scalar_one_or_none()
```

---

## Rule 3: Refresh Token Generation and Rotation

**Generate:**

```python
import secrets

raw_token = secrets.token_urlsafe(48)  # 48 bytes = 64 char base64url
token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
```

**Store:** `token_hash` in `refresh_tokens.token_hash`. Return `raw_token` to client once.

**Rotation on use:**

1. Client sends `raw_token` to `POST /auth/refresh`
2. Server hashes it: `token_hash = SHA256(raw_token)`
3. Server looks up the token by hash
4. If token not found → 401 (already rotated or never valid)
5. If token found but `revoked_at IS NOT NULL` → **REUSE DETECTED**
6. On reuse: `UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = '<user_id>'` — revoke ALL sessions for this user
7. If token found and active: issue new access + refresh tokens, revoke the old one

**Token lifetimes:**
- Access tokens: 15 minutes (`exp = now + timedelta(minutes=15)`)
- Refresh tokens: 7 days (`expires_at = now + timedelta(days=7)`)

---

## Rule 4: JWT Specification

**Algorithm:** HS256

**Required claims:**

```python
{
    "sub": str(user_id_or_api_key_id),
    "tenant_id": str(tenant_id),
    "role": "admin" | "developer" | "viewer",
    "type": "access" | "refresh",   # REQUIRED — prevents using refresh tokens as access tokens
    "exp": <unix timestamp>,
    "iat": <unix timestamp>
}
```

**Issue with python-jose:**

```python
from jose import jwt
from apps.api.core.config import settings

token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm="HS256")
```

**Decode and verify:**

```python
from jose import jwt, JWTError

try:
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
except JWTError:
    raise HTTPException(status_code=401, detail="Invalid or expired token")
```

**Never:**
- Accept a refresh token where an access token is expected (check `"type"` claim)
- Use `algorithms=["none"]` or skip algorithm verification

---

## Rule 5: Rate Limiting

**API rate limiting:** 100 requests per 60 seconds per tenant.

Implemented via Redis sorted set in `apps/api/core/redis_client.py`:

```python
class RateLimiter:
    def check_rate_limit(self, tenant_id: str, limit: int = 100, window: int = 60) -> bool:
        # Uses Redis ZADD + ZREMRANGEBYSCORE + ZCARD sliding window
        ...
```

**LLM rate limiting:** Per-profile RPM limit in `LLMRateLimiter`. Configured by `model_profiles.yaml`.

Call `rate_limiter.acquire()` before every Gemini API call. This is blocking — it sleeps until a slot opens.

---

## Rule 6: Postgres Credentials — Never in Code

`DATABASE_URL` must come from the environment or `.env` file via `pydantic-settings`. Never hardcode:

```python
# WRONG
engine = create_engine("postgresql://redline:redline_dev@localhost:5433/redline")

# CORRECT
from apps.api.core.config import settings
engine = create_engine(settings.DATABASE_URL)
```

**`.env` file:** Must be in `.gitignore`. Check:

```bash
grep ".env" .gitignore
```

**`.env.example`:** Committed with placeholder values (no real credentials).

---

## Rule 7: ClickHouse Password

ClickHouse requires a password for network access (even on localhost Docker network for the `default` user).

**Required in `.env`:**

```
CLICKHOUSE_PASSWORD=redline_dev
```

**Never:** Leave `CLICKHOUSE_PASSWORD` empty. An empty password causes 403 errors when `emit_trace()` tries to write.

**In `clickhouse_client.py`:**

```python
client = clickhouse_connect.get_client(
    host=settings.CLICKHOUSE_HOST,
    port=settings.CLICKHOUSE_PORT,
    username="default",
    password=settings.CLICKHOUSE_PASSWORD,
    database="redline"
)
```

---

## Rule 8: Never Log Raw Tokens or Keys

Structured logging must never include:

- Raw API keys (`rl_live_...`)
- Raw JWT tokens
- Raw refresh tokens
- Passwords (even hashed ones)
- `DATABASE_URL` (contains password)
- `GEMINI_API_KEY`

**Safe to log:**
- Token hashes (SHA256 hex)
- User IDs (UUIDs)
- Tenant IDs
- API key names (not the key itself)

**Check logs for accidental exposure:**

```bash
grep -rn "rl_live_\|ey[A-Za-z0-9]" run.log | head -10
```

---

## Rule 9: RBAC Dependency Pattern

Use `require_role()` for RBAC on sensitive endpoints:

```python
from apps.api.core.security import require_api_key, require_role, AuthContext

# Require admin role
@router.post("/admin/action")
def admin_action(auth: AuthContext = Depends(require_role("admin"))):
    ...

# Any authenticated role
@router.get("/eval-runs/{run_id}")
def get_eval_run(auth: AuthContext = Depends(require_api_key)):
    ...
```

**Role hierarchy:** `admin` can do everything `developer` can. `developer` can do everything `viewer` can.

| Operation | Required Role |
|---|---|
| Read eval runs, dashboard | viewer |
| Create eval runs, push suites | developer |
| Manage agents, gates, API keys | admin |
| Revoke API keys | admin |

---

## Rule 10: Branch Protection and CI

The `agentbench-check.yml` GitHub Actions workflow must be a **required status check** in branch protection settings for `main`.

A failing gate check (exit code 1 from `agentbench ci-check`) must block the merge button.

**Verify branch protection:**

```bash
gh api repos/uh-bhinav/RedLine/branches/main/protection
```

The `required_status_checks.contexts` array must include `"AgentBench Reliability Check"`.
