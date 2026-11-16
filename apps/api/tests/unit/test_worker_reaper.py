"""Reliability tests for PostgresJobQueue: retry/backoff, heartbeat, reaper.
Needs the real Postgres with migration 0004 applied and a seeded tenant."""
import pytest
from sqlalchemy import text

from apps.api.core.db import SessionLocal
from apps.api.core.jobqueue import PostgresJobQueue
from apps.api.models import Job

JT = "test.reaper"


@pytest.fixture()
def session(make_tenant):
    """A session plus a fresh tenant (tables are truncated between tests by conftest)."""
    s = SessionLocal()
    try:
        s.info["tenant_id"] = make_tenant("reaper-test-tenant").id
        yield s
    finally:
        s.rollback()
        s.close()


def _publish(session) -> tuple[PostgresJobQueue, object]:
    q = PostgresJobQueue(session)
    return q, q.publish(session.info["tenant_id"], JT, {"k": "v"})


def _age_heartbeat(session, job_id, seconds):
    session.execute(
        text("UPDATE jobs SET heartbeat_at = now() - make_interval(secs => :s) WHERE id = :i"),
        {"s": seconds, "i": str(job_id)},
    )
    session.commit()


def _job(session, job_id) -> Job:
    session.expire_all()
    return session.get(Job, job_id)


def test_claim_increments_attempts_and_sets_timestamps(session):
    q, jid = _publish(session)
    claimed = q.claim_next_job(job_types=[JT])
    assert claimed.id == jid and claimed.attempt == 1
    job = _job(session, jid)
    assert job.status == "in_progress" and job.attempts == 1
    assert job.started_at is not None and job.heartbeat_at is not None


def test_heartbeat_refreshes_timestamp(session):
    q, jid = _publish(session)
    q.claim_next_job(job_types=[JT])
    _age_heartbeat(session, jid, 500)
    old = _job(session, jid).heartbeat_at
    q.heartbeat(jid)
    assert _job(session, jid).heartbeat_at > old


def test_fail_or_retry_backs_off_then_fails(session):
    q, jid = _publish(session)
    q.claim_next_job(job_types=[JT])
    assert q.fail_or_retry(jid, "boom") == "pending"
    job = _job(session, jid)
    assert job.status == "pending" and job.error == "boom"
    delay = session.execute(
        text("SELECT extract(epoch FROM available_at - now()) FROM jobs WHERE id = :i"), {"i": str(jid)}
    ).scalar()
    assert 5 * 2**1 - 2 < delay <= 5 * 2**1 + 1  # attempts == 1 -> ~10s
    # not claimable until available_at passes
    assert q.claim_next_job(job_types=[JT]) is None
    session.execute(text("UPDATE jobs SET available_at = now() WHERE id = :i"), {"i": str(jid)})
    session.commit()
    assert q.claim_next_job(job_types=[JT]).attempt == 2
    session.execute(text("UPDATE jobs SET attempts = max_attempts WHERE id = :i"), {"i": str(jid)})
    session.commit()
    assert q.fail_or_retry(jid, "final") == "failed"
    assert _job(session, jid).status == "failed"


def test_reaper_requeues_stale_and_ignores_fresh(session):
    q, jid = _publish(session)
    q.claim_next_job(job_types=[JT])
    assert q.reap_stale(60, job_types=[JT]) == []  # fresh heartbeat
    _age_heartbeat(session, jid, 300)
    reaped = q.reap_stale(60, job_types=[JT])
    assert [r.id for r in reaped] == [jid] and reaped[0].status == "pending"
    assert _job(session, jid).status == "pending"


def test_reaper_fails_job_with_no_attempts_left(session):
    q, jid = _publish(session)
    q.claim_next_job(job_types=[JT])
    session.execute(text("UPDATE jobs SET attempts = max_attempts WHERE id = :i"), {"i": str(jid)})
    session.commit()
    _age_heartbeat(session, jid, 300)
    reaped = q.reap_stale(60, job_types=[JT])
    assert reaped[0].status == "failed"
    job = _job(session, jid)
    assert job.status == "failed" and "reaped" in job.error
