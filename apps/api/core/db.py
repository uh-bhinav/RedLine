from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from apps.api.core.config import get_settings

settings = get_settings()

# Phase 5.1 -- when DATABASE_URL points at PgBouncer (opt-in, see
# docs/infra-hardening.md) instead of Postgres directly, SQLAlchemy must NOT
# also pool connections: PgBouncer's transaction-mode pool underneath a second,
# independent QueuePool would double-pool, defeating the point of adding a
# pooler in the first place. NullPool makes every checkout a fresh connection
# to PgBouncer, which is exactly what PgBouncer itself is designed to pool.
_engine_kwargs = {"poolclass": NullPool} if settings.db_use_external_pooler else {"pool_pre_ping": True}

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()