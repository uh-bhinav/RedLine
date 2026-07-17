"""
Unit tests for the drift detector (Phase 2 Section 9).

Pure logic -- no DB, no LLM, no network.
Run from the repo root:
    pytest apps/api/tests/unit/test_drift_detector.py -v
"""
import pytest

from apps.api.services.drift.detector import (
    DEFAULT_DRIFT_THRESHOLD,
    detect_model_drift,
)

pytestmark = pytest.mark.unit


def test_stable_pass_rates_do_not_trigger_drift():
    rates = [0.90, 0.91, 0.89, 0.90, 0.90]
    result = detect_model_drift(rates)
    assert result.drifted is False
    assert result.delta > -DEFAULT_DRIFT_THRESHOLD


def test_real_regression_triggers_drift():
    # Simulate: agent was stable at 0.90, then drops to 0.67 (like our case_003 failure)
    rates = [0.90, 0.91, 0.89, 0.90, 0.67]
    result = detect_model_drift(rates)
    assert result.drifted is True
    assert result.delta < -DEFAULT_DRIFT_THRESHOLD
    assert result.current_pass_rate == pytest.approx(0.67)
    assert "dropped" in result.detail


def test_improvement_does_not_trigger_drift():
    # Score goes UP -- should never alert on improvements
    rates = [0.67, 0.68, 0.67, 0.90]
    result = detect_model_drift(rates)
    assert result.drifted is False
    assert result.delta > 0


def test_exactly_at_threshold_does_not_trigger():
    # delta = -0.10 exactly -- must NOT alert (strictly greater than threshold)
    rates = [0.90, 0.80]
    result = detect_model_drift(rates, threshold=0.10)
    assert result.drifted is False
    assert result.delta == pytest.approx(-0.10)


def test_just_over_threshold_triggers():
    rates = [0.90, 0.789]  # delta ≈ -0.111
    result = detect_model_drift(rates, threshold=0.10)
    assert result.drifted is True
    assert result.delta < -0.10


def test_single_snapshot_not_enough_data():
    result = detect_model_drift([0.90])
    assert result.drifted is False
    assert "not enough snapshots" in result.detail


def test_empty_snapshot_list_not_enough_data():
    result = detect_model_drift([])
    assert result.drifted is False


def test_baseline_is_mean_of_all_but_last():
    # Baseline = mean(0.8, 0.9) = 0.85; current = 0.70; delta = -0.15
    rates = [0.80, 0.90, 0.70]
    result = detect_model_drift(rates, threshold=0.10)
    assert result.baseline_pass_rate == pytest.approx(0.85)
    assert result.current_pass_rate == pytest.approx(0.70)
    assert result.delta == pytest.approx(-0.15, abs=0.001)
    assert result.drifted is True


def test_custom_threshold_respected():
    # Same data, but looser threshold (0.20) -- should NOT alert
    rates = [0.90, 0.78]  # delta = -0.12
    result = detect_model_drift(rates, threshold=0.20)
    assert result.drifted is False

    # Same data, tighter threshold (0.05) -- should alert
    result = detect_model_drift(rates, threshold=0.05)
    assert result.drifted is True


def test_detail_string_is_human_readable():
    rates = [0.90, 0.70]
    result = detect_model_drift(rates)
    assert result.drifted is True
    # Must name the actual numbers so a human can understand the alert without code
    assert "0.70" in result.detail or "0.700" in result.detail
    assert "baseline" in result.detail


def test_many_snapshots_uses_all_for_baseline():
    # 9 historical snapshots + 1 current
    rates = [0.90] * 9 + [0.67]
    result = detect_model_drift(rates)
    assert result.baseline_pass_rate == pytest.approx(0.90)
    assert result.current_pass_rate == pytest.approx(0.67)
    assert result.drifted is True