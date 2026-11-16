"""
The Job Queue abstraction (Phase1 roadmap Section 5) — STABLE CONTRACT.

Routers and the eval engine must only ever talk to this interface, never to the
`jobs` table directly. Phase 2 swaps PostgresJobQueue for a RedpandaJobQueue behind
the same publish()/get_status() signatures without touching any calling code.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from apps.api.models.job import Job


class JobStatus(BaseModel):
    """What callers polling a job get back. Mirrors the public surface of the `jobs` row."""

    id: uuid.UUID
    status: str  # 'pending' | 'in_progress' | 'completed' | 'failed'
    result: dict | None = None
    error: str | None = None


class ClaimedJob(BaseModel):
    """What a worker gets back from claim_next_job(). Internal to PostgresJobQueue —
    not part of the cross-phase STABLE CONTRACT, since Phase 2's Redpanda consumer
    hands the worker a message, not a claimed row."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    job_type: str
    payload: dict
    attempt: int = 1
    max_attempts: int = 3


class ReapedJob(BaseModel):
    id: uuid.UUID
    job_type: str
    payload: dict
    status: str  # 'pending' (will retry) | 'failed'


RETRY_BASE_SECONDS = 5


class JobQueue(Protocol):
    def publish(self, tenant_id: uuid.UUID, job_type: str, payload: dict) -> uuid.UUID:
        """Creates a job, returns its id immediately. Must not block on the job's execution."""
        ...

    def get_status(self, job_id: uuid.UUID) -> JobStatus:
        """Returns current status + result/error if completed."""
        ...


class PostgresJobQueue:
    """Phase 1 implementation: INSERTs into the `jobs` table.

    The eval_worker polls this table on a short interval via `claim_next_job`, which uses
    SELECT ... FOR UPDATE SKIP LOCKED so two worker processes can never claim the same
    pending job at the same time. This is required even with a single worker process —
    it costs nothing now and prevents a real bug the moment a second worker is started
    (Holy Grail doc §10.5, distributed locks).
    """

    def __init__(self, db: Session):
        self.db = db

    def publish(self, tenant_id: uuid.UUID, job_type: str, payload: dict) -> uuid.UUID:
        job = Job(tenant_id=tenant_id, job_type=job_type, payload=payload, status="pending")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job.id

    def get_status(self, job_id: uuid.UUID) -> JobStatus:
        job = self.db.get(Job, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        return JobStatus(id=job.id, status=job.status, result=job.result, error=job.error)

    def claim_next_job(self, job_types: list[str] | None = None) -> ClaimedJob | None:
        """Atomically claims the oldest pending job and marks it in_progress.

        Returns None if nothing is pending. The FOR UPDATE lock is only held for the
        duration of this one method call (select + update + commit) — never across the
        job's actual processing time, which is what keeps this safe under concurrency.
        """
        stmt = select(Job).where(Job.status == "pending", Job.available_at <= func.now())
        if job_types:
            stmt = stmt.where(Job.job_type.in_(job_types))
        stmt = stmt.order_by(Job.created_at).limit(1).with_for_update(skip_locked=True)

        job = self.db.execute(stmt).scalar_one_or_none()
        if job is None:
            self.db.commit()  # release the (empty) transaction cleanly
            return None

        job.status = "in_progress"
        job.attempts = (job.attempts or 0) + 1
        job.started_at = func.now()
        job.heartbeat_at = func.now()
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)

        return ClaimedJob(
            id=job.id, tenant_id=job.tenant_id, job_type=job.job_type, payload=job.payload,
            attempt=job.attempts, max_attempts=job.max_attempts,
        )

    def heartbeat(self, job_id: uuid.UUID) -> None:
        """Marks an in_progress job as still alive so reap_stale() leaves it alone."""
        self.db.execute(
            update(Job).where(Job.id == job_id, Job.status == "in_progress").values(heartbeat_at=func.now())
        )
        self.db.commit()

    def _fail_or_retry_locked(self, job: Job, error: str) -> str:
        """Caller must hold the row lock and commit. Returns the new status."""
        job.error = error
        job.updated_at = datetime.utcnow()
        if (job.attempts or 0) < (job.max_attempts or 1):
            delay = RETRY_BASE_SECONDS * (2 ** (job.attempts or 0))
            job.status = "pending"
            job.available_at = func.now() + timedelta(seconds=delay)
        else:
            job.status = "failed"
        return job.status

    def fail_or_retry(self, job_id: uuid.UUID, error: str) -> str:
        """attempts < max_attempts -> back to pending with exponential backoff
        (available_at = now + 5 * 2^attempts seconds); otherwise failed.
        Returns the resulting status ('pending' or 'failed')."""
        job = self.db.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
        if job is None:
            self.db.commit()
            raise ValueError(f"job {job_id} not found")
        status = self._fail_or_retry_locked(job, error)
        self.db.commit()
        return status

    def reap_stale(self, older_than_seconds: int, job_types: list[str] | None = None) -> list[ReapedJob]:
        """Finds in_progress jobs whose heartbeat is older than the threshold (crashed or
        hung workers) and routes each through fail_or_retry. FOR UPDATE SKIP LOCKED so
        concurrent reapers never double-process a job."""
        last_beat = func.coalesce(Job.heartbeat_at, Job.started_at, Job.updated_at)
        cutoff = func.now() - timedelta(seconds=older_than_seconds)
        stmt = select(Job).where(Job.status == "in_progress", last_beat < cutoff)
        if job_types:
            stmt = stmt.where(Job.job_type.in_(job_types))
        stmt = stmt.with_for_update(skip_locked=True)
        reaped: list[ReapedJob] = []
        for job in self.db.execute(stmt).scalars().all():
            status = self._fail_or_retry_locked(job, f"reaped: no heartbeat for >{older_than_seconds}s")
            reaped.append(ReapedJob(id=job.id, job_type=job.job_type, payload=job.payload, status=status))
        self.db.commit()
        return reaped

    def mark_completed(self, job_id: uuid.UUID, result: dict) -> None:
        job = self.db.get(Job, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        job.status = "completed"
        job.result = result
        job.updated_at = datetime.utcnow()
        self.db.commit()

    def mark_failed(self, job_id: uuid.UUID, error: str) -> None:
        job = self.db.get(Job, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        job.status = "failed"
        job.error = error
        job.updated_at = datetime.utcnow()
        self.db.commit()