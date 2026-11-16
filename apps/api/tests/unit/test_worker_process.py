"""eval_worker process paths: timeout kill, handler errors, abrupt child death, success,
graceful shutdown and reap_once domain sync. Needs the real test Postgres.

Children are real 'spawn' processes. Their handlers are replaced via a test-only sitecustomize
(see tests/_worker_site) selected with REDLINE_TEST_WORKER_MODE.
"""
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from apps.api.core.db import SessionLocal
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.models import DiffRun, EvalRun, Job, LoadRun
from apps.api.workers import eval_worker
from seeding import seed_agent, seed_run, seed_suite

SITE_DIR = str(Path(__file__).resolve().parents[1] / "_worker_site")
MODELS = {"eval.requested": EvalRun, "diff.requested": DiffRun, "load.requested": LoadRun}
ALL_TYPES = list(MODELS)
OK_TIMEOUT = 60  # generous: child start-up (imports) is slow on Windows


@pytest.fixture()
def child_mode(monkeypatch):
    def _set(mode: str) -> None:
        monkeypatch.setenv("REDLINE_TEST_WORKER_MODE", mode)
        existing = os.environ.get("PYTHONPATH")
        monkeypatch.setenv("PYTHONPATH", SITE_DIR + (os.pathsep + existing if existing else ""))

    return _set


@pytest.fixture()
def world(make_tenant):
    """Factory for (queue, claimed job, domain id) with the domain row 'running'."""
    tenant = make_tenant("worker-proc-tenant")
    db = SessionLocal()
    db.info["tenant_id"] = tenant.id
    agent = seed_agent(db, tenant)
    suite = seed_suite(db, agent, n_cases=1)
    version = agent.versions[0]
    queue = PostgresJobQueue(db)

    def make(job_type: str, status: str = "running", attempts_exhausted: bool = False):
        run_a = seed_run(db, tenant, version, suite, [], status="completed")
        run_b = seed_run(db, tenant, version, suite, [], status="completed")
        if job_type == "eval.requested":
            row = EvalRun(tenant_id=tenant.id, agent_version_id=version.id, suite_id=suite.id,
                          status=status, triggered_by="manual")
        elif job_type == "diff.requested":
            row = DiffRun(tenant_id=tenant.id, agent_id=agent.id, suite_id=suite.id,
                          run_a_id=run_a.id, run_b_id=run_b.id, status=status)
        else:
            row = LoadRun(tenant_id=tenant.id, agent_version_id=version.id, suite_id=suite.id,
                          concurrency=1, duration_seconds=1, status=status)
        db.add(row)
        db.commit()
        key = eval_worker.JOB_TYPES[job_type][0]
        queue.publish(tenant.id, job_type, {key: str(row.id)})
        claimed = queue.claim_next_job(job_types=[job_type])
        assert claimed is not None and claimed.attempt == 1
        if attempts_exhausted:
            db.execute(text("UPDATE jobs SET attempts = max_attempts WHERE id = :i"), {"i": str(claimed.id)})
            db.commit()
        return claimed, row.id

    yield SimpleNamespace_(queue=queue, make=make, db=db, tenant=tenant, agent=agent,
                           suite=suite, version=version)
    db.rollback()
    db.close()


class SimpleNamespace_:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _job(db, job_id) -> Job:
    db.expire_all()
    return db.get(Job, job_id)


def _domain_status(job_type: str, row_id) -> str:
    with SessionLocal() as s:
        return s.get(MODELS[job_type], row_id).status


def _run(world, claimed, timeout=OK_TIMEOUT):
    state = {"last_reap": 1e18}  # never reap inside the child wait loop
    eval_worker.process_job(world.queue, claimed, timeout, 3600, state)


# ---------------------------------------------------------------- (1) timeout


@pytest.mark.parametrize("job_type", ALL_TYPES)
def test_hung_job_is_killed_then_retried_and_domain_reset_to_pending(world, child_mode, job_type):
    child_mode("hang")
    claimed, row_id = world.make(job_type)
    _run(world, claimed, timeout=2)
    job = _job(world.db, claimed.id)
    assert job.status == "pending" and job.attempts == 1 < job.max_attempts
    assert "timed out after 2s and was killed" in job.error
    assert _domain_status(job_type, row_id) == "pending"


@pytest.mark.parametrize("job_type", ALL_TYPES)
def test_hung_job_with_attempts_exhausted_fails_job_and_domain(world, child_mode, job_type):
    child_mode("hang")
    claimed, row_id = world.make(job_type, attempts_exhausted=True)
    _run(world, claimed, timeout=2)
    job = _job(world.db, claimed.id)
    assert job.status == "failed" and "timed out" in job.error
    assert _domain_status(job_type, row_id) == "failed"


# ---------------------------------------------------------------- (2) handler raises


def test_raising_handler_captures_error_text_and_retries(world, child_mode):
    child_mode("raise")
    claimed, row_id = world.make("eval.requested")
    _run(world, claimed)
    job = _job(world.db, claimed.id)
    assert job.status == "pending"
    assert "handler exploded: kaboom-marker" in job.error
    assert "Traceback" in job.error and "RuntimeError" in job.error
    assert _domain_status("eval.requested", row_id) == "pending"


def test_raising_handler_fails_when_attempts_exhausted(world, child_mode):
    child_mode("raise")
    claimed, row_id = world.make("diff.requested", attempts_exhausted=True)
    _run(world, claimed)
    job = _job(world.db, claimed.id)
    assert job.status == "failed" and "kaboom-marker" in job.error
    assert _domain_status("diff.requested", row_id) == "failed"


# ---------------------------------------------------------------- (3) abrupt exit


def test_child_exiting_abruptly_is_retried_and_domain_reset(world, child_mode):
    child_mode("exit")
    claimed, row_id = world.make("load.requested")
    _run(world, claimed)
    job = _job(world.db, claimed.id)
    assert job.status == "pending" and job.error
    assert _domain_status("load.requested", row_id) == "pending"


def test_child_exiting_abruptly_reports_unexpected_exit_message(world, child_mode):
    child_mode("exit")
    claimed, _ = world.make("load.requested")
    _run(world, claimed)
    assert "child exited unexpectedly with code 1" in _job(world.db, claimed.id).error


def test_child_exiting_abruptly_fails_when_attempts_exhausted(world, child_mode):
    child_mode("exit")
    claimed, row_id = world.make("load.requested", attempts_exhausted=True)
    _run(world, claimed)
    assert _job(world.db, claimed.id).status == "failed"
    assert _domain_status("load.requested", row_id) == "failed"


# ---------------------------------------------------------------- (4) success


def test_success_marks_job_completed_and_leaves_domain_row_alone(world, child_mode):
    child_mode("ok")
    claimed, row_id = world.make("eval.requested")
    _run(world, claimed)
    job = _job(world.db, claimed.id)
    assert job.status == "completed" and job.error is None
    assert job.result == {"eval_run_id": str(row_id)}
    assert _domain_status("eval.requested", row_id) == "running"  # only the engine moves it


def test_unresolvable_payload_does_not_kill_worker(world):
    """A job whose payload lacks the target key fails through fail_or_retry (no child needed)."""
    claimed, _ = world.make("eval.requested")
    bad = claimed.model_copy(update={"payload": {}})
    _run(world, bad)
    job = _job(world.db, claimed.id)
    assert job.status == "pending" and "eval_run_id" in job.error


# ---------------------------------------------------------------- (5) graceful shutdown


@pytest.fixture()
def loop_env(monkeypatch):
    monkeypatch.setattr(eval_worker, "_stop_requested", False)
    monkeypatch.setattr(eval_worker, "REAP_INTERVAL_SECONDS", 10**9)
    saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    yield
    for s, h in saved.items():
        signal.signal(s, h)


def _publish_two(world):
    key = "eval_run_id"
    ids = []
    for _ in range(2):
        ids.append(world.queue.publish(world.tenant.id, "eval.requested", {key: "00000000-0000-0000-0000-000000000001"}))
    return ids


def test_signal_handler_sets_stop_flag(monkeypatch):
    monkeypatch.setattr(eval_worker, "_stop_requested", False)
    eval_worker._signal_handler(signal.SIGTERM, None)
    assert eval_worker._stop_requested is True


def test_signal_during_job_lets_it_finish_but_claims_no_more(world, loop_env, monkeypatch):
    first, second = _publish_two(world)
    processed = []

    def fake_process(queue, claimed, timeout, stale, state):
        processed.append(claimed.id)
        signal.raise_signal(signal.SIGTERM)  # goes through the handler run_worker_loop installed
        queue.mark_completed(claimed.id, {"done": True})

    monkeypatch.setattr(eval_worker, "process_job", fake_process)
    eval_worker.run_worker_loop()
    assert processed == [first]
    assert _job(world.db, first).status == "completed"
    assert _job(world.db, second).status == "pending"
    assert eval_worker._stop_requested is True


def test_stop_flag_set_before_loop_claims_nothing(world, loop_env, monkeypatch):
    ids = _publish_two(world)
    monkeypatch.setattr(eval_worker, "_stop_requested", True)
    monkeypatch.setattr(eval_worker, "process_job", lambda *a, **k: pytest.fail("claimed a job"))
    eval_worker.run_worker_loop()
    assert all(_job(world.db, i).status == "pending" for i in ids)


# ---------------------------------------------------------------- (6) reap_once


def _age(world, job_id, seconds=500):
    world.db.execute(
        text("UPDATE jobs SET heartbeat_at = now() - make_interval(secs => :s) WHERE id = :i"),
        {"s": seconds, "i": str(job_id)},
    )
    world.db.commit()


@pytest.mark.parametrize("job_type", ALL_TYPES)
def test_reap_once_requeues_stale_job_and_resets_domain_row(world, job_type):
    claimed, row_id = world.make(job_type)
    assert eval_worker.reap_once(60) == 0  # fresh heartbeat
    assert _domain_status(job_type, row_id) == "running"
    _age(world, claimed.id)
    assert eval_worker.reap_once(60) == 1
    assert _job(world.db, claimed.id).status == "pending"
    assert _domain_status(job_type, row_id) == "pending"


@pytest.mark.parametrize("job_type", ALL_TYPES)
def test_reap_once_fails_exhausted_job_and_domain_row(world, job_type):
    claimed, row_id = world.make(job_type, attempts_exhausted=True)
    _age(world, claimed.id)
    assert eval_worker.reap_once(60) == 1
    assert _job(world.db, claimed.id).status == "failed"
    assert _domain_status(job_type, row_id) == "failed"


def test_reap_once_does_not_overwrite_completed_domain_row(world):
    claimed, row_id = world.make("eval.requested", status="completed")
    _age(world, claimed.id)
    assert eval_worker.reap_once(60) == 1
    assert _domain_status("eval.requested", row_id) == "completed"


def test_sync_domain_status_ignores_unknown_type_and_bad_payload(world):
    eval_worker.sync_domain_status("nope", {"eval_run_id": "x"}, "failed")
    eval_worker.sync_domain_status("eval.requested", {}, "failed")
    eval_worker.sync_domain_status("eval.requested", {"eval_run_id": "not-a-uuid"}, "failed")
    eval_worker.sync_domain_status("eval.requested", {"eval_run_id": "00000000-0000-0000-0000-000000000009"}, "failed")
