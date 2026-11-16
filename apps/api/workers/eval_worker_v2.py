"""
Eval worker (Phase 2) -- consumes from Redpanda instead of polling the Postgres
`jobs` table.

Key behavioral differences from the Phase 1 worker:
  - Message comes from Redpanda via consumer group assignment (broker handles
    load distribution across workers automatically)
  - Offset is committed AFTER processing, not before -- ensures at-least-once
    delivery semantics (a crash during processing causes re-delivery)
  - DistributedLock (Redis) prevents the at-least-once re-delivery from causing
    duplicate eval runs if a message is re-delivered to a different worker

Run this as a separate, long-lived process alongside the API:
    python -m apps.api.workers.eval_worker_v2
"""
import traceback
import uuid

from apps.api.core.db import SessionLocal
from apps.api.core.redis_client import DistributedLock
from apps.api.core.redpanda_queue import RedpandaEvalWorker
from apps.api.services import eval_engine

POLL_TIMEOUT_SECONDS = 2.0


def run_worker_loop() -> None:
    worker = RedpandaEvalWorker(group_id="eval-worker")
    lock = DistributedLock(ttl_seconds=600)
    print("eval_worker_v2 started (Redpanda consumer, group=eval-worker)")

    try:
        while True:
            claimed = worker.consume_one(timeout_seconds=POLL_TIMEOUT_SECONDS)
            if claimed is None:
                continue  # poll timeout, no messages -- loop immediately

            job_id = claimed.id
            eval_run_id_str = claimed.payload.get("eval_run_id")

            if eval_run_id_str is None:
                print(f"[skip] job {job_id}: missing eval_run_id in payload")
                worker.commit_offset()
                continue

            # DistributedLock: if a previous worker crashed and this message was
            # re-delivered, the lock prevents us from running the same eval twice.
            if not lock.acquire(job_id):
                print(f"[skip] job {job_id}: lock held by another worker (re-delivery), committing offset")
                worker.commit_offset()
                continue

            print(f"claimed job {job_id} (eval_run_id={eval_run_id_str})")
            db = SessionLocal()
            try:
                eval_run_id = uuid.UUID(eval_run_id_str)
                worker.update_status(job_id, "in_progress", db=db)
                eval_engine.run_eval(eval_run_id)
                worker.update_status(job_id, "completed", result={"eval_run_id": eval_run_id_str}, db=db)
                worker.commit_offset()   # only commit AFTER successful processing
                print(f"job {job_id} completed")
            except Exception as exc:
                error_text = f"{exc}\n{traceback.format_exc()}"
                # Phase 5.1: retry with backoff via a fresh message, or dead-letter
                # once max_job_retries is exhausted -- see retry_or_dead_letter()'s
                # docstring for why commit_offset() below is still required either way.
                dead_lettered = worker.retry_or_dead_letter(claimed, error_text)
                final_status = "failed" if dead_lettered else "pending"
                worker.update_status(job_id, final_status, error=error_text, db=db)
                worker.commit_offset()  # commit to avoid infinite re-delivery loop
                tag = "DEAD-LETTERED" if dead_lettered else f"retrying (attempt {claimed.retry_count + 1})"
                print(f"job {job_id} FAILED, {tag}: {exc}")
            finally:
                lock.release(job_id)
                db.close()
    finally:
        worker.close()


if __name__ == "__main__":
    run_worker_loop()