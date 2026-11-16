"""
Shared pytest harness for the RedLine API.

Isolation rules:
  * Tests NEVER touch the dev database. DATABASE_URL is forced to a dedicated
    `redline_test` database *before* any `apps.api` import (core/db.py builds its engine
    at import time and get_settings() is lru_cached).
  * Database selection, in order:
      1. TEST_DATABASE_URL, if set.
      2. Native Postgres 16 at localhost:5432 (postgres / redline_dev_password), if reachable.
      3. The embedded pgserver instance from scripts/dev_db.py (host/port from .env
         DATABASE_URL, database name replaced by `redline_test`).
  * The test DB is created if missing, `alembic upgrade head` runs once per session, and
    every table except alembic_version is truncated between tests.
"""
from __future__ import annotations

import os
import secrets
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
TEST_DB_NAME = "redline_test"
NATIVE_URL = "postgresql+psycopg2://postgres:redline_dev_password@localhost:5432/postgres"


def _read_dotenv(key: str) -> str | None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def _reachable(url: str) -> bool:
    u = make_url(url)
    try:
        psycopg2.connect(
            host=u.host, port=u.port, user=u.username, password=u.password,
            dbname=u.database, connect_timeout=3,
        ).close()
        return True
    except psycopg2.Error:
        return False


def _resolve_test_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    if _reachable(NATIVE_URL):
        return str(make_url(NATIVE_URL).set(database=TEST_DB_NAME).render_as_string(hide_password=False))
    dev_url = os.environ.get("DATABASE_URL") or _read_dotenv("DATABASE_URL")
    if not dev_url:
        raise RuntimeError("no TEST_DATABASE_URL, native Postgres, or .env DATABASE_URL available")
    if not _reachable(dev_url):
        # (re)start the embedded server from scripts/dev_db.py; it keeps running afterwards
        import pgserver

        pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode=None)
    return make_url(dev_url).set(database=TEST_DB_NAME).render_as_string(hide_password=False)


def _ensure_database(test_url: str) -> None:
    u = make_url(test_url)
    if u.database in (None, "postgres"):
        raise RuntimeError(f"refusing to run tests against non-test database {u.database!r}")
    conn = psycopg2.connect(
        host=u.host, port=u.port, user=u.username, password=u.password,
        dbname="postgres", connect_timeout=5,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (u.database,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        conn.close()


# ---- must run before any `apps.api` import --------------------------------------------
TEST_DATABASE_URL = _resolve_test_url()
_ensure_database(TEST_DATABASE_URL)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET_KEY", _read_dotenv("JWT_SECRET_KEY") or secrets.token_urlsafe(48))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ---------------------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from apps.api.core.config import get_settings  # noqa: E402
from apps.api.core.db import SessionLocal, engine  # noqa: E402
from apps.api.core.security import create_access_token, hash_api_key, hash_password  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.models import ApiKey, Tenant, User  # noqa: E402

assert get_settings().database_url == TEST_DATABASE_URL
assert engine.url.database == make_url(TEST_DATABASE_URL).database


def _llm_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or get_settings().gemini_api_key)


def pytest_collection_modifyitems(config, items):
    if _llm_available():
        return
    skip = pytest.mark.skip(reason="requires_llm: GEMINI_API_KEY is not set")
    for item in items:
        if "requires_llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "apps" / "api" / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables(_migrated_database):
    """Truncate every table except alembic_version after (and before) each test."""

    def truncate():
        with engine.begin() as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                    )
                )
            ]
            if tables:
                quoted = ", ".join(f'"{t}"' for t in tables)
                conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_tenant():
    def _make(name: str | None = None):
        with SessionLocal() as s:
            tenant = Tenant(name=name or f"tenant-{uuid.uuid4().hex[:8]}")
            s.add(tenant)
            s.commit()
            s.refresh(tenant)
            return SimpleNamespace(id=tenant.id, name=tenant.name)

    return _make


@pytest.fixture
def auth_headers():
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def make_user(make_tenant, auth_headers):
    def _make(role: str = "admin", tenant=None, password: str = "correct-horse-battery"):
        tenant = tenant or make_tenant()
        with SessionLocal() as s:
            user = User(
                tenant_id=tenant.id,
                name=f"{role}-user",
                email=f"{role}-{uuid.uuid4().hex[:8]}@example.test",
                hashed_password=hash_password(password),
                role=role,
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            token = create_access_token(user)
            return SimpleNamespace(
                id=user.id, tenant_id=tenant.id, tenant=tenant, email=user.email, role=role,
                password=password, token=token, headers=auth_headers(token),
            )

    return _make


@pytest.fixture
def api_key(make_tenant, auth_headers):
    """An API key for a fresh tenant. Call api_key(role=..., tenant=...) via .make for variants."""

    def _make(role: str = "admin", tenant=None):
        tenant = tenant or make_tenant()
        raw = "rl_" + secrets.token_urlsafe(32)
        with SessionLocal() as s:
            key = ApiKey(
                tenant_id=tenant.id, name="test key", label="test key",
                key_hash=hash_api_key(raw), last_four=raw[-4:], role=role,
            )
            s.add(key)
            s.commit()
            s.refresh(key)
            return SimpleNamespace(
                id=key.id, tenant_id=tenant.id, tenant=tenant, role=role, raw=raw,
                headers=auth_headers(raw),
            )

    default = _make()
    default.make = _make
    return default
