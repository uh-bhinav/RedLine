"""
Unit tests for LLMRateLimiter (Phase 3 Section 3).

No Redis, no network. These cover the parts that must be correct without a broker:
key naming, TTL arithmetic, profile wiring, and -- most importantly -- the degraded
fallback, since that path only runs when Redis is already broken and would otherwise
never be exercised until an outage.

The Redis coordination itself (the Lua script, cross-process sharing, daily counter)
is covered in tests/integration/test_llm_rate_limiter_redis.py against a real Redis,
because a fake cannot meaningfully verify script atomicity.

Run from the repo root:
    pytest apps/api/tests/unit/test_llm_rate_limiter.py -v -m unit
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from apps.api.core.llm_rate_limiter import (
    DailyQuotaExceeded,
    LLMRateLimiter,
    _seconds_until_utc_midnight,
)

pytestmark = pytest.mark.unit


class _DeadRedis:
    """A Redis handle where everything fails, to force the degraded path."""

    def register_script(self, _script):
        raise ConnectionError("redis is down")

    def __getattr__(self, _name):
        def _boom(*args, **kwargs):
            raise ConnectionError("redis is down")
        return _boom


def _degraded_limiter(rpm: int = 3, **kwargs) -> LLMRateLimiter:
    return LLMRateLimiter(rpm=rpm, redis_client=_DeadRedis(), **kwargs)


# ---------- key naming ----------

def test_window_key_is_scoped_to_provider_and_model():
    limiter = _degraded_limiter(provider="gemini", model="gemini-2.0-flash")
    assert limiter.window_key == "ratelimit:llm:gemini:gemini-2.0-flash"


def test_daily_key_carries_the_utc_date():
    limiter = _degraded_limiter(provider="gemini", model="gemini-2.0-flash")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert limiter.daily_key == f"quota:llm:gemini:gemini-2.0-flash:{today}"


def test_different_models_do_not_share_a_window():
    a = _degraded_limiter(provider="gemini", model="gemini-2.0-flash")
    b = _degraded_limiter(provider="gemini", model="gemini-2.5-flash")
    assert a.window_key != b.window_key
    assert a.daily_key != b.daily_key


# ---------- daily TTL arithmetic ----------

def test_ttl_covers_the_rest_of_the_day_plus_slack():
    just_after_midnight = datetime(2026, 7, 29, 0, 0, 1, tzinfo=timezone.utc)
    ttl = _seconds_until_utc_midnight(just_after_midnight)
    assert 86_399 + 3600 - 2 <= ttl <= 86_399 + 3600 + 2


def test_ttl_is_still_positive_just_before_midnight():
    almost_midnight = datetime(2026, 7, 29, 23, 59, 59, tzinfo=timezone.utc)
    ttl = _seconds_until_utc_midnight(almost_midnight)
    assert ttl > 3600  # the slack hour alone keeps it alive


def test_ttl_handles_month_end():
    """Naive date arithmetic breaks on the 31st; this is why it is not `.replace(day=+1)`."""
    month_end = datetime(2026, 7, 31, 22, 0, 0, tzinfo=timezone.utc)
    ttl = _seconds_until_utc_midnight(month_end)
    assert 7200 + 3600 - 2 <= ttl <= 7200 + 3600 + 2


def test_ttl_handles_year_end():
    year_end = datetime(2026, 12, 31, 23, 0, 0, tzinfo=timezone.utc)
    ttl = _seconds_until_utc_midnight(year_end)
    assert 3600 + 3600 - 2 <= ttl <= 3600 + 3600 + 2


# ---------- degraded fallback ----------

def test_unreachable_redis_degrades_instead_of_raising():
    """A Redis outage must not stop LLM calls -- that turns a cache outage into a
    total platform outage."""
    limiter = _degraded_limiter(rpm=5)
    assert limiter.is_degraded is True
    assert limiter.acquire() == 0.0


def test_degraded_limiter_still_enforces_the_per_minute_window():
    limiter = _degraded_limiter(rpm=2)
    limiter._window = 0.3  # keep the test fast

    limiter.acquire()
    limiter.acquire()
    slept = limiter.acquire()  # third call must wait for the window

    assert slept > 0, "degraded limiter did not enforce rpm"


def test_degraded_limiter_does_not_sleep_below_the_limit():
    limiter = _degraded_limiter(rpm=10)
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == 0.0


def test_degraded_current_usage_tracks_the_local_window():
    limiter = _degraded_limiter(rpm=10)
    limiter.acquire()
    limiter.acquire()
    assert limiter.current_usage == 2


def test_degraded_limiter_reports_zero_daily_usage():
    """The daily ceiling genuinely is not enforced without Redis. Reporting 0 rather
    than guessing is honest -- the warning log is what flags it."""
    limiter = _degraded_limiter(rpm=5, daily_limit=100)
    limiter.acquire()
    assert limiter.used_today == 0


def test_degradation_is_logged_once_not_per_call(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        limiter = _degraded_limiter(rpm=5)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()

    degraded_warnings = [r for r in caplog.records if "degraded" in r.message]
    assert len(degraded_warnings) == 1, "degradation warning repeated on every call"


# ---------- profile wiring ----------

def test_remaining_today_is_none_without_a_daily_limit():
    limiter = _degraded_limiter(rpm=5, daily_limit=None)
    assert limiter.remaining_today is None


def test_get_limiter_reads_provider_model_and_daily_limit_from_the_profile():
    from apps.api.core.llm_rate_limiter import get_limiter, reset_limiters
    from apps.api.core.model_profiles import get_profile

    reset_limiters()
    try:
        profile = get_profile("standard")
        limiter = get_limiter("standard")

        assert limiter.window_key == (
            f"ratelimit:llm:{profile.provider}:{profile.chat_model}"
        )
        assert limiter._daily_limit == profile.daily_limit
        assert limiter._rpm == profile.rpm
    finally:
        reset_limiters()


def test_get_limiter_returns_the_same_instance_per_profile():
    from apps.api.core.llm_rate_limiter import get_limiter, reset_limiters

    reset_limiters()
    try:
        assert get_limiter("standard") is get_limiter("standard")
        assert get_limiter("standard") is not get_limiter("cheap")
    finally:
        reset_limiters()


# ---------- for_embedding: the chat/embedding conflation fix ----------

def test_embedding_limiter_is_keyed_to_the_embedding_model_not_chat_model():
    """The actual bug: get_limiter("standard") for an embedding call used to
    return the same limiter as get_limiter("standard") for a chat call, tracked
    against the CHAT model's name even though embedding calls hit a different
    model on the provider's side."""
    from apps.api.core.llm_rate_limiter import get_limiter, reset_limiters
    from apps.api.core.model_profiles import get_profile

    reset_limiters()
    try:
        profile = get_profile("standard")
        chat_limiter = get_limiter("standard")
        embedding_limiter = get_limiter("standard", for_embedding=True)

        assert chat_limiter.window_key == f"ratelimit:llm:{profile.provider}:{profile.chat_model}"
        assert embedding_limiter.window_key == (
            f"ratelimit:llm:{profile.provider}:{profile.embedding_model}"
        )
        assert profile.chat_model != profile.embedding_model, (
            "this profile's chat and embedding models are coincidentally the same "
            "name -- pick a different profile to keep this test meaningful"
        )
    finally:
        reset_limiters()


def test_chat_and_embedding_limiters_for_the_same_profile_are_distinct_instances():
    from apps.api.core.llm_rate_limiter import get_limiter, reset_limiters

    reset_limiters()
    try:
        chat = get_limiter("standard")
        embedding = get_limiter("standard", for_embedding=True)
        assert chat is not embedding
        assert chat.window_key != embedding.window_key
        assert chat.daily_key != embedding.daily_key
    finally:
        reset_limiters()


def test_embedding_limiter_is_cached_separately_from_chat():
    """Calling get_limiter(..., for_embedding=True) twice must return the SAME
    embedding limiter, not construct a fresh one each time (which would defeat
    sharing the sliding window across calls in one process)."""
    from apps.api.core.llm_rate_limiter import get_limiter, reset_limiters

    reset_limiters()
    try:
        assert (
            get_limiter("standard", for_embedding=True)
            is get_limiter("standard", for_embedding=True)
        )
    finally:
        reset_limiters()


def test_default_for_embedding_preserves_existing_chat_behavior():
    """Every pre-existing caller (agents' own chat calls, llm_judge) calls
    get_limiter(profile_name) with no for_embedding argument at all -- this must
    keep returning exactly what it always did."""
    from apps.api.core.llm_rate_limiter import get_limiter, reset_limiters
    from apps.api.core.model_profiles import get_profile

    reset_limiters()
    try:
        profile = get_profile("high_reasoning")
        limiter = get_limiter("high_reasoning")
        assert limiter.window_key == f"ratelimit:llm:{profile.provider}:{profile.chat_model}"
    finally:
        reset_limiters()


def test_profiles_declare_a_daily_limit():
    """Phase 3 Section 3 added daily_limit; a profile missing it silently loses the
    daily ceiling, which is the exact failure that blocked the L3/L4 verdicts."""
    from apps.api.core.model_profiles import get_profile, list_profiles

    for name in list_profiles():
        assert get_profile(name).daily_limit is not None, (
            f"profile '{name}' has no daily_limit"
        )


# ---------- exception shape ----------

def test_daily_quota_exceeded_is_a_runtime_error():
    """Callers that only catch RuntimeError must still see it."""
    assert issubclass(DailyQuotaExceeded, RuntimeError)
