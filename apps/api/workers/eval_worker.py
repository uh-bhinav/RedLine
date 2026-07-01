"""
Eval worker (Phase1 roadmap Section 10) -- long-running process.

Polls the `jobs` table for job_type = "eval.requested", claims one via SKIP LOCKED
(PostgresJobQueue.claim_next_job -- the same mechanism proven safe in Section 5's
tests), runs it through eval_engine.run_eval(), and marks the job completed/failed.

Run this as a separate, long-lived process alongside the API:
    python -m apps.api.workers.eval_worker
"""
import time
import traceback
import uuid

from apps.api.core.db import SessionLocal
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.services import eval_engine

POLL_INTERVAL_SECONDS = 2
JOB_TYPE = "eval.requested"


def run_worker_loop() -> None:
    print(f"eval_worker started, polling for job_type='{JOB_TYPE}' every {POLL_INTERVAL_SECONDS}s")
    while True:
        db = SessionLocal()
        try:
            queue = PostgresJobQueue(db)
            claimed = queue.claim_next_job(job_types=[JOB_TYPE])
            if claimed is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            print(f"claimed job {claimed.id} (eval_run_id={claimed.payload['eval_run_id']})")
            try:
                eval_run_id = uuid.UUID(claimed.payload["eval_run_id"])
                eval_engine.run_eval(eval_run_id)
                queue.mark_completed(claimed.id, {"eval_run_id": str(eval_run_id)})
                print(f"job {claimed.id} completed")
            except Exception as exc:
                error_text = f"{exc}\n{traceback.format_exc()}"
                queue.mark_failed(claimed.id, error_text)
                print(f"job {claimed.id} FAILED: {exc}")
        finally:
            db.close()


if __name__ == "__main__":
    run_worker_loop()