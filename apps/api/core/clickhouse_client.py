"""
ClickHouse client (Phase 2 Section 4).

ClickHouse is used for the append-heavy, query-heavy trace/event data described
in Holy Grail §10.6. Postgres handles relational metadata (tenants, eval runs,
results). ClickHouse handles the per-turn event stream -- a single eval run can
emit ~20 events, and at meaningful scale (1M+ runs) that's tens of millions of
rows of time-series data that Postgres would struggle with analytically.

The three event types emitted during an eval run:
  - run_started    : when eval_engine.run_eval() begins a run
  - turn_completed : after each agent turn (one per scripted turn in the case)
  - run_completed  : when eval_engine.run_eval() finishes (pass/fail + gate verdict)

These land in ClickHouse via the TraceWorker (trace.emitted Redpanda topic).
For Phase 2, the eval engine also writes directly to ClickHouse (simpler, proves
the data path). The full async TraceWorker via Redpanda is Phase 2 Section 4b.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from clickhouse_driver import Client

from apps.api.core.config import get_settings

_settings = get_settings()


def get_clickhouse() -> Client:
    return Client(
        host=_settings.clickhouse_host,
        port=_settings.clickhouse_port,
        database=_settings.clickhouse_db,
        user=_settings.clickhouse_user,
        password=_settings.clickhouse_password,
    )


# DDL as a constant so init_clickhouse() and tests can reference the same schema
TRACES_DDL = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id     UUID,
    eval_run_id  UUID,
    tenant_id    UUID,
    event_type   String,
    case_key     String,
    turn_index   UInt8,
    latency_ms   UInt32,
    cost_usd     Float32,
    passed       Nullable(UInt8),
    detail       String,
    created_at   DateTime64(3, 'UTC')
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, eval_run_id, created_at)
"""


def init_clickhouse() -> None:
    """Creates the redline database and traces table if they don't exist.

    Idempotent -- safe to re-run. Call once at startup or via the init script.
    """
    # Connect without a database first to create it if needed
    root = Client(
        host=_settings.clickhouse_host,
        port=_settings.clickhouse_port,
        user=_settings.clickhouse_user,
        password=_settings.clickhouse_password,
    )
    root.execute(f"CREATE DATABASE IF NOT EXISTS {_settings.clickhouse_db}")

    ch = get_clickhouse()
    ch.execute(TRACES_DDL)
    print(f"ClickHouse: database '{_settings.clickhouse_db}' and table 'traces' ready.")


def emit_trace(
    *,
    eval_run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    event_type: str,
    case_key: str = "",
    turn_index: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    passed: bool | None = None,
    detail: str = "",
) -> None:
    """Inserts one trace event row into ClickHouse.

    Called by the eval engine at key points in the run lifecycle.
    Failures here are logged but never raise -- a trace write failure must
    never block or corrupt the actual eval result.
    """
    try:
        ch = get_clickhouse()
        ch.execute(
            """
            INSERT INTO traces
            (trace_id, eval_run_id, tenant_id, event_type, case_key,
             turn_index, latency_ms, cost_usd, passed, detail, created_at)
            VALUES
            """,
            [{
                "trace_id": uuid.uuid4(),
                "eval_run_id": eval_run_id,
                "tenant_id": tenant_id,
                "event_type": event_type,
                "case_key": case_key,
                "turn_index": turn_index,
                "latency_ms": latency_ms,
                "cost_usd": cost_usd,
                "passed": int(passed) if passed is not None else None,
                "detail": detail,
                "created_at": datetime.utcnow(),
            }],
        )
    except Exception as e:
        print(f"[trace] write failed (non-fatal): {e}")