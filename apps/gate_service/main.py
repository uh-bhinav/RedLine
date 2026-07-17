"""
Gate Service (Phase 2 Section 5 — service decomposition).

Owns: gate policy evaluation, dashboard read endpoints.
Port: 8003 (internal).

Why separate (Holy Grail §9.3): "Policy/Gate logic changes far less often than
Eval logic; you don't want to redeploy your entire backend every time you tweak
an evaluation metric." The gate service can be a single stable replica; only
the eval service needs elastic scaling.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import dashboard
from apps.api.routers import auth
from apps.api.core.telemetry import setup_metrics

app = FastAPI(
    title="RedLine Gate Service",
    version="0.2.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, "gate-service")

app.include_router(dashboard.router)
app.include_router(auth.router)

@app.get("/health")
def health():
    from sqlalchemy import text
    from apps.api.core.db import engine
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "gate-service"}