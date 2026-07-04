from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
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

    # Phase 2 Section 4
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 9000
    clickhouse_db: str = "redline"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()