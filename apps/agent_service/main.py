"""
Agent Service (Phase 2 Section 5 — service decomposition).

Owns: agent registry, agent versions, eval suites.
Port: 8002 (internal).

Why separate: agent registration and versioning are write-once, read-many
operations. This service is unlikely to need scaling beyond 1-2 replicas and
changes only when the registry model changes — independent of eval logic.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import agent, eval_suites
from apps.api.routers import auth
from apps.api.core.telemetry import setup_metrics

app = FastAPI(
    title="RedLine Agent Service",
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

setup_metrics(app, "agent-service")

app.include_router(agent.router)
app.include_router(eval_suites.router)
app.include_router(auth.router)


@app.get("/health")
def health():
    from sqlalchemy import text
    from apps.api.core.db import engine
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "agent-service"}