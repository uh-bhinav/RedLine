"""
Worker -- long-running process.

Polls the `jobs` table, claims one job via SKIP LOCKED (PostgresJobQueue.claim_next_job)
and dispatches on job_type:
    eval.requested  -> eval_engine.run_eval(eval_run_id)
    diff.requested  -> diff_engine.run_diff(diff_run_id)
    load.requested  -> load_engine.run_load(load_run_id)

Reliability model:
  * each job runs in a 'spawn' child process, so a hang/crash/OOM cannot take the worker down
  * the parent heartbeats the job every HEARTBEAT_SECONDS and kills the child after
    JOB_TIMEOUT_SECONDS
  * failures go through fail_or_retry (exponential backoff, max_attempts)
  * a reaper requeues/fails in_progress jobs whose heartbeat went stale (crashed workers)
  * SIGTERM/SIGINT stop claiming; the current job is allowed to finish

Run this as a separate, long-lived process alongside the API:
    python -m apps.api.workers.eval_worker
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import signal
import time
import traceback
import uuid

from apps.api.core.config import get_settings
from apps.api.core.db import SessionLocal
from apps.api.core.jobqueue import ClaimedJob, PostgresJobQueue
from apps.api.models import DiffCaseResult, DiffRun, EvalCaseResult, EvalRun, LoadRun

logger = logging.getLogger("redline.worker")

HEARTBEAT_SECONDS = 10
REAP_INTERVAL_SECONDS = 30
MAX_ERROR_CHARS = 4000

# job_type -> (payload key, domain model)
JOB_TYPES = {
    "eval.requested": ("eval_run_id", EvalRun),
    "diff.requested": ("diff_run_id", DiffRun),
    "load.requested": ("load_run_id", LoadRun),
}

_stop_requested = False


def _log(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))


# --------------------------------------------------------------------------- handlers
# Top-level, importable functions: required so the 'spawn' child (Windows) can resolve them.
# Each is safe to run twice: a completed domain row is a no-op, and partial results from a
# previous interrupted attempt are cleared before re-running.

def handle_eval(eval_run_id: uuid.UUID) -> None:
    from apps.api.services import eval_engine

    db = SessionLocal()
    try:
        run = db.get(EvalRun, eval_run_id)
        if run is not None and run.status == "completed":
            return
        db.query(EvalCaseResult).filter(EvalCaseResult.eval_run_id == eval_run_id).delete()
        db.commit()
    finally:
        db.close()
    eval_engine.run_eval(eval_run_id)


def handle_diff(diff_run_id: uuid.UUID) -> None:
    from apps.api.services import diff_engine

    db = SessionLocal()
    try:
        diff = db.get(DiffRun, diff_run_id)
        if diff is not None and diff.status == "completed":
            return
        db.query(DiffCaseResult).filter(DiffCaseResult.diff_run_id == diff_run_id).delete()
        db.commit()
    finally:
        db.close()
    diff_engine.run_diff(diff_run_id)


def handle_load(load_run_id: uuid.UUID) -> None:
    from apps.api.services import load_engine

    db = SessionLocal()
    try:
        load = db.get(LoadRun, load_run_id)
        if load is not None and load.status == "completed":
            return
    finally:
        db.close()
    load_engine.run_load(load_run_id)


HANDLERS = {
    "eval.requested": handle_eval,
    "diff.requested": handle_diff,
    "load.requested": handle_load,
}


def _child_main(job_type: str, target_id: str, conn) -> None:
    """Entry point of the spawned child. Reports (ok, error_text) over the pipe."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl-C is handled by the parent only
    try:
        HANDLERS[job_type](uuid.UUID(target_id))
        conn.send((True, None))
    except BaseException as exc:  # noqa: BLE001
        conn.send((False, f"{exc}\n{traceback.format_exc()}"[:MAX_ERROR_CHARS]))
        raise SystemExit(1)
    finally:
        conn.close()


# --------------------------------------------------------------------------- domain sync

def sync_domain_status(job_type: str, payload: dict, job_status: str) -> None:
    """After a job failed/retried, reflect it on the EvalRun/DiffRun/LoadRun row:
    failed if no retries are left, back to pending if the job will be retried."""
    spec = JOB_TYPES.get(job_type)
    if spec is None:
        return
    key, model = spec
    try:
        target_id = uuid.UUID(payload[key])
    except (KeyError, ValueError, TypeError):
        return
    db = SessionLocal()
    try:
        row = db.get(model, target_id)
        if row is not None and row.status != "completed":
            row.status = "failed" if job_status == "failed" else "pending"
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("could not sync domain status for %s", target_id)
    finally:
        db.close()


# --------------------------------------------------------------------------- worker

def _signal_handler(signum, _frame) -> None:
    global _stop_requested
    _stop_requested = True
    _log("shutdown_requested", signal=signum)


def _heartbeat(job_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        PostgresJobQueue(db).heartbeat(job_id)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("heartbeat failed for %s", job_id)
    finally:
        db.close()


def reap_once(stale_seconds: int) -> int:
    db = SessionLocal()
    try:
        reaped = PostgresJobQueue(db).reap_stale(stale_seconds, job_types=list(JOB_TYPES))
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("reaper failed")
        return 0
    finally:
        db.close()
    for job in reaped:
        _log("job_reaped", job_id=job.id, job_type=job.job_type, new_status=job.status)
        sync_domain_status(job.job_type, job.payload, job.status)
    return len(reaped)


def _run_job_in_child(claimed: ClaimedJob, timeout: float, stale_seconds: int, state: dict) -> tuple[bool, str | None]:
    ctx = multiprocessing.get_context("spawn")
    key, _model = JOB_TYPES[claimed.job_type]
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_main, args=(claimed.job_type, claimed.payload[key], child_conn), daemon=True)
    started = time.monotonic()
    proc.start()
    child_conn.close()
    last_beat = started
    try:
        while proc.is_alive():
            proc.join(timeout=1)
            now = time.monotonic()
            if now - last_beat >= HEARTBEAT_SECONDS:
                _heartbeat(claimed.id)
                last_beat = now
            if now - state["last_reap"] >= REAP_INTERVAL_SECONDS:
                reap_once(stale_seconds)
                state["last_reap"] = now
            if proc.is_alive() and now - started > timeout:
                proc.terminate()
                proc.join(5)
                if proc.is_alive():
                    proc.kill()
                    proc.join()
                return False, f"job timed out after {timeout:.0f}s and was killed"
        try:
            # A child that died without reporting raises here: BrokenPipeError/OSError on
            # Windows, EOFError on POSIX. Either way it means "no result was sent".
            if parent_conn.poll():
                ok, err = parent_conn.recv()
                return ok, err
        except (EOFError, OSError):
            pass
        return False, f"child exited unexpectedly with code {proc.exitcode}"
    finally:
        parent_conn.close()


def process_job(queue: PostgresJobQueue, claimed: ClaimedJob, timeout: float, stale_seconds: int, state: dict) -> None:
    t0 = time.monotonic()
    base = {"job_id": claimed.id, "job_type": claimed.job_type, "attempt": claimed.attempt}
    _log("job_started", **base)
    try:
        ok, err = _run_job_in_child(claimed, timeout, stale_seconds, state)
    except Exception as exc:  # noqa: BLE001  (e.g. bad payload) -- never kill the worker
        ok, err = False, f"{exc}\n{traceback.format_exc()}"[:MAX_ERROR_CHARS]
    duration_ms = int((time.monotonic() - t0) * 1000)
    if ok:
        key, _ = JOB_TYPES[claimed.job_type]
        queue.mark_completed(claimed.id, {key: claimed.payload[key]})
        _log("job_completed", duration_ms=duration_ms, **base)
        return
    status = queue.fail_or_retry(claimed.id, err or "unknown error")
    sync_domain_status(claimed.job_type, claimed.payload, status)
    _log("job_failed" if status == "failed" else "job_retry_scheduled",
         duration_ms=duration_ms, new_status=status, error=(err or "")[:300], **base)


def run_worker_loop() -> None:
    settings = get_settings()
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    _log("worker_started", job_types=sorted(JOB_TYPES), poll_seconds=settings.worker_poll_seconds,
         timeout_seconds=settings.job_timeout_seconds, stale_seconds=settings.job_stale_seconds)
    state = {"last_reap": 0.0}
    while not _stop_requested:
        now = time.monotonic()
        if now - state["last_reap"] >= REAP_INTERVAL_SECONDS:
            reap_once(settings.job_stale_seconds)
            state["last_reap"] = now

        db = SessionLocal()
        try:
            queue = PostgresJobQueue(db)
            claimed = queue.claim_next_job(job_types=list(JOB_TYPES))
            if claimed is None:
                db.close()
                time.sleep(settings.worker_poll_seconds)
                continue
            process_job(queue, claimed, settings.job_timeout_seconds, settings.job_stale_seconds, state)
        except Exception:  # noqa: BLE001
            logger.exception("worker loop error")
            time.sleep(settings.worker_poll_seconds)
        finally:
            db.close()
    _log("worker_stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_worker_loop()
