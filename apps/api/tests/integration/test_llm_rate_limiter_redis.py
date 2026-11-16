"""
Redis-backed LLM rate limiter integration tests (Phase 3 Section 3).

These run against a REAL Redis because the thing being verified is coordination
between independent limiter instances -- which is exactly what a fake or an
in-process stub cannot prove. The Lua script's atomicity in particular is only
meaningful on a real server.

The central claim under test: two limiters that share a provider/model share one
budget. Under the Phase 2 in-process deque this was false, and it got worse the more
worker pods KEDA started.

Requires:
  - Redis running (docker compose up redis)

Run from the repo root:
    pytest apps/api/tests/integration/test_llm_rate_limiter_redis.py -v -m integration
"""
from __future__ import annotations

import threading
import time
import uuid

import pytest

from apps.api.core.llm_rate_limiter import DailyQuotaExceeded, LLMRateLimiter

pytestmark = pytest.mark.integration


@pytest.fixture
def model_id():
    """A unique provider/model per test so runs never share state."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def redis_client():
    try:
        from apps.api.core.redis_client import get_redis
        client = get_redis()
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"redis unavailable: {exc}")
    return client


def _limiter(model_id: str, rpm: int, daily_limit: int | None = None, **kw):
    return LLMRateLimiter(
        rpm=rpm, provider="test", model=model_id, daily_limit=daily_limit, **kw
    )


@pytest.fixture(autouse=True)
def _cleanup(redis_client, model_id):
    yield
    for key in redis_client.scan_iter(match=f"*:llm:test:{model_id}*"):
        redis_client.delete(key)


# ---------- basic operation ----------

def test_acquires_without_sleeping_below_the_limit(redis_client, model_id):
    limiter = _limiter(model_id, rpm=10)
    assert limiter.is_degraded is False

    for _ in range(5):
        assert limiter.acquire() == 0.0

    assert limiter.current_usage == 5


def test_window_key_actually_exists_in_redis(redis_client, model_id):
    limiter = _limiter(model_id, rpm=5)
    limiter.acquire()

    assert redis_client.exists(limiter.window_key) == 1
    assert redis_client.zcard(limiter.window_key) == 1


def test_daily_counter_increments_and_has_a_ttl(redis_client, model_id):
    limiter = _limiter(model_id, rpm=10, daily_limit=100)
    limiter.acquire()
    limiter.acquire()

    assert limiter.used_today == 2
    assert limiter.remaining_today == 98

    ttl = redis_client.ttl(limiter.daily_key)
    assert ttl > 0, "daily counter has no TTL -- old date keys would accumulate forever"
    assert ttl <= 86_400 + 3600 + 5


# ---------- the multi-worker claim ----------

def test_two_limiters_share_one_window(redis_client, model_id):
    """The whole reason for this rewrite. Two limiter instances = two worker pods.

    Under the Phase 2 in-process deque both would independently permit `rpm`
    requests. Here the third acquire must block because the budget is shared.
    """
    worker_a = _limiter(model_id, rpm=2)
    worker_b = _limiter(model_id, rpm=2)

    assert worker_a.acquire() == 0.0
    assert worker_b.acquire() == 0.0

    # Budget of 2 is now spent across both workers.
    assert worker_a.current_usage == 2
    assert worker_b.current_usage == 2

    start = time.perf_counter()
    slept = worker_b.acquire()
    elapsed = time.perf_counter() - start

    assert slept > 0, "second worker did not observe the first worker's usage"
    assert elapsed > 0.5, "did not actually wait for the shared window to clear"


def test_two_limiters_share_one_daily_counter(redis_client, model_id):
    worker_a = _limiter(model_id, rpm=100, daily_limit=3)
    worker_b = _limiter(model_id, rpm=100, daily_limit=3)

    worker_a.acquire()
    worker_b.acquire()
    worker_a.acquire()

    assert worker_b.used_today == 3
    assert worker_b.remaining_today == 0

    with pytest.raises(DailyQuotaExceeded):
        worker_b.acquire()


def test_concurrent_acquires_never_exceed_the_limit(redis_client, model_id):
    """Atomicity check. With a check-then-add pipeline instead of the Lua script,
    concurrent threads can both read count=N-1 and both proceed, overshooting."""
    rpm = 10
    limiter_count = 8
    acquired = []
    lock = threading.Lock()
    barrier = threading.Barrier(limiter_count)

    def worker():
        # Each thread is its own limiter instance == its own pod.
        lim = _limiter(model_id, rpm=rpm)
        barrier.wait()
        # Non-blocking probe: only count acquires that needed no sleep, i.e. that
        # genuinely found room in the window.
        slept = lim.acquire()
        if slept == 0.0:
            with lock:
                acquired.append(1)

    threads = [threading.Thread(target=worker) for _ in range(limiter_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(acquired) <= rpm, (
        f"{len(acquired)} immediate acquires exceeded the limit of {rpm} -- "
        f"the check-and-add was not atomic"
    )
    assert redis_client.zcard(_limiter(model_id, rpm=rpm).window_key) <= rpm


# ---------- daily quota ----------

def test_daily_quota_raises_rather_than_blocking(redis_client, model_id):
    """Blocking a worker until midnight UTC is never right, so this raises."""
    limiter = _limiter(model_id, rpm=100, daily_limit=2)

    limiter.acquire()
    limiter.acquire()

    start = time.perf_counter()
    with pytest.raises(DailyQuotaExceeded, match="daily quota exhausted"):
        limiter.acquire()
    assert time.perf_counter() - start < 1.0, "it blocked instead of raising"


def test_daily_quota_message_names_the_model_and_the_reset(redis_client, model_id):
    limiter = _limiter(model_id, rpm=100, daily_limit=1)
    limiter.acquire()

    with pytest.raises(DailyQuotaExceeded) as exc:
        limiter.acquire()

    message = str(exc.value)
    assert model_id in message
    assert "midnight UTC" in message
    assert "1/1" in message


def test_daily_check_happens_before_the_window_wait(redis_client, model_id):
    """An exhausted daily quota must short-circuit, not make the caller sit through a
    per-minute wait first only to then be refused."""
    limiter = _limiter(model_id, rpm=1, daily_limit=1)
    limiter.acquire()  # spends both the window slot and the daily budget

    start = time.perf_counter()
    with pytest.raises(DailyQuotaExceeded):
        limiter.acquire()
    assert time.perf_counter() - start < 1.0


def test_no_daily_limit_means_no_daily_ceiling(redis_client, model_id):
    limiter = _limiter(model_id, rpm=100, daily_limit=None)
    for _ in range(20):
        limiter.acquire()
    assert limiter.remaining_today is None


# ---------- window behaviour ----------

def test_window_slides(redis_client, model_id):
    limiter = _limiter(model_id, rpm=2, window_seconds=1.0)

    limiter.acquire()
    limiter.acquire()
    assert limiter.current_usage == 2

    time.sleep(1.2)
    assert limiter.current_usage == 0, "old entries were not evicted from the window"
    assert limiter.acquire() == 0.0


def test_separate_models_have_separate_budgets(redis_client, model_id):
    a = _limiter(f"{model_id}-a", rpm=1)
    b = _limiter(f"{model_id}-b", rpm=1)

    assert a.acquire() == 0.0
    assert b.acquire() == 0.0, "a different model's usage consumed this model's budget"

    for key in redis_client.scan_iter(match=f"*:llm:test:{model_id}-*"):
        redis_client.delete(key)
