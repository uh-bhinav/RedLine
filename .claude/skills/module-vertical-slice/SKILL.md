---
name: module-vertical-slice
description: RedLine service decomposition patterns — which code lives where, how to add a new microservice, the commonEnv Helm template, nginx gateway routing, and why each service has a health endpoint.
---

# RedLine Service Decomposition — Module Vertical Slice

Use this skill when:
- Adding a new endpoint and deciding which service it belongs to
- Adding a new microservice to the platform
- Understanding how nginx routes requests
- Understanding the Helm chart's shared config pattern
- Debugging why a route works in monolith mode but not microservice mode

---

## Code Ownership by Layer

Every feature in RedLine follows the same vertical slice:

```
Router  →  Service  →  Model  →  Schema
(HTTP)     (logic)    (ORM)     (Pydantic)
```

| Layer | Location | Responsibility |
|---|---|---|
| Router | `apps/api/routers/` | HTTP contract, auth, request parsing, response serialization |
| Service | `apps/api/services/` | Business logic, orchestration, no HTTP concerns |
| Model | `apps/api/models/` | SQLAlchemy ORM, DB schema |
| Schema | `apps/api/schemas/` | Pydantic request/response models |
| Core | `apps/api/core/` | Infrastructure: DB, auth, config, rate limiting, telemetry |

**Services never import from routers. Routers never contain business logic.**

---

## Service Ownership Map

| Domain | Router | Service | Microservice app |
|---|---|---|---|
| Eval runs lifecycle | `routers/eval_runs.py` | `services/eval_engine.py` | `eval_service/main.py` (port 8001) |
| CI gate checks | `routers/ci.py` | `services/gate_engine.py` | `eval_service/main.py` (port 8001) |
| Auth | `routers/auth.py` | `core/auth.py` | `eval_service/main.py` (port 8001) |
| Agent registry | `routers/agents.py` | — (direct DB) | `agent_service/main.py` (port 8002) |
| Eval suites | `routers/eval_suites.py` | — (direct DB) | `agent_service/main.py` (port 8002) |
| Dashboard reads | `routers/dashboard.py` | — (direct DB queries) | `gate_service/main.py` (port 8003) |

---

## nginx Gateway Routing

All external traffic enters at port 8085 (Docker Compose) or port 8000 (k3d). nginx routes by URL prefix:

```nginx
# infra/gateway.nginx.conf

# eval runs + ci + auth → eval_service
location /eval-runs   { proxy_pass http://eval_service:8001; }
location /ci          { proxy_pass http://eval_service:8001; }
location /auth        { proxy_pass http://eval_service:8001; }

# agent registry + suites → agent_service
location /agents      { proxy_pass http://agent_service:8002; }
location /eval-suites { proxy_pass http://agent_service:8002; }

# dashboard reads → gate_service
location /dashboard   { proxy_pass http://gate_service:8003; }

# metrics → eval_service (primary metrics aggregator)
location /metrics     { proxy_pass http://eval_service:8001; }
```

**Adding a new route with a new prefix:** Add a `location` block to `infra/gateway.nginx.conf` pointing to the correct upstream.

**Dev mode:** In `apps/api/main.py` (the monolith), all routers are included. No nginx needed for local development.

---

## Adding a New Microservice

If Phase 3 requires a new dedicated service (e.g., a `drift_service`):

### Step 1 — Create the app

```python
# apps/drift_service/main.py
from fastapi import FastAPI
from apps.api.core.telemetry import setup_metrics
from apps.api.routers.drift import router as drift_router

app = FastAPI(title="RedLine Drift Service")
setup_metrics(app)
app.include_router(drift_router, prefix="")

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "drift-service"}
```

### Step 2 — Create a Dockerfile

```dockerfile
# apps/drift_service/Dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "apps.drift_service.main:app", "--host", "0.0.0.0", "--port", "8004"]
```

### Step 3 — Add to `docker-compose.yml`

```yaml
drift_service:
  build:
    context: .
    dockerfile: apps/drift_service/Dockerfile
  ports:
    - "8004:8004"
  environment:
    DATABASE_URL: "postgresql://redline:redline_dev@postgres:5433/redline"
    REDIS_URL: "redis://redis:6379"
    CLICKHOUSE_HOST: "clickhouse"
    CLICKHOUSE_PASSWORD: "${CLICKHOUSE_PASSWORD}"
    JWT_SECRET_KEY: "${JWT_SECRET_KEY}"
  depends_on:
    - postgres
    - redis
```

### Step 4 — Add nginx location block

```nginx
location /drift { proxy_pass http://drift_service:8004; }
```

### Step 5 — Add Helm templates

Copy the pattern from `helm/redline/templates/eval-service/`:
- `deployment.yaml` — references `commonEnv` configmap
- `service.yaml` — ClusterIP on port 8004
- `hpa.yaml` — CPU HPA for stateless services

---

## The `commonEnv` Helm Template

All services in k3d share environment variables from a single ConfigMap:

```yaml
# helm/redline/templates/base/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redline-common-env
data:
  DATABASE_URL: "postgresql://redline:{{ .Values.postgres.password }}@host.k3d.internal:5433/redline"
  REDIS_URL: "redis://host.k3d.internal:6379"
  CLICKHOUSE_HOST: "host.k3d.internal"
  REDPANDA_BOOTSTRAP_SERVERS: "host.k3d.internal:19092"
```

Each deployment's pod spec references it:

```yaml
envFrom:
  - configMapRef:
      name: redline-common-env
  - secretRef:
      name: redline-secrets   # JWT_SECRET_KEY, GEMINI_API_KEY, CLICKHOUSE_PASSWORD
```

**When adding a new service to Helm:** Copy a deployment template, change the container name, image name, and port. The `envFrom` block is identical for all services — they all share the same infra config.

---

## Health Endpoint Contract

Every service app must implement `/health` with a live DB check:

```python
@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "eval-service"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB check failed: {e}")
```

**Why the DB check matters:**

- Kubernetes liveness probes hit `/health` — a 503 triggers a pod restart
- nginx upstream health checks use `/health` to route around failed pods
- KEDA's external trigger health check uses `/health` to confirm the scaler is healthy
- A service that can't reach Postgres can't do any useful work — `/health` returning 200 when the DB is down would be a lie

**Never:** Return 200 from `/health` without checking the DB.

---

## Monolith vs Microservice Mode

**Monolith mode** (`apps/api/main.py`): All routers included. Used for local dev. Start with:

```bash
python -m uvicorn apps.api.main:app --port 8000
```

**Microservice mode** (Docker Compose or k3d): Each service runs independently. Routers are split across service apps.

The routing logic is:
- In monolith: FastAPI resolves `/eval-runs` because the router is registered in `main.py`
- In microservice: nginx resolves `/eval-runs` to `eval_service:8001`, then FastAPI inside that container handles it

**A route registered only in the monolith but not in the service app will:**
- Work locally with `main.py`
- Return 404 in Docker Compose and k3d

Always register new routes in **both** the appropriate service app AND the monolith.
