import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.core.config import get_settings
from apps.api.core.db import engine
from apps.api.core.errors import RequestIdMiddleware, install_error_handling
from apps.api.core.security import validate_jwt_secret
from apps.api.routers import agent, analytics, auth, ci, dashboard, eval_runs, eval_suites

logger = logging.getLogger("redline.api")

# Fail fast: refuse to boot with a weak JWT signing key.
validate_jwt_secret(get_settings().jwt_secret_key)

_ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="RedLine API", version="0.2.0")

install_error_handling(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
# Added last => outermost, so every response (incl. CORS preflight) carries X-Request-ID.
app.add_middleware(RequestIdMiddleware)


@app.get("/health")
def health_check():
    """Liveness only: the process is up. Deliberately does not touch the database."""
    return {"status": "ok", "service": "redline-api"}


def _alembic_head() -> str | None:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "apps" / "api" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@app.get("/ready")
def readiness_check():
    """Readiness: DB reachable and schema at the alembic head revision."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            current = MigrationContext.configure(conn).get_current_revision()
        head = _alembic_head()
    except Exception:
        logger.exception("readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable", "reason": "database unreachable"})
    if current != head:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "reason": "database schema is not at head; run alembic upgrade head",
                "current": current,
                "head": head,
            },
        )
    return {"status": "ready", "revision": current}


for router in (
    auth.router,
    agent.router,
    eval_suites.router,
    ci.router,
    eval_runs.router,
    dashboard.router,
    analytics.router,
):
    app.include_router(router)
