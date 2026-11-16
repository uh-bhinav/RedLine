"""
Unit tests for load_engine._compute_load_stats() and _percentile() (Phase 4 Section 5).

Pure function tests -- no database, no network, no real concurrency. The DB-backed
run_load_test() (real ThreadPoolExecutor concurrency, real adapter calls, real
ClickHouse/Postgres writes) is covered by test_load_engine_end_to_end.py.

Run from the repo root:
    pytest apps/api/tests/unit/test_load_engine.py -v -m unit
"""
import pytest

from apps.api.services.load_engine import LoadSample, _compute_load_stats, _percentile

pytestmark = pytest.mark.unit


# ---------- _percentile ----------

def test_percentile_of_empty_list_is_zero():
    assert _percentile([], 50) == 0.0


def test_percentile_of_single_value():
    assert _percentile([42.0], 50) == 42.0
    assert _percentile([42.0], 99) == 42.0


def test_percentiles_are_monotonically_non_decreasing():
    values = sorted(float(i) for i in range(1, 101))
    p50 = _percentile(values, 50)
    p95 = _percentile(values, 95)
    p99 = _percentile(values, 99)
    assert p50 <= p95 <= p99


def test_p50_of_uniform_distribution_is_near_the_middle():
    values = sorted(float(i) for i in range(1, 101))  # 1..100
    assert 45 <= _percentile(values, 50) <= 55


def test_p99_of_uniform_distribution_is_near_the_top():
    values = sorted(float(i) for i in range(1, 101))
    assert _percentile(values, 99) >= 95


# ---------- _compute_load_stats: empty and trivial cases ----------

def test_zero_samples_returns_a_zeroed_result_not_a_division_error():
    result = _compute_load_stats([], duration_seconds=10.0)
    assert result.total_requests == 0
    assert result.error_rate == 0.0
    assert result.cost_per_hour_usd == 0.0
    assert "no requests" in result.detail


def test_single_successful_sample():
    result = _compute_load_stats(
        [LoadSample(latency_ms=100, success=True, cost_usd=0.001)], duration_seconds=1.0,
    )
    assert result.total_requests == 1
    assert result.successful_requests == 1
    assert result.error_rate == 0.0
    assert result.p50_latency_ms == 100
    assert result.total_cost_usd == 0.001


# ---------- error rate ----------

def test_error_rate_counts_failures_correctly():
    samples = (
        [LoadSample(latency_ms=100, success=True) for _ in range(7)]
        + [LoadSample(latency_ms=100, success=False, error_detail="boom") for _ in range(3)]
    )
    result = _compute_load_stats(samples, duration_seconds=1.0)
    assert result.total_requests == 10
    assert result.successful_requests == 7
    assert result.error_rate == pytest.approx(0.3)


def test_all_failures_is_a_100_percent_error_rate():
    samples = [LoadSample(latency_ms=0, success=False, error_detail="timeout") for _ in range(5)]
    result = _compute_load_stats(samples, duration_seconds=1.0)
    assert result.error_rate == 1.0
    assert result.successful_requests == 0


# ---------- cost extrapolation -- the number the foundational doc calls out ----------

def test_cost_per_hour_extrapolates_from_the_actual_window():
    # $0.01 total spent in 30 seconds -> $1.20/hour at this concurrency.
    samples = [LoadSample(latency_ms=100, success=True, cost_usd=0.01)]
    result = _compute_load_stats(samples, duration_seconds=30.0)
    assert result.total_cost_usd == pytest.approx(0.01)
    assert result.cost_per_hour_usd == pytest.approx(0.01 * (3600 / 30))


def test_cost_per_hour_sums_across_all_samples_not_just_one():
    samples = [LoadSample(latency_ms=100, success=True, cost_usd=0.002) for _ in range(50)]
    result = _compute_load_stats(samples, duration_seconds=60.0)
    assert result.total_cost_usd == pytest.approx(0.1)
    assert result.cost_per_hour_usd == pytest.approx(0.1 * 60)


def test_zero_duration_does_not_raise_a_division_error():
    """Defensive: a load test that somehow reports 0 elapsed seconds must not crash
    stats computation with a ZeroDivisionError."""
    samples = [LoadSample(latency_ms=100, success=True, cost_usd=0.01)]
    result = _compute_load_stats(samples, duration_seconds=0.0)
    assert result.cost_per_hour_usd > 0
    assert result.throughput_rps > 0


# ---------- throughput ----------

def test_throughput_is_requests_over_wall_clock_duration():
    samples = [LoadSample(latency_ms=50, success=True) for _ in range(300)]
    result = _compute_load_stats(samples, duration_seconds=30.0)
    assert result.throughput_rps == pytest.approx(10.0)


# ---------- detail string ----------

def test_detail_names_the_key_numbers():
    samples = [LoadSample(latency_ms=100, success=True, cost_usd=0.001) for _ in range(20)]
    result = _compute_load_stats(samples, duration_seconds=10.0)
    assert "p50=" in result.detail
    assert "p95=" in result.detail
    assert "p99=" in result.detail
    assert "/hour" in result.detail


# ---------- samples are preserved for the caller to persist ----------

def test_result_carries_the_original_samples():
    samples = [LoadSample(latency_ms=1, success=True) for _ in range(3)]
    result = _compute_load_stats(samples, duration_seconds=1.0)
    assert len(result.samples) == 3
