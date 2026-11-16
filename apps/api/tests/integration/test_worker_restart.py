"""
Integration test: test_worker_restart_does_not_duplicate_job (Section 15).

This is the explicit named test the roadmap requires (Section 15, bullet 3):
"The worker-restart test (Section 10's acceptance criterion) belongs here as an
explicit, named integration test (test_worker_restart_does_not_duplicate_job),
not just something verified manually once."

What it proves:
  - A worker that crashes mid-job (after claiming but before completing) does NOT
    cause a restarted worker to re-process the same job
  - The in_progress row is not re-claimed, so eval results are never duplicated
  - The job's EvalRun is left in whatever state the crashed worker left it,
    with no phantom second run created

Requires: Postgres running (docker-compose up postgres)
Run from the repo root:
    pytest apps/api/tests/integration/test_worker_restart.py -v -m integration
"""
import pytest

from apps.api.core.db import SessionLocal
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.models import Job, Tenant

pytestmark = pytest.mark.integration


def _get_tenant(db):
    tenant = db.query(Tenant).first()
    assert tenant is not None, "run `python -m apps.api.scripts.seed` first"
    return tenant


def test_worker_restart_does_not_duplicate_job():
    """
    Simulates the exact crash scenario:
      1. Worker A publishes a job and claims it (status -> in_progress)
      2. Worker A crashes -- mark_completed/mark_failed is never called
      3. Worker B starts up (simulated by a fresh claim_next_job call)
      4. Worker B must NOT pick up the in_progress job
      5. There must still be exactly ONE job row (no duplicate created)
    """
    db = SessionLocal()
    try:
        tenant = _get_tenant(db)
        queue = PostgresJobQueue(db)

        # Step 1: publish and claim (Worker A starts)
        job_id = queue.publish(
            tenant.id,
            "eval.requested",
            {"eval_run_id": "00000000-0000-0000-0000-000000000001", "_test": "restart_check"},
        )
        claimed_by_a = queue.claim_next_job(job_types=["eval.requested"])
        assert claimed_by_a is not None
        assert claimed_by_a.id == job_id

        # Step 2: Worker A crashes here -- nothing more called on `queue`
        # The row is now status=in_progress but never completed/failed

        # Step 3 + 4: Worker B restarts and polls -- it must not get OUR job back.
        #
        # Deliberately not `assert reclaimed is None`. claim_next_job() is scoped by
        # job_type, not by tenant or by test, so any unrelated pending job in a shared
        # dev database is a legitimate thing for worker B to claim -- that is the
        # queue working correctly, not a failure. Asserting an empty queue made this
        # test order-dependent: it passed alone and failed in a full run whenever any
        # earlier test (or a manual publish) left a pending job behind.
        #
        # The invariant that actually matters is narrower and always true: the job
        # already marked in_progress is never handed out again.
        db_b = SessionLocal()
        try:
            queue_b = PostgresJobQueue(db_b)
            reclaimed = queue_b.claim_next_job(job_types=["eval.requested"])
            assert reclaimed is None or reclaimed.id != job_id, (
                "a restarted worker must NOT reclaim a job already marked in_progress -- "
                "this would cause duplicate processing and corrupt eval results"
            )
            # Put anything unrelated we claimed back, so this test does not strand
            # another test's job in in_progress.
            if reclaimed is not None:
                reclaimed.status = "pending"
                db_b.commit()
        finally:
            db_b.close()

        # Step 5: exactly one job row, not two
        job_count = (
            db.query(Job)
            .filter(
                Job.payload["_test"].astext == "restart_check",
                Job.tenant_id == tenant.id,
            )
            .count()
        )
        assert job_count == 1, "restart must not create a second job row"

    finally:
        # Clean up test job so it doesn't affect other tests
        db.query(Job).filter(
            Job.payload["_test"].astext == "restart_check"
        ).delete(synchronize_session=False)
        db.commit()
        db.close()