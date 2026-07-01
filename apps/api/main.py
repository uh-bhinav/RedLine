from fastapi import FastAPI
from sqlalchemy import text

from apps.api.core.db import engine

app = FastAPI(title="RedLine API", version="0.1.0")


@app.get("/health")
def health_check():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "redline-api"}

from apps.api.routers import eval_runs
from apps.api.routers import agent, ci, eval_runs, eval_suites
app.include_router(agent.router)
app.include_router(eval_suites.router)
app.include_router(ci.router)
app.include_router(eval_runs.router)
