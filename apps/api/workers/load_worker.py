"""
Load-test worker (Phase 4 Section 5) -- consumes `load.requested` from Redpanda.

Structurally identical to eval_worker_v2.py (same DistributedLock re-delivery
guard, same commit-offset-after-processing rule), because the JobQueue STABLE
CONTRACT and the Redpanda consumer pattern don't care what kind of job they're
carrying. The only difference is the topic subscribed to and which engine gets
called -- this is the actual point of foundational doc §9.3's "separate worker
pools by resource profile" claim: a load runner's profile (many concurrent
outbound HTTP requests for the duration of a run) is nothing like an eval
runner's (one case at a time), so it gets its OWN process, OWN consumer group,
and (in the Helm chart) its OWN KEDA ScaledObject and replica count -- entirely
independent of eval-worker scaling decisions.

Run this as a separate, long-lived process alongside the API:
    python -m apps.api.workers.load_worker
"""
import traceback
import uuid

from apps.api.core.config import get_settings
from apps.api.core.db import SessionLocal
from apps.api.core.redis_client import DistributedLock
from apps.api.core.redpanda_queue import RedpandaEvalWorker
from apps.api.services import load_engine

POLL_TIMEOUT_SECONDS = 2.0


def run_worker_loop() -> None:
    settings = get_settings()
    worker = RedpandaEvalWorker(group_id="load-worker", topics=[settings.topic_load_requested])
    lock = DistributedLock(ttl_seconds=1800)  # load tests can run for minutes
    print(f"load_worker started (Redpanda consumer, group=load-worker, "
          f"topic={settings.topic_load_requested})")

    try:
        while True:
            claimed = worker.consume_one(timeout_seconds=POLL_TIMEOUT_SECONDS)
            if claimed is None:
                continue

            job_id = claimed.id
            load_run_id_str = claimed.payload.get("load_run_id")

            if load_run_id_str is None:
                print(f"[skip] job {job_id}: missing load_run_id in payload")
                worker.commit_offset()
                continue

            if not lock.acquire(job_id):
                print(f"[skip] job {job_id}: lock held by another worker (re-delivery), committing offset")
                worker.commit_offset()
                continue

            print(f"claimed job {job_id} (load_run_id={load_run_id_str})")
            db = SessionLocal()
            try:
                load_run_id = uuid.UUID(load_run_id_str)
                worker.update_status(job_id, "in_progress", db=db)
                load_engine.run_load_test(load_run_id)
                worker.update_status(job_id, "completed", result={"load_run_id": load_run_id_str}, db=db)
                worker.commit_offset()
                print(f"job {job_id} completed")
            except Exception as exc:
                error_text = f"{exc}\n{traceback.format_exc()}"
                dead_lettered = worker.retry_or_dead_letter(claimed, error_text)
                final_status = "failed" if dead_lettered else "pending"
                worker.update_status(job_id, final_status, error=error_text, db=db)
                worker.commit_offset()
                tag = "DEAD-LETTERED" if dead_lettered else f"retrying (attempt {claimed.retry_count + 1})"
                print(f"job {job_id} FAILED, {tag}: {exc}")
            finally:
                lock.release(job_id)
                db.close()
    finally:
        worker.close()


if __name__ == "__main__":
    run_worker_loop()
