"""
RedpandaJobQueue (Phase 2) — swaps in behind the STABLE CONTRACT from Phase 1.

The interface is identical to PostgresJobQueue: publish() and get_status() are
the only public methods the router layer ever calls. The worker now uses
consume_one() instead of claim_next_job() -- because Redpanda/Kafka's consumer
model is fundamentally different from the Postgres SKIP LOCKED pattern:
  - Phase 1: worker polls a table, claims a row (lock), processes, marks done
  - Phase 2: worker is assigned partitions by the broker; commits offset only
    after successful processing; a crash means the message is re-delivered to
    the next consumer in the group (at-least-once delivery)

At-least-once vs exactly-once: Kafka guarantees at-least-once delivery by
default. For eval jobs this is acceptable -- if a worker crashes mid-run, the
EvalRun row is already in the DB (status=running) and the eval_engine will
detect the inconsistency. A recovery pass (out of scope for Phase 2) can reset
stale running runs. For now, the DistributedLock (redis_client.py) prevents
the at-least-once re-delivery from causing duplicate processing:
  acquire lock(job_id) → process → release lock
  re-delivered message → acquire fails → skip → offset committed

Job status is stored in Postgres (the `jobs` table from Phase 1 still exists
for audit purposes) AND in Redis (JobStatusCache) for fast polling.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient
from sqlalchemy.orm import Session

from apps.api.core.config import get_settings
from apps.api.core.jobqueue import ClaimedJob, JobStatus
from apps.api.core.redis_client import JobStatusCache
from apps.api.models.job import Job

_settings = get_settings()


def _make_producer() -> Producer:
    return Producer(
        {
            "bootstrap.servers": _settings.redpanda_bootstrap_servers,
            "acks": "all",          # wait for broker to confirm write
            "retries": 3,
            "retry.backoff.ms": 200,
        }
    )


def _make_consumer(group_id: str) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": _settings.redpanda_bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,  # we commit manually, after processing
        }
    )


class RedpandaJobQueue:
    """Phase 2 implementation of the JobQueue STABLE CONTRACT.

    publish() and get_status() are drop-in replacements for PostgresJobQueue's
    versions -- routers and the CLI call the same interface and don't know
    which implementation is active.
    """

    def __init__(self, db: Session):
        self._db = db
        self._producer = _make_producer()
        self._cache = JobStatusCache()

    def publish(self, tenant_id: uuid.UUID, job_type: str, payload: dict) -> uuid.UUID:
        """Creates a persistent DB record (for audit/recovery), publishes to Redpanda,
        caches initial status, and returns the job_id immediately."""
        job = Job(
            tenant_id=tenant_id,
            job_type=job_type,
            payload=payload,
            status="pending",
        )
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)

        # Publish to Redpanda -- topic is partitioned by tenant_id so one
        # tenant's burst never delays another's job (noisy-neighbor protection,
        # Holy Grail §10.1).
        message = json.dumps(
            {
                "job_id": str(job.id),
                "tenant_id": str(tenant_id),
                "job_type": job_type,
                "payload": payload,
            }
        ).encode("utf-8")

        topic = _settings.topic_eval_requested
        self._producer.produce(
            topic=topic,
            value=message,
            key=str(tenant_id).encode("utf-8"),  # partition key = tenant_id
        )
        self._producer.flush()

        # Warm the cache so the first poll from the caller is instant.
        self._cache.set(job.id, {"status": "pending", "result": None, "error": None})

        return job.id

    def get_status(self, job_id: uuid.UUID) -> JobStatus:
        """Cache-first read: Redis → Postgres fallback."""
        cached = self._cache.get(job_id)
        if cached is not None:
            return JobStatus(id=job_id, **cached)

        job = self._db.get(Job, job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        return JobStatus(id=job.id, status=job.status, result=job.result, error=job.error)


class RedpandaEvalWorker:
    """Stateful consumer wrapper used by the eval worker process.

    Replaces the PostgresJobQueue.claim_next_job() polling pattern with a
    Kafka consumer that is assigned topic partitions by the broker. Multiple
    RedpandaEvalWorker processes in the same consumer group automatically
    share the load across partitions without any coordination code.
    """

    def __init__(self, group_id: str = "eval-worker"):
        self._consumer = _make_consumer(group_id)
        self._consumer.subscribe([_settings.topic_eval_requested])
        self._cache = JobStatusCache()
        self._producer = _make_producer()

    def consume_one(self, timeout_seconds: float = 2.0) -> ClaimedJob | None:
        """Polls for one message. Returns None on timeout (no messages available).

        Does NOT commit the offset yet -- the caller must call commit_offset()
        after successful processing so a crash during processing causes
        re-delivery rather than silent job loss.
        """
        msg = self._consumer.poll(timeout=timeout_seconds)
        if msg is None:
            return None
        if msg.error():
            raise KafkaException(msg.error())

        self._current_msg = msg
        data = json.loads(msg.value().decode("utf-8"))
        return ClaimedJob(
            id=uuid.UUID(data["job_id"]),
            tenant_id=uuid.UUID(data["tenant_id"]),
            job_type=data["job_type"],
            payload=data["payload"],
        )

    def commit_offset(self) -> None:
        """Commits the offset of the last consumed message. Call only after
        successful processing -- never before."""
        if self._current_msg is not None:
            self._consumer.commit(message=self._current_msg, asynchronous=False)
            self._current_msg = None

    def update_status(self, job_id: uuid.UUID, status: str,
                      result: dict | None = None, error: str | None = None,
                      db: Session | None = None) -> None:
        """Updates job status in both Postgres and the Redis cache."""
        status_data = {"status": status, "result": result, "error": error}
        self._cache.set(job_id, status_data)
        self._cache.invalidate(job_id)  # force next poll to re-read
        self._cache.set(job_id, status_data)

        if db is not None:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = status
                job.result = result
                job.error = error
                job.updated_at = datetime.utcnow()
                db.commit()

    def close(self) -> None:
        self._consumer.close()
        self._producer.flush()