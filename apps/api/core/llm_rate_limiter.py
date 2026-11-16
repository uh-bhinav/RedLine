"""
Distributed LLM rate limiter (Phase 2 Section 10, rewritten in Phase 3 Section 3).

Sits between an agent and its LLM provider. `acquire()` is called before every LLM
API call and blocks until a slot is available.

Why this was rewritten
----------------------
Phase 2 used an in-process deque, justified by "typically 1 active eval worker."
KEDA now scales `eval-worker` on Redpanda consumer lag, so more than one worker pod
routinely runs -- and N pods each holding a private 15-RPM window permit 15N requests
per minute against a single provider quota. The limiter was not slightly off under
concurrency; it was arithmetically wrong, and it silently got worse the better
autoscaling worked.

Phase 4 load testing makes that certain rather than likely, and Phase 4 behavioural
diffing runs a full suite twice per comparison.

Two limits, not one
-------------------
The per-minute window never could have prevented what actually broke: free-tier
DAILY quota exhaustion, which is still what blocks the Level 3 and Level 4 gate
verdicts. So `acquire()` checks both:

  ratelimit:llm:{provider}:{model}              sorted set, sliding 60s window
  quota:llm:{provider}:{model}:{YYYY-MM-DD}     counter, expires after the UTC day

A full per-minute window is a wait. An exhausted daily quota is not -- blocking a
worker until midnight UTC is never the right behaviour -- so it raises
DailyQuotaExceeded and lets the caller fail the run with a clear reason.

Why a Lua script
----------------
Check-then-add across two round trips is a race: two workers can both read
`count = 14` against a limit of 15 and both proceed. The whole point of moving to
Redis is coordination between workers, so the check and the add must be one atomic
operation. Redis executes a Lua script atomically, which is the standard solution
and the reason this is not simply a pipeline.

Degradation
-----------
If Redis is unreachable, the limiter falls back to a per-process window and logs a
warning on every transition. That is deliberately the *lenient* failure: refusing all
LLM calls because Redis is down would turn a cache outage into a total platform
outage. The fallback over-permits under multi-worker concurrency, which is exactly
the Phase 2 behaviour -- acceptable briefly, and loud enough to notice.

STABLE CONTRACT: `acquire()` still takes no arguments and returns the seconds slept.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0

# KEYS[1] = sliding window key      KEYS[2] = daily counter key
# ARGV[1] = now (float seconds)     ARGV[2] = window seconds
# ARGV[3] = rpm                     ARGV[4] = daily limit (-1 = unlimited)
# ARGV[5] = daily key TTL seconds   ARGV[6] = unique member for the sorted set
#
# Returns {status, detail}:
#   { 0, used_today}  acquired
#   {-1, used_today}  daily quota exhausted
#   { 1, oldest_score} window full -- caller sleeps until oldest_score + window
_ACQUIRE_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local rpm = tonumber(ARGV[3])
local daily_limit = tonumber(ARGV[4])
local daily_ttl = tonumber(ARGV[5])

local used_today = tonumber(redis.call('GET', KEYS[2]) or '0')
if daily_limit >= 0 and used_today >= daily_limit then
    return {-1, used_today}
end

redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])

if count >= rpm then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {1, tonumber(oldest[2])}
end

redis.call('ZADD', KEYS[1], now, ARGV[6])
redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000) + 1000)
local new_total = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], daily_ttl)
return {0, new_total}
"""


class DailyQuotaExceeded(RuntimeError):
    """The daily request ceiling for this provider/model has been reached.

    Raised rather than blocked on: the quota does not reset until midnight UTC, so
    sleeping would hold a worker for hours. The caller should fail the run with this
    as the reason.
    """


def _seconds_until_utc_midnight(now: datetime | None = None) -> int:
    """TTL for the daily counter: the rest of the UTC day, plus an hour of slack.

    The key already carries the date, so the TTL only needs to outlive the day it
    names -- it exists to stop old dates accumulating in Redis, not to define the
    window.
    """
    now = now or datetime.now(timezone.utc)
    midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = midnight_today + timedelta(days=1)
    return int((next_midnight - now).total_seconds()) + 3600


class LLMRateLimiter:
    """Sliding-window + daily-quota limiter shared across every worker process.

    Usage (unchanged from Phase 2):
        limiter = get_limiter("standard")
        limiter.acquire()   # blocks if at the per-minute limit
        response = client.models.generate_content(...)
    """

    def __init__(
        self,
        rpm: int,
        *,
        provider: str = "unknown",
        model: str = "unknown",
        daily_limit: int | None = None,
        window_seconds: float = WINDOW_SECONDS,
        redis_client: redis.Redis | None = None,
    ):
        self._rpm = rpm
        self._provider = provider
        self._model = model
        self._daily_limit = daily_limit
        self._window = window_seconds

        self.window_key = f"ratelimit:llm:{provider}:{model}"

        # Local fallback state, used only when Redis is unreachable.
        self._timestamps: deque[float] = deque()
        self._lock = Lock()
        self._degraded = False

        self._redis: redis.Redis | None
        self._script = None
        try:
            self._redis = redis_client or _default_redis()
            self._script = self._redis.register_script(_ACQUIRE_LUA)
        except Exception as exc:  # noqa: BLE001 -- any Redis failure degrades
            self._redis = None
            self._enter_degraded(exc)

    # ---------- keys ----------

    @property
    def daily_key(self) -> str:
        """Includes the UTC date, so the counter resets by key rotation, not by TTL."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"quota:llm:{self._provider}:{self._model}:{today}"

    # ---------- public API (STABLE CONTRACT) ----------

    def acquire(self) -> float:
        """Blocks until a request slot is available. Returns seconds slept.

        Raises DailyQuotaExceeded if the daily ceiling is reached.
        """
        if self._redis is None or self._script is None:
            return self._acquire_local()

        slept = 0.0
        while True:
            try:
                status, detail = self._script(
                    keys=[self.window_key, self.daily_key],
                    args=[
                        time.time(),
                        self._window,
                        self._rpm,
                        self._daily_limit if self._daily_limit is not None else -1,
                        _seconds_until_utc_midnight(),
                        f"{time.time()}:{id(self)}",
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                self._enter_degraded(exc)
                return slept + self._acquire_local()

            if status == 0:
                return slept

            if status == -1:
                raise DailyQuotaExceeded(
                    f"daily quota exhausted for {self._provider}/{self._model}: "
                    f"{detail}/{self._daily_limit} requests used today (UTC). "
                    f"Resets at midnight UTC."
                )

            # Window full -- wait until the oldest entry leaves it.
            wait = max(0.0, (float(detail) + self._window) - time.time())
            # Small cushion so we do not immediately re-lose the race by a microsecond.
            wait = min(wait + 0.01, self._window)
            time.sleep(wait)
            slept += wait

    @property
    def current_usage(self) -> int:
        """Requests in the current sliding window (for metrics/logging)."""
        if self._redis is None:
            with self._lock:
                self._evict_local(time.monotonic())
                return len(self._timestamps)
        try:
            self._redis.zremrangebyscore(
                self.window_key, 0, time.time() - self._window
            )
            return int(self._redis.zcard(self.window_key) or 0)
        except Exception as exc:  # noqa: BLE001
            self._enter_degraded(exc)
            return 0

    @property
    def used_today(self) -> int:
        """Requests counted against today's UTC quota."""
        if self._redis is None:
            return 0
        try:
            return int(self._redis.get(self.daily_key) or 0)
        except Exception as exc:  # noqa: BLE001
            self._enter_degraded(exc)
            return 0

    @property
    def remaining_today(self) -> int | None:
        """None when the profile declares no daily limit."""
        if self._daily_limit is None:
            return None
        return max(0, self._daily_limit - self.used_today)

    @property
    def is_degraded(self) -> bool:
        """True when Redis is unreachable and per-process fallback is in use."""
        return self._degraded

    # ---------- fallback ----------

    def _enter_degraded(self, exc: Exception) -> None:
        self._redis = None
        self._script = None
        if not self._degraded:
            self._degraded = True
            logger.warning(
                "LLM rate limiter for %s/%s degraded to per-process window -- Redis "
                "unreachable (%s). Multiple workers will now independently permit %d "
                "requests/min against one provider quota, and the daily ceiling is "
                "NOT enforced.",
                self._provider,
                self._model,
                exc,
                self._rpm,
            )

    def _evict_local(self, now: float) -> None:
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _acquire_local(self) -> float:
        """Phase 2's in-process sliding window. Correct for one process only."""
        with self._lock:
            now = time.monotonic()
            self._evict_local(now)

            slept = 0.0
            if len(self._timestamps) >= self._rpm:
                slept = max(0.0, (self._timestamps[0] + self._window) - now)
                if slept > 0:
                    time.sleep(slept)

            self._timestamps.append(time.monotonic())
            return slept


def _default_redis() -> redis.Redis:
    from apps.api.core.redis_client import get_redis

    client = get_redis()
    client.ping()  # fail fast at construction rather than on the first acquire()
    return client


# Module-level registry -- one limiter per (profile, purpose), per process.
# The Redis keys are shared across processes, so this is a handle cache, not the
# state itself. Keyed by purpose as well as profile name -- see get_limiter()'s
# docstring for why that second axis is load-bearing, not cosmetic.
_limiters: dict[tuple[str, str], LLMRateLimiter] = {}


def get_limiter(profile_name: str, *, for_embedding: bool = False) -> LLMRateLimiter:
    """Returns (creating if needed) the rate limiter for the given profile.

    Found and fixed during a Phase 4 audit: this used to key the limiter to
    `profile.chat_model` unconditionally and cache it by `profile_name` alone.
    `apps/api/services/embeddings.py` calls `get_limiter("standard")` for
    EMBEDDING calls -- the exact same call agents make for their CHAT calls on
    the same profile -- so both got the SAME cached limiter, tracked against
    `gemini-2.0-flash` (the chat model) even though the embedding calls actually
    hit `gemini-embedding-001` on the provider's side. Every embedding call this
    platform has ever made (diff_engine, mining) was silently sharing rag_agent's
    real chat rate/quota bucket, under the wrong model's name, in Redis.

    `for_embedding=True` selects `profile.embedding_model` instead, and the cache
    key includes the purpose so a profile's chat limiter and its embedding
    limiter are two genuinely separate `LLMRateLimiter` instances -- separate
    Redis window keys, separate daily counters, never colliding.

    Known simplification, not silently ignored: `rpm` and `daily_limit` are still
    read from the same profile fields regardless of purpose, since
    model_profiles.yaml does not (yet) declare separate embedding-specific
    values. If a provider's real embedding-model quota differs meaningfully from
    its chat-model quota, add `embedding_rpm`/`embedding_daily_limit` to
    `ModelProfile` rather than assuming they match.
    """
    cache_key = (profile_name, "embedding" if for_embedding else "chat")
    if cache_key not in _limiters:
        from apps.api.core.model_profiles import get_profile

        profile = get_profile(profile_name)
        model = profile.embedding_model if for_embedding else profile.chat_model
        _limiters[cache_key] = LLMRateLimiter(
            rpm=profile.rpm,
            provider=profile.provider,
            model=model,
            daily_limit=profile.daily_limit,
        )
    return _limiters[cache_key]


def reset_limiters() -> None:
    """Clears the registry. Tests only -- profiles are immutable at runtime."""
    _limiters.clear()
