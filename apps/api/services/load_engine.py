"""
Agent Load Testing engine (Phase 4 Section 5 -- foundational doc §5.5).

"k6/JMeter load-test APIs on latency and error rate. Nobody load-tests agent cost
and tool-failure rate under concurrency -- and cost is often the metric that kills
an agent in production (an agent that's fine at 10 users can become financially
unviable at 10,000)."

Concurrency model, and why it doesn't violate rule #2 (synchronous only)
--------------------------------------------------------------------------
The eval engine, scorers, and workers are synchronous by architectural rule --
confluent-kafka is sync, mixing asyncio with synchronous SQLAlchemy is a deadlock
trap. Load testing genuinely needs concurrency (many simulated users hammering an
agent at once), and `concurrent.futures.ThreadPoolExecutor` provides that without
asyncio anywhere: real OS-thread-based concurrency, ordinary synchronous Python in
each thread, zero event loop. Each thread is one "virtual user" -- it owns its own
`session_state` dict (never shared across threads) and repeatedly calls
`adapter.run_turn()` until the configured duration elapses.

Why the failure-rate is measured at the adapter boundary, not inside the agent
--------------------------------------------------------------------------------
Same disclosed scope as ChaosAdapter (Section 4.3): RedLine's AgentAdapter is a
black box, so "tool-failure rate under concurrency" here means "did the whole
run_turn() call succeed," which for an HTTP-deployed agent is a reasonable proxy
for its underlying tool/dependency health, and for a LocalPythonAdapter-wrapped
agent mostly measures whatever the agent's OWN process does under concurrent calls
(including its own use of the Redis-backed LLMRateLimiter, Phase 3.3 -- which is
exactly the payoff of making that limiter multi-worker-safe: concurrent load-test
threads calling an agent that calls get_limiter() share ONE real budget instead of
each thread getting its own illusory allowance).

Split into a pure stats function (`_compute_load_stats`, no DB, no I/O, unit
testable with synthetic samples) and a DB-backed orchestrator (`run_load_test`),
the same discipline as every other Phase 4 engine.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from apps.api.core.clickhouse_client import emit_load_samples
from apps.api.core.db import SessionLocal
from apps.api.models import AgentVersion, LoadRun
from apps.api.services.adapters import build_adapter


@dataclass
class LoadSample:
    latency_ms: int
    success: bool
    cost_usd: float = 0.0
    error_detail: str = ""


@dataclass
class LoadTestResult:
    total_requests: int
    successful_requests: int
    error_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    total_cost_usd: float
    cost_per_hour_usd: float
    throughput_rps: float
    detail: str
    samples: list[LoadSample] = field(default_factory=list, repr=False)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile -- simple, deterministic, no interpolation
    ambiguity to argue about for a metric that's already inherently noisy under
    concurrency. pct in [0, 100]."""
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, int(round(pct / 100 * len(sorted_values))) - 1))
    return sorted_values[index]


def _compute_load_stats(samples: list[LoadSample], duration_seconds: float) -> LoadTestResult:
    """Pure function -- no DB, no I/O, no network. Takes samples already collected
    and a wall-clock duration, returns the aggregate result.

    duration_seconds is passed in rather than inferred from the samples so a real
    caller can supply "how long the load test actually ran," including any
    ramp-up/ramp-down time between samples -- inferring it from sample count and
    latency alone would understate elapsed time under real concurrency.
    """
    total = len(samples)
    if total == 0:
        return LoadTestResult(
            total_requests=0, successful_requests=0, error_rate=0.0,
            p50_latency_ms=0.0, p95_latency_ms=0.0, p99_latency_ms=0.0,
            total_cost_usd=0.0, cost_per_hour_usd=0.0, throughput_rps=0.0,
            detail="no requests were completed during the load test window",
            samples=[],
        )

    successful = sum(1 for s in samples if s.success)
    error_rate = 1.0 - (successful / total)
    latencies = sorted(s.latency_ms for s in samples)
    total_cost = sum(s.cost_usd for s in samples)

    duration_hours = max(duration_seconds, 1e-9) / 3600.0
    cost_per_hour = total_cost / duration_hours
    throughput = total / max(duration_seconds, 1e-9)

    detail = (
        f"{total} requests ({successful} succeeded, {error_rate:.1%} error rate) "
        f"in {duration_seconds:.1f}s -- p50={_percentile(latencies, 50):.0f}ms "
        f"p95={_percentile(latencies, 95):.0f}ms p99={_percentile(latencies, 99):.0f}ms, "
        f"${cost_per_hour:.4f}/hour at this concurrency"
    )

    return LoadTestResult(
        total_requests=total,
        successful_requests=successful,
        error_rate=error_rate,
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        p99_latency_ms=_percentile(latencies, 99),
        total_cost_usd=total_cost,
        cost_per_hour_usd=cost_per_hour,
        throughput_rps=throughput,
        detail=detail,
        samples=samples,
    )


def _virtual_user(adapter, message: str, stop_at: float) -> list[LoadSample]:
    """One simulated user: its own session_state, calling the adapter in a loop
    until the shared deadline passes. Runs entirely inside one ThreadPoolExecutor
    worker thread -- ordinary synchronous code, no asyncio."""
    session_state: dict = {}
    samples: list[LoadSample] = []

    while time.monotonic() < stop_at:
        start = time.perf_counter()
        try:
            result = adapter.run_turn(session_state, message)
            samples.append(LoadSample(
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=True,
                cost_usd=result.cost_usd,
            ))
        except Exception as exc:  # noqa: BLE001 -- any adapter failure is a sample, not a crash
            samples.append(LoadSample(
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error_detail=f"{type(exc).__name__}: {exc}"[:500],
            ))

    return samples


def run_load_test(load_run_id: uuid.UUID) -> LoadTestResult:
    """DB-backed orchestrator. Resolves the LoadRun's configuration, builds ONE
    adapter shared across all virtual-user threads (HTTPAdapter's underlying
    httpx.Client is thread-safe for concurrent requests; LocalPythonAdapter is a
    plain function reference, safe to call concurrently as long as each thread
    owns its own session_state, which _virtual_user() guarantees), fires
    `concurrency` concurrent virtual users for `duration_seconds`, computes the
    aggregate result, and persists both the aggregate (Postgres) and the raw
    samples (ClickHouse).
    """
    db = SessionLocal()
    try:
        load_run = db.get(LoadRun, load_run_id)
        if load_run is None:
            raise ValueError(f"load_run {load_run_id} not found")

        agent_version = db.get(AgentVersion, load_run.agent_version_id)
        if agent_version is None:
            raise ValueError(f"agent_version {load_run.agent_version_id} not found")

        load_run.status = "running"
        from datetime import datetime
        load_run.started_at = datetime.utcnow()
        db.commit()

        adapter = build_adapter(agent_version.entrypoint)

        wall_start = time.perf_counter()
        stop_at = time.monotonic() + load_run.duration_seconds

        all_samples: list[LoadSample] = []
        with ThreadPoolExecutor(max_workers=load_run.concurrency) as pool:
            futures = [
                pool.submit(_virtual_user, adapter, load_run.message, stop_at)
                for _ in range(load_run.concurrency)
            ]
            for future in as_completed(futures):
                all_samples.extend(future.result())

        actual_duration = time.perf_counter() - wall_start
        result = _compute_load_stats(all_samples, actual_duration)

        load_run.status = "completed"
        load_run.completed_at = datetime.utcnow()
        load_run.total_requests = result.total_requests
        load_run.successful_requests = result.successful_requests
        load_run.p50_latency_ms = result.p50_latency_ms
        load_run.p95_latency_ms = result.p95_latency_ms
        load_run.p99_latency_ms = result.p99_latency_ms
        load_run.error_rate = result.error_rate
        load_run.total_cost_usd = result.total_cost_usd
        load_run.cost_per_hour_usd = result.cost_per_hour_usd
        load_run.throughput_rps = result.throughput_rps
        db.commit()

        emit_load_samples(
            load_run_id=load_run.id,
            tenant_id=load_run.tenant_id,
            samples=[
                {
                    "latency_ms": s.latency_ms, "success": s.success,
                    "cost_usd": s.cost_usd, "error_detail": s.error_detail,
                }
                for s in all_samples
            ],
        )

        return result
    except Exception as exc:
        db.rollback()
        failed_run = db.get(LoadRun, load_run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.error = str(exc)
            db.commit()
        raise
    finally:
        db.close()
