from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    # Phase 5.1 -- true when database_url points at PgBouncer instead of
    # Postgres directly. See db.py for why this changes the SQLAlchemy pool
    # class, and docs/infra-hardening.md for the opt-in switch. Default false:
    # this is a blast-radius change to every service's DB path, not something
    # to flip on by default until a real deployment needs the connection-count
    # relief (Phase 5.4, deferred).
    db_use_external_pooler: bool = False
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    github_token: str = ""

    # Phase 2 additions
    redis_url: str = "redis://localhost:6379/0"
    redpanda_bootstrap_servers: str = "localhost:19092"
    topic_eval_requested: str = "eval.requested"
    topic_eval_completed: str = "eval.completed"
    topic_trace_emitted: str = "trace.emitted"

    # Phase 4 Section 4 -- load testing gets its own topic, consumed by its own
    # worker pool (foundational doc §9.3: separate worker pools by resource
    # profile). See redpanda_queue.py's _KNOWN_TOPICS for why this matters.
    topic_load_requested: str = "load.requested"

    # Phase 5.1 -- dead-letter queue. A job is republished with an incremented
    # retry_count on failure; once retry_count exceeds this, it's published to
    # <topic>.dead-letter instead of being retried again.
    max_job_retries: int = 3

    # Phase 2 Section 4
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 9000
    clickhouse_db: str = "redline"
    # Phase 5.1 -- least-privilege app identity (SELECT, INSERT only), not the
    # ClickHouse superuser. See init_clickhouse() for the CREATE USER/GRANT.
    clickhouse_user: str = "redline_app"
    clickhouse_password: str = ""
    # Bootstrap-only: creates the database, tables, and the app user above.
    # Never used by get_clickhouse() (the request-path client) -- only by
    # init_clickhouse()'s one-time setup. Defaults to the container's own
    # built-in superuser.
    clickhouse_admin_user: str = "default"
    clickhouse_admin_password: str = ""

    # Phase 5.1 -- OTLP trace export target (Grafana Tempo). Defaults to a
    # host-run worker process's view of the world, same convention as
    # redpanda_bootstrap_servers.
    otel_exporter_endpoint: str = "http://localhost:4317"

    # Per-credential API rate limit (requests per 60s window). Raised from the
    # old hardcoded 100 because the dashboard polls several endpoints at once.
    rate_limit_per_minute: int = 600

@lru_cache
def get_settings() -> Settings:
    return Settings()