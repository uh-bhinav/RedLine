from fastapi import FastAPI
from sqlalchemy import text

from apps.api.core.db import engine
from fastapi import Request
from fastapi.responses import JSONResponse
from apps.api.core.redis_client import RateLimiter
import hashlib, uuid

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="RedLine API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "redline-api"}

_rate_limiter = RateLimiter(max_requests=100, window_seconds=60)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for health check and docs
    if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    
    # Use API key hash as tenant proxy until full auth is in (Phase 2 §10.2)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_key = auth_header.removeprefix("Bearer ").strip()
        # Derive a stable UUID from the key hash so RateLimiter's UUID signature is satisfied
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        tenant_proxy_id = uuid.UUID(key_hash[:32])
    else:
        # Unauthenticated requests share one bucket -- they'll hit the limit fast
        tenant_proxy_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    
    if not _rate_limiter.is_allowed(tenant_proxy_id):
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded -- 100 requests per 60 seconds"},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)


from apps.api.routers import dashboard
from apps.api.routers import agent, ci, diff, eval_runs, eval_suites, load_runs, mining
from apps.api.routers import auth

app.include_router(agent.router)
app.include_router(eval_suites.router)
app.include_router(ci.router)
app.include_router(eval_runs.router)
app.include_router(diff.router)
app.include_router(load_runs.router)
app.include_router(mining.router)
app.include_router(dashboard.router)
app.include_router(auth.router)