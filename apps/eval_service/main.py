"""
Eval Service (Phase 2 Section 5 — service decomposition).

Owns: eval runs lifecycle, CI check triggering, job publishing.
Port: 8001 (internal — never exposed directly; traffic arrives via the gateway).

Why this service is separate (Holy Grail §9.3): the Eval Service changes whenever
eval logic changes — new scorers, new adapter types, new eval metrics. It may need
many replicas under load. Policy/Gate and Agent Registry code changes far less
often and would be unaffected redeploys without this separation.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import ci, eval_runs
from apps.api.routers import auth

app = FastAPI(
    title="RedLine Eval Service",
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

app.include_router(eval_runs.router)
app.include_router(ci.router)
app.include_router(auth.router)


@app.get("/health")
def health():
    from sqlalchemy import text
    from apps.api.core.db import engine
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "eval-service"}