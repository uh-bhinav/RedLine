"""
Unit tests for gate_engine._compute_gate_result() (roadmap Section 15).

Pure function tests -- no database, no LLM, no I/O. These cover every
threshold combination the Gate Engine can evaluate. The _compute_gate_result()
refactor exists specifically so these can run without any infrastructure.

Run from the repo root:
    pytest apps/api/tests/unit/test_gate_engine.py -v
"""
import pytest

from apps.api.services.gate_engine import _compute_gate_result, DEFAULT_MIN_PASS_RATE

pytestmark = pytest.mark.unit


# ---------- pass_rate thresholds ----------

def test_gate_passes_when_all_cases_pass():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.001, avg_latency_ms=1000,
        min_pass_rate=DEFAULT_MIN_PASS_RATE, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is True
    assert result.reasons == []


def test_gate_fails_when_pass_rate_below_threshold():
    result = _compute_gate_result(
        passed_count=2, total=3, avg_cost_usd=0.001, avg_latency_ms=1000,
        min_pass_rate=DEFAULT_MIN_PASS_RATE, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is False
    assert len(result.reasons) == 1
    assert "pass_rate 0.67" in result.reasons[0]
    assert "0.90" in result.reasons[0]


def test_gate_passes_at_exact_threshold():
    # 9/10 = 0.9 exactly -- must pass, not fail
    result = _compute_gate_result(
        passed_count=9, total=10, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is True


def test_gate_fails_with_zero_cases():
    result = _compute_gate_result(
        passed_count=0, total=0, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=DEFAULT_MIN_PASS_RATE, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is False
    assert "no case results" in result.reasons[0]


def test_gate_fails_when_all_cases_fail():
    result = _compute_gate_result(
        passed_count=0, total=3, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=DEFAULT_MIN_PASS_RATE, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is False
    assert "pass_rate 0.00" in result.reasons[0]


# ---------- cost threshold ----------

def test_gate_fails_when_avg_cost_exceeds_max():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.05, avg_latency_ms=1000,
        min_pass_rate=0.9, max_avg_cost_usd=0.01, max_avg_latency_ms=None,
    )
    assert result.passed is False
    assert any("avg_cost_usd" in r for r in result.reasons)


def test_gate_passes_when_cost_under_max():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.005, avg_latency_ms=1000,
        min_pass_rate=0.9, max_avg_cost_usd=0.01, max_avg_latency_ms=None,
    )
    assert result.passed is True


def test_gate_skips_cost_check_when_no_max_configured():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=999.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is True  # no cost policy = no cost gate


# ---------- latency threshold ----------

def test_gate_fails_when_avg_latency_exceeds_max():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.0, avg_latency_ms=6000,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=5000,
    )
    assert result.passed is False
    assert any("avg_latency_ms" in r for r in result.reasons)


def test_gate_passes_when_latency_under_max():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.0, avg_latency_ms=3000,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=5000,
    )
    assert result.passed is True


# ---------- multiple violations ----------

def test_gate_collects_all_violation_reasons():
    """All three thresholds violated simultaneously -- all three reasons must appear."""
    result = _compute_gate_result(
        passed_count=1, total=3,        # pass_rate 0.33 < 0.9
        avg_cost_usd=0.1,               # > max 0.01
        avg_latency_ms=10000,           # > max 5000
        min_pass_rate=0.9,
        max_avg_cost_usd=0.01,
        max_avg_latency_ms=5000,
    )
    assert result.passed is False
    assert len(result.reasons) == 3


def test_gate_reasons_are_human_readable():
    """Reasons must be legible to a newcomer -- this is the dashboard's gate banner text."""
    result = _compute_gate_result(
        passed_count=2, total=3, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    reason = result.reasons[0]
    assert "pass_rate" in reason
    assert "below" in reason
    assert "minimum" in reason


# ---------- ARS threshold (Phase 4 Section 1) ----------

def test_gate_ignores_ars_when_not_configured():
    """ars/min_ars default to None -- every pre-Phase-4 call above this line in the
    file must keep passing unchanged, which is the actual regression this guards."""
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
    )
    assert result.passed is True


def test_gate_fails_when_ars_below_min_ars():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
        ars=0.75, min_ars=0.9,
    )
    assert result.passed is False
    assert any("ars" in r and "0.750" in r for r in result.reasons)


def test_gate_passes_when_ars_meets_min_ars_exactly():
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
        ars=0.9, min_ars=0.9,
    )
    assert result.passed is True


def test_gate_skips_ars_check_when_min_ars_configured_but_ars_missing():
    """A run with no ARSSnapshot yet (predates Phase 4, or ARS computation failed
    non-fatally) must not crash the gate or count as a violation by default."""
    result = _compute_gate_result(
        passed_count=3, total=3, avg_cost_usd=0.0, avg_latency_ms=0,
        min_pass_rate=0.9, max_avg_cost_usd=None, max_avg_latency_ms=None,
        ars=None, min_ars=0.9,
    )
    assert result.passed is True


def test_gate_collects_ars_reason_alongside_other_violations():
    result = _compute_gate_result(
        passed_count=1, total=3, avg_cost_usd=0.1, avg_latency_ms=10000,
        min_pass_rate=0.9, max_avg_cost_usd=0.01, max_avg_latency_ms=5000,
        ars=0.5, min_ars=0.9,
    )
    assert result.passed is False
    assert len(result.reasons) == 4