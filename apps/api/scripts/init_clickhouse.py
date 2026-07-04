"""
Creates the ClickHouse database and traces table.

Idempotent -- safe to re-run. Call once after `docker compose up`.

Usage (from the repo root):
    python -m apps.api.scripts.init_clickhouse
"""
from apps.api.core.clickhouse_client import init_clickhouse

if __name__ == "__main__":
    init_clickhouse()