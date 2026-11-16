"""
Load test engine. Runs `concurrency` virtual users for `duration_seconds`, each looping
over the suite's cases (one full scripted session per request) through the same
AgentAdapter the eval engine uses, and records latency percentiles, error rate,
throughput and projected cost/hour.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from apps.api.core.db import SessionLocal
from apps.api.models import AgentVersion, EvalCase, LoadRun
from apps.api.services.adapters.local_python import LocalPythonAdapter

BUCKET_SECONDS = 5


def run_load(load_run_id: uuid.UUID) -> None:
    db: Session = SessionLocal()
    try:
        load = db.get(LoadRun, load_run_id)
        if load is None:
            raise ValueError(f"load_run {load_run_id} not found")
        load.status = "running"
        db.commit()

        version = db.get(AgentVersion, load.agent_version_id)
        cases = db.query(EvalCase).filter(EvalCase.suite_id == load.suite_id).all()
        if not cases:
            raise ValueError("suite has no cases")
        scripted = [[t["content"] for t in c.turns if t["role"] == "user"] for c in cases]
        adapter = LocalPythonAdapter(version.entrypoint)

        samples: list[tuple[float, float, bool, float]] = []  # (t_offset, latency_ms, ok, cost)
        lock = threading.Lock()
        start = time.monotonic()
        deadline = start + load.duration_seconds

        def worker(idx: int) -> None:
            n = idx
            while time.monotonic() < deadline:
                turns, state = scripted[n % len(scripted)], {}
                n += 1
                t0, ok, cost = time.monotonic(), True, 0.0
                try:
                    for msg in turns:
                        cost += adapter.run_turn(state, msg).cost_usd
                except Exception:
                    ok = False
                latency = (time.monotonic() - t0) * 1000
                with lock:
                    samples.append((t0 - start, latency, ok, cost))

        with ThreadPoolExecutor(max_workers=load.concurrency) as pool:
            list(pool.map(worker, range(load.concurrency)))

        elapsed = max(time.monotonic() - start, 1e-6)
        lat = np.array([s[1] for s in samples]) if samples else np.array([0.0])
        total_cost = sum(s[3] for s in samples)

        series = []
        for b in range(int(np.ceil(elapsed / BUCKET_SECONDS))):
            lo, hi = b * BUCKET_SECONDS, (b + 1) * BUCKET_SECONDS
            bucket = [s[1] for s in samples if lo <= s[0] < hi]
            if bucket:
                series.append(
                    {"t": lo, "p95_ms": round(float(np.percentile(bucket, 95)), 1),
                     "rps": round(len(bucket) / BUCKET_SECONDS, 2)}
                )

        load.total_requests = len(samples)
        load.p50_ms = round(float(np.percentile(lat, 50)), 1)
        load.p95_ms = round(float(np.percentile(lat, 95)), 1)
        load.p99_ms = round(float(np.percentile(lat, 99)), 1)
        load.error_rate = round(sum(1 for s in samples if not s[2]) / max(len(samples), 1), 4)
        load.throughput_rps = round(len(samples) / elapsed, 2)
        load.cost_per_hour_usd = round(total_cost / elapsed * 3600, 4)
        load.latency_series = series
        load.status = "completed"
        load.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        failed = db.get(LoadRun, load_run_id)
        if failed is not None:
            failed.status = "failed"
            db.commit()
        raise
    finally:
        db.close()
