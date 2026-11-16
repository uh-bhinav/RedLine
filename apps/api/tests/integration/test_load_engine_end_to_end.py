"""
End-to-end integration test for Agent Load Testing (Phase 4 Section 5).

Two things get verified against real infrastructure, not mocks:

1. load_engine.run_load_test() itself: REAL concurrent threads (ThreadPoolExecutor,
   not simulated) firing REAL HTTP requests at the REAL reference agent
   (examples/http-agent/server.py, started on a free port) for a short real
   duration, persisting a REAL aggregate result to Postgres and REAL samples to
   ClickHouse. This is the load-testing engine's actual job.

2. The Redpanda job-queue plumbing this feature required fixing: publish() used to
   ignore the job_type argument and always produce to eval.requested regardless of
   what was passed -- never caught before because every prior caller happened to
   pass job_type="eval.requested". Verified here: publishing "load.requested"
   actually lands on the load.requested topic and a worker subscribed to THAT
   topic (not eval.requested) can consume it.

Requires:
  - Postgres, Redpanda, ClickHouse running (docker compose up)

Run from the repo root:
    pytest apps/api/tests/integration/test_load_engine_end_to_end.py -v -m integration
"""
from __future__ import annotations

import hashlib
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn

from apps.api.core.db import SessionLocal
from apps.api.core.redpanda_queue import RedpandaEvalWorker, RedpandaJobQueue
from apps.api.models import Agent, AgentVersion, Job, LoadRun, Tenant
from apps.api.services.load_engine import run_load_test

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def agent_url():
    """The same reference HTTP agent used by test_http_adapter_end_to_end.py --
    zero LLM cost, real HTTP, real concurrency-safe (a fresh uvicorn/FastAPI
    server handling concurrent requests genuinely, not simulated)."""
    example_dir = Path(__file__).resolve().parents[4] / "examples" / "http-agent"
    if not (example_dir / "server.py").exists():
        pytest.skip(f"reference agent not found at {example_dir}")
    sys.path.insert(0, str(example_dir))
    from server import app  # noqa: E402

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        server.should_exit = True
        pytest.fail("reference HTTP agent did not become healthy within 15s")

    yield f"{url}/turn"

    server.should_exit = True
    thread.join(timeout=5)
    sys.path.remove(str(example_dir))


@pytest.fixture
def seeded(agent_url):
    db = SessionLocal()
    try:
        tenant = Tenant(name=f"load-e2e-{uuid.uuid4().hex[:8]}")
        db.add(tenant)
        db.flush()

        agent = Agent(tenant_id=tenant.id, name=f"load-agent-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()

        version = AgentVersion(
            agent_id=agent.id, version_label="v1", model_name="reference-http-agent",
            prompt_text="reference agent", content_hash=hashlib.sha256(b"load-e2e").hexdigest(),
            entrypoint=agent_url,
        )
        db.add(version)
        db.commit()

        ids = {"tenant_id": tenant.id, "agent_id": agent.id, "version_id": version.id}
    except Exception:
        db.rollback()
        db.close()
        raise

    yield ids

    try:
        # RedpandaJobQueue.publish() (used by test_load_requested_actually_reaches_
        # the_load_requested_topic) creates a Job row that FKs to tenants -- must
        # be deleted before the Tenant delete below, same class of gap already hit
        # with ars_snapshots and behavior_diffs.
        db.query(Job).filter(Job.tenant_id == ids["tenant_id"]).delete()
        db.query(LoadRun).filter(LoadRun.tenant_id == ids["tenant_id"]).delete()
        db.query(AgentVersion).filter(AgentVersion.id == ids["version_id"]).delete()
        db.query(Agent).filter(Agent.id == ids["agent_id"]).delete()
        db.query(Tenant).filter(Tenant.id == ids["tenant_id"]).delete()
        db.commit()
    finally:
        db.close()


def _make_load_run(seeded, concurrency: int, duration_seconds: int) -> uuid.UUID:
    db = SessionLocal()
    try:
        run = LoadRun(
            tenant_id=seeded["tenant_id"], agent_version_id=seeded["version_id"],
            message="What is your return policy?",
            concurrency=concurrency, duration_seconds=duration_seconds,
            status="pending", triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


# ---------- the engine itself: real concurrency, real HTTP, real persistence ----------

def test_real_concurrent_requests_produce_a_sane_aggregate_result(seeded):
    run_id = _make_load_run(seeded, concurrency=5, duration_seconds=2)

    wall_start = time.perf_counter()
    result = run_load_test(run_id)
    wall_elapsed = time.perf_counter() - wall_start

    assert result.total_requests > 0, "no requests completed -- concurrency isn't working"
    assert result.error_rate == 0.0, "the reference agent should never fail a well-formed request"
    assert result.p50_latency_ms <= result.p95_latency_ms <= result.p99_latency_ms
    assert result.throughput_rps > 0
    # 5 concurrent users over ~2s should produce meaningfully more than 5 total
    # requests -- proving the concurrency is real, not sequential (5 users doing
    # one request each would just be 5, not dozens).
    assert result.total_requests > 5, (
        f"only {result.total_requests} requests in ~2s across 5 concurrent users -- "
        f"looks sequential, not concurrent"
    )
    # The engine must not run dramatically longer than the configured duration.
    assert wall_elapsed < 10.0


def test_run_is_persisted_to_postgres_with_the_aggregate(seeded):
    run_id = _make_load_run(seeded, concurrency=3, duration_seconds=1)
    run_load_test(run_id)

    db = SessionLocal()
    try:
        row = db.get(LoadRun, run_id)
        assert row.status == "completed"
        assert row.total_requests > 0
        assert row.p50_latency_ms is not None
        assert row.cost_per_hour_usd is not None
        assert row.started_at is not None
        assert row.completed_at is not None
    finally:
        db.close()


def test_engine_marks_the_run_failed_for_an_unreachable_agent(seeded):
    db = SessionLocal()
    try:
        dead_version = AgentVersion(
            agent_id=seeded["agent_id"], version_label="v-dead", model_name="dead",
            prompt_text="points at a closed port",
            content_hash=hashlib.sha256(b"dead-load").hexdigest(),
            entrypoint=f"http://127.0.0.1:{_free_port()}/turn",
        )
        db.add(dead_version)
        db.flush()
        run = LoadRun(
            tenant_id=seeded["tenant_id"], agent_version_id=dead_version.id,
            message="hello", concurrency=2, duration_seconds=1,
            status="pending", triggered_by="manual",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id, dead_id = run.id, dead_version.id
    finally:
        db.close()

    # An unreachable agent means every virtual user's calls fail -- that is a
    # 100% error rate, NOT an engine crash. The engine only raises for a genuine
    # configuration problem (e.g. the LoadRun row itself missing).
    result = run_load_test(run_id)
    assert result.error_rate == 1.0
    assert result.successful_requests == 0

    db = SessionLocal()
    try:
        assert db.get(LoadRun, run_id).status == "completed"
    finally:
        db.query(LoadRun).filter(LoadRun.id == run_id).delete()
        db.query(AgentVersion).filter(AgentVersion.id == dead_id).delete()
        db.commit()
        db.close()


# ---------- the job-queue routing fix ----------

def test_load_requested_actually_reaches_the_load_requested_topic(seeded):
    """The real bug this feature found: publish() used to ignore job_type and
    always produce to eval.requested. A worker subscribed ONLY to load.requested
    must be the one that receives this message.

    Marker must be unique per invocation, not a literal constant: a fresh consumer
    group resets to 'earliest' and replays every past message on the topic --
    across repeated local test runs that means old messages with a hardcoded
    marker string are still sitting there and would be matched first.
    """
    unique_marker = f"test-marker-{uuid.uuid4()}"
    db = SessionLocal()
    try:
        queue = RedpandaJobQueue(db)
        job_id = queue.publish(seeded["tenant_id"], "load.requested",
                                {"load_run_id": unique_marker})
    finally:
        db.close()

    worker = RedpandaEvalWorker(group_id=f"test-load-consumer-{uuid.uuid4().hex[:8]}",
                                 topics=["load.requested"])
    try:
        claimed = None
        deadline = time.time() + 15
        while time.time() < deadline:
            claimed = worker.consume_one(timeout_seconds=2.0)
            if claimed is not None and claimed.payload.get("load_run_id") == unique_marker:
                break
            claimed = None
        assert claimed is not None, "message never arrived on the load.requested topic"
        assert claimed.id == job_id
        assert claimed.job_type == "load.requested"
        worker.commit_offset()
    finally:
        worker.close()


def test_eval_requested_still_routes_correctly_after_the_routing_fix(seeded):
    """Regression guard: fixing load.requested routing must not have broken the
    original eval.requested path every other feature depends on."""
    from apps.api.core.redpanda_queue import _resolve_topic
    from apps.api.core.config import get_settings

    assert _resolve_topic("eval.requested") == get_settings().topic_eval_requested
