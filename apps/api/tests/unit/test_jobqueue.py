"""
Tests for the Postgres-backed JobQueue (roadmap Section 5).

These need the real docker-compose Postgres running, and the seed script already
run once (these tests use the seeded tenant). Run from the repo root:

    pytest apps/api/tests/unit/test_jobqueue.py -v
"""
import threading

from sqlalchemy import text

from apps.api.core.db import SessionLocal, engine
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.models import Tenant


def _get_seeded_tenant_id(session):
    tenant = session.query(Tenant).first()
    assert tenant is not None, "no tenant found — run `python -m apps.api.scripts.seed` first"
    return tenant.id


def test_restarted_worker_does_not_reclaim_an_in_progress_job():
    """Simulates a crash: claim a job (status -> in_progress), do NOT complete it,
    then have a 'restarted' worker poll again. It must not pick up the same job."""
    session = SessionLocal()
    try:
        tenant_id = _get_seeded_tenant_id(session)
        queue = PostgresJobQueue(session)

        job_id = queue.publish(tenant_id, "test.restart_check", {"marker": "crash-sim"})

        claimed = queue.claim_next_job(job_types=["test.restart_check"])
        assert claimed is not None
        assert claimed.id == job_id

        # the "worker" crashes here -- it never calls mark_completed / mark_failed

        restarted_queue = PostgresJobQueue(session)
        reclaimed = restarted_queue.claim_next_job(job_types=["test.restart_check"])
        assert reclaimed is None, "a restarted worker must not re-claim an in_progress job"
    finally:
        session.close()


def test_skip_locked_prevents_concurrent_double_claim():
    """Holds a real row lock open on one connection (simulating worker A mid-claim) and
    proves a second, fully concurrent claim_next_job() call on a different connection
    skips that row instead of blocking on it or grabbing it too -- even though the row's
    status is still technically 'pending' at that exact moment."""
    setup_session = SessionLocal()
    try:
        tenant_id = _get_seeded_tenant_id(setup_session)
        setup_queue = PostgresJobQueue(setup_session)
        job_id = setup_queue.publish(tenant_id, "test.skip_locked_check", {"marker": "race-sim"})
    finally:
        setup_session.close()

    lock_acquired = threading.Event()
    release_lock = threading.Event()
    worker_b_result: dict[str, object] = {}

    def worker_a_holds_the_lock():
        conn = engine.connect()
        trans = conn.begin()
        conn.execute(
            text("SELECT id FROM jobs WHERE status = 'pending' AND id = :job_id FOR UPDATE SKIP LOCKED"),
            {"job_id": str(job_id)},
        )
        lock_acquired.set()
        release_lock.wait(timeout=5)
        conn.execute(text("UPDATE jobs SET status = 'in_progress' WHERE id = :job_id"), {"job_id": str(job_id)})
        trans.commit()
        conn.close()

    t = threading.Thread(target=worker_a_holds_the_lock)
    t.start()
    assert lock_acquired.wait(timeout=5), "worker A never acquired the lock"

    session_b = SessionLocal()
    try:
        queue_b = PostgresJobQueue(session_b)
        worker_b_result["claimed"] = queue_b.claim_next_job(job_types=["test.skip_locked_check"])
    finally:
        session_b.close()
        release_lock.set()
        t.join(timeout=5)

    assert worker_b_result["claimed"] is None, (
        "worker B must not be able to claim a row that's locked by worker A's "
        "open transaction, even though its status is still 'pending'"
    )