"""Fixtures for HTTP-level endpoint tests that need only Postgres (+ Redis for the
rate-limit middleware) -- no Redpanda, ClickHouse or LLM.

Safety: DATABASE_URL is redirected to a throwaway database (`<dbname>_test`,
created on demand and migrated with alembic to head) BEFORE any apps.* import, so
the dev database is never touched. If apps.api.core.db was already imported against
a different database in this session, every test here is skipped rather than risk it.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[4]


def _resolve_test_url() -> str | None:
    explicit = os.environ.get("REDLINE_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL")
    if not base:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    base = line.split("=", 1)[1].strip()
    if not base:
        return None
    url = make_url(base)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


_TEST_URL = _resolve_test_url()
_READY = False

if _TEST_URL and "apps.api.core.db" not in sys.modules:
    os.environ["DATABASE_URL"] = _TEST_URL
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-prod-0123456789")
    try:
        url = make_url(_TEST_URL)
        admin = create_engine(
            url.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as c:
            exists = c.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            ).scalar()
            if not exists:
                c.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin.dispose()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT, env=os.environ.copy(), check=True,
            capture_output=True,
        )
        _READY = True
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"test DB setup failed: {e}")


@pytest.fixture(scope="session")
def client():
    if not _READY:
        pytest.skip("throwaway test database unavailable")
    from apps.api.core.db import engine

    if not str(engine.url.database).endswith("_test"):
        pytest.skip("refusing to run against a non-test database")

    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as c:
        yield c


def _register(client) -> dict:
    email = f"t-{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "Passw0rdTest", "name": "Tester"},
    )
    assert r.status_code == 201, r.text
    tok = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    return {"headers": {"Authorization": f"Bearer {tok}"}, "tenant_id": me["tenant_id"]}


@pytest.fixture()
def tenant_a(client):
    return _register(client)


@pytest.fixture()
def tenant_b(client):
    return _register(client)
