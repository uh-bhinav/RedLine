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

import re
import uuid
from datetime import datetime

from clickhouse_driver import Client

from apps.api.core.config import get_settings

_settings = get_settings()

# Phase 5.1 -- init_clickhouse() interpolates clickhouse_user into raw SQL
# (CREATE USER/GRANT) since clickhouse-driver's parameter binding doesn't cover
# identifiers. This runs once from a trusted init script, not request-path
# input, but validating first removes any ambiguity about why an f-string is
# safe here.
_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


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

# Phase 4 Section 4 -- one row per simulated request during a load test. This is
# the append-heavy, high-volume shape ClickHouse was chosen for in the first
# place (Holy Grail §10.6): a single load test at 100 concurrent users for 60s can
# produce thousands of samples, and the only queries against this data are
# aggregations (percentiles, error rate) -- exactly ClickHouse's strength, not
# Postgres's. The aggregate result of a run lives on the Postgres `load_runs` row;
# this table is the raw samples underneath that aggregate.
LOAD_SAMPLES_DDL = """
CREATE TABLE IF NOT EXISTS load_samples (
    load_run_id  UUID,
    tenant_id    UUID,
    latency_ms   UInt32,
    success      UInt8,
    cost_usd     Float32,
    error_detail String,
    created_at   DateTime64(3, 'UTC')
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, load_run_id, created_at)
"""


def init_clickhouse() -> None:
    """Creates the redline database, tables, and the least-privilege app user
    if they don't exist.

    Idempotent -- safe to re-run. Call once at startup or via the init script.

    Phase 5.1: DDL (CREATE DATABASE/TABLE) and CREATE USER/GRANT all run via
    the admin client, never via get_clickhouse() -- that's the app-runtime
    client, and once the app user is locked down to SELECT/INSERT it has no
    CREATE rights to run this script a second time with.
    """
    root = Client(
        host=_settings.clickhouse_host,
        port=_settings.clickhouse_port,
        user=_settings.clickhouse_admin_user,
        password=_settings.clickhouse_admin_password,
    )
    root.execute(f"CREATE DATABASE IF NOT EXISTS {_settings.clickhouse_db}")
    root.execute(TRACES_DDL)
    root.execute(LOAD_SAMPLES_DDL)
    print(
        f"ClickHouse: database '{_settings.clickhouse_db}', tables 'traces' and "
        f"'load_samples' ready."
    )

    if not _VALID_IDENTIFIER.match(_settings.clickhouse_user):
        raise ValueError(
            f"clickhouse_user '{_settings.clickhouse_user}' is not a valid SQL "
            f"identifier -- refusing to interpolate it into CREATE USER/GRANT."
        )
    root.execute(
        f"CREATE USER IF NOT EXISTS {_settings.clickhouse_user} "
        f"IDENTIFIED WITH sha256_password BY %(pw)s",
        {"pw": _settings.clickhouse_password},
    )
    root.execute(
        f"GRANT SELECT, INSERT ON {_settings.clickhouse_db}.* TO {_settings.clickhouse_user}"
    )
    print(
        f"ClickHouse: least-privilege user '{_settings.clickhouse_user}' ready "
        f"(SELECT, INSERT only)."
    )


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


def emit_load_samples(
    *,
    load_run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    samples: list[dict],
) -> None:
    """Batch-inserts load-test samples into ClickHouse. `samples` is a list of
    {latency_ms, success, cost_usd, error_detail} dicts -- one per simulated
    request. Batched (one INSERT for potentially thousands of rows) rather than
    per-sample like emit_trace(), since a load test can produce far more rows per
    run than an eval run's ~20 trace events ever would.

    Same rule as emit_trace(): a ClickHouse write failure here must never affect
    the load test's own result -- the aggregate stats are already computed in
    Python from the in-memory samples before this is called, so a write failure
    here only means the raw samples aren't queryable later, not that the run's
    reported result is wrong.
    """
    if not samples:
        return
    try:
        ch = get_clickhouse()
        now = datetime.utcnow()
        ch.execute(
            """
            INSERT INTO load_samples
            (load_run_id, tenant_id, latency_ms, success, cost_usd, error_detail, created_at)
            VALUES
            """,
            [
                {
                    "load_run_id": load_run_id,
                    "tenant_id": tenant_id,
                    "latency_ms": max(0, s["latency_ms"]),
                    "success": int(s["success"]),
                    "cost_usd": s.get("cost_usd", 0.0),
                    "error_detail": s.get("error_detail", ""),
                    "created_at": now,
                }
                for s in samples
            ],
        )
    except Exception as e:
        print(f"[load_samples] write failed (non-fatal): {e}")