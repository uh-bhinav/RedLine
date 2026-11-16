---
name: fastapi-patterns
description: RedLine FastAPI endpoint patterns — how to add endpoints, wire auth dependencies, set up response models, and register routes in the correct service.
---

# RedLine FastAPI Patterns

Use this skill when:
- Adding a new API endpoint to any RedLine service
- Wiring auth (JWT + API key) to a new route
- Adding rate limiting middleware
- Debugging a 422 Unprocessable Entity or 401 Unauthorized

---

## Pattern 1: Adding a New Endpoint

### Step 1 — Determine the correct router file

| What the route does | Router file | Service |
|---|---|---|
| Manage eval runs or CI checks | `apps/api/routers/eval_runs.py` or `routers/ci.py` | eval_service (8001) |
| Manage agent registry or suites | `apps/api/routers/agents.py` or `routers/eval_suites.py` | agent_service (8002) |
| Read dashboard data | `apps/api/routers/dashboard.py` | gate_service (8003) |
| Auth (login/refresh/logout) | `apps/api/routers/auth.py` | eval_service (8001) |

### Step 2 — Write the endpoint

```python
# apps/api/routers/eval_runs.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from apps.api.core.db import get_db
from apps.api.core.security import require_api_key, AuthContext
from apps.api.models.eval import EvalRun
from apps.api.schemas.eval_run import EvalRunCreate, EvalRunResponse

router = APIRouter(prefix="/eval-runs", tags=["eval-runs"])

@router.post("", response_model=EvalRunResponse, status_code=201)
def create_eval_run(
    body: EvalRunCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_api_key),
):
    # Business logic here
    eval_run = EvalRun(
        tenant_id=auth.tenant_id,
        ...
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)
    return eval_run
```

### Step 3 — Register in service main.py

```python
# apps/eval_service/main.py
from apps.api.routers.eval_runs import router as eval_runs_router

app = FastAPI()
app.include_router(eval_runs_router)
```

### Step 4 — Register in monolith for dev mode

```python
# apps/api/main.py
from apps.api.routers.eval_runs import router as eval_runs_router

app.include_router(eval_runs_router)
```

---

## Pattern 2: Auth Dependencies

RedLine has two auth dependencies:

### `require_api_key` — Any authenticated caller

Accepts **both** JWT Bearer tokens and raw API keys (`rl_live_...` prefix). Returns an `AuthContext`.

```python
from apps.api.core.security import require_api_key, AuthContext

@router.get("/eval-runs/{run_id}", response_model=EvalRunResponse)
def get_eval_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_api_key),
):
    # auth.tenant_id — UUID, always present
    # auth.role — "admin" | "developer" | "viewer"
    # auth.user_id — UUID | None (None for API key auth)
    # auth.api_key_id — UUID | None (None for JWT auth)
    ...
```

### `require_role(role)` — Role-gated access

Use when the endpoint requires a specific role or higher:

```python
from apps.api.core.security import require_role

@router.delete("/agents/{agent_id}", status_code=204)
def delete_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_role("admin")),  # admin only
):
    ...
```

Role hierarchy: `admin > developer > viewer`. `require_role("developer")` allows `developer` and `admin`.

---

## Pattern 3: Rate Limiting Middleware

Rate limiting is applied per-tenant using Redis. It is wired in `setup_metrics()` in `apps/api/core/telemetry.py`.

The middleware reads `auth.tenant_id` from request state (set by `require_api_key`). Requests over 100/60s for a tenant get 429.

**If you add a new service app and need rate limiting:**

```python
# In your service's main.py
from apps.api.core.telemetry import setup_metrics

app = FastAPI()
setup_metrics(app)  # Registers /metrics endpoint + rate limiting middleware
```

---

## Pattern 4: Response Models

Every endpoint must have `response_model=` on the decorator. Response models live in `apps/api/schemas/`.

```python
# apps/api/schemas/eval_run.py
from pydantic import BaseModel
import uuid
from datetime import datetime

class EvalRunResponse(BaseModel):
    id: uuid.UUID
    status: str
    agent_version_id: uuid.UUID
    suite_id: uuid.UUID
    created_at: datetime
    
    model_config = {"from_attributes": True}  # Pydantic v2 ORM mode
```

`from_attributes = True` enables loading from SQLAlchemy ORM objects via `model_validate(orm_obj)`.

---

## Pattern 5: Health Endpoint

Every service app must expose `/health`:

```python
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from apps.api.core.db import get_db

app = FastAPI()

@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "eval-service"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {e}")
```

The health endpoint is what Kubernetes liveness probes, nginx upstreams, and KEDA trigger health checks against. It must make a real DB query — not just return static JSON.

---

## Pattern 6: Error Handling

Use FastAPI's `HTTPException` for all user-facing errors:

```python
from fastapi import HTTPException

# 404
raise HTTPException(status_code=404, detail=f"EvalRun {run_id} not found")

# 409 Conflict (duplicate content hash)
raise HTTPException(status_code=409, detail="Agent version with this content hash already exists")

# 403 Forbidden (wrong role)
raise HTTPException(status_code=403, detail="Admin role required")

# 422 Unprocessable — let FastAPI handle this automatically via Pydantic validation
```

Do NOT use generic `Exception` or `ValueError` — they produce 500s with unhelpful messages.

---

## Common Mistakes

1. **Forgetting `response_model=`** — FastAPI returns untyped JSON, bypassing Pydantic validation
2. **Using `db.query()` instead of `select()`** — SQLAlchemy 1.x legacy pattern, forbidden
3. **Not calling `db.refresh(obj)` after `db.commit()`** — the object's attributes may be stale
4. **Adding a route to the wrong service** — `/eval-runs` in `agent_service` breaks the service decomposition
5. **Not registering the router in the monolith** — the route works in microservice mode but not in dev mode
