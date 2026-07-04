"""
Redis client (Phase 2 Section 2).

Three distinct uses, each in its own class -- because "just use Redis" without
knowing which pattern you're implementing is a junior-level answer (Holy Grail §10.5):

  1. RateLimiter   -- per-tenant token bucket (sliding window), noisy-neighbor protection
  2. DistributedLock -- prevents duplicate job processing across multiple workers
  3. JobStatusCache  -- `GET /eval-runs/{id}` reads Redis first, falls back to Postgres
"""
from __future__ import annotations

import json
import time
import uuid

import redis

from apps.api.core.config import get_settings

_settings = get_settings()
_pool = redis.ConnectionPool.from_url(_settings.redis_url, decode_responses=True)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


# ---------- 1. Rate Limiter (sliding window) ----------

class RateLimiter:
    """Per-tenant sliding-window rate limiter backed by a Redis sorted set.

    Key: `rl:{tenant_id}`
    Each request adds the current timestamp as a member; old timestamps outside
    the window are pruned on every check. This is the sliding-window pattern --
    more precise than a fixed token bucket at the cost of slightly more memory.
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._r = get_redis()

    def is_allowed(self, tenant_id: uuid.UUID) -> bool:
        """Returns True if the tenant is within their rate limit."""
        key = f"rl:{tenant_id}"
        now = time.time()
        window_start = now - self._window

        pipe = self._r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, self._window + 1)
        _, current_count, _, _ = pipe.execute()

        return current_count < self._max

    def remaining(self, tenant_id: uuid.UUID) -> int:
        key = f"rl:{tenant_id}"
        now = time.time()
        window_start = now - self._window
        self._r.zremrangebyscore(key, 0, window_start)
        return max(0, self._max - (self._r.zcard(key) or 0))


# ---------- 2. Distributed Lock ----------

class DistributedLock:
    """Prevents two workers from processing the same job concurrently.

    Uses SET NX + EX (atomic set-if-not-exists with expiry) -- the minimal safe
    pattern that doesn't require a full Redlock quorum for a single Redis node.
    For Phase 4 with a Redis cluster, replace with redlock-py.

    Lock key: `lock:job:{job_id}`
    TTL: slightly longer than the expected max job duration so a crashed worker's
    lock eventually expires and a recovery process can re-queue.
    """

    def __init__(self, ttl_seconds: int = 600):
        self._ttl = ttl_seconds
        self._r = get_redis()

    def acquire(self, job_id: uuid.UUID) -> bool:
        """Returns True if the lock was acquired (caller may proceed). False = another worker holds it."""
        key = f"lock:job:{job_id}"
        return self._r.set(key, "1", nx=True, ex=self._ttl) is not None

    def release(self, job_id: uuid.UUID) -> None:
        self._r.delete(f"lock:job:{job_id}")


# ---------- 3. Job Status Cache ----------

class JobStatusCache:
    """Caches EvalRun status in Redis so `GET /eval-runs/{id}` doesn't hit Postgres on every poll.

    Cache is invalidated (deleted) whenever the worker updates the run's status.
    TTL is a safety net for the case where the worker crashes before invalidating.
    """

    TTL_SECONDS = 30

    def __init__(self):
        self._r = get_redis()

    def get(self, eval_run_id: uuid.UUID) -> dict | None:
        raw = self._r.get(f"run_status:{eval_run_id}")
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, eval_run_id: uuid.UUID, status_data: dict) -> None:
        self._r.setex(f"run_status:{eval_run_id}", self.TTL_SECONDS, json.dumps(status_data))

    def invalidate(self, eval_run_id: uuid.UUID) -> None:
        self._r.delete(f"run_status:{eval_run_id}")