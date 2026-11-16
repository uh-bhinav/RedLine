"""
Unit tests for ars_engine._compute_ars() and compute_error_budget() (Phase 4 Section 1).

Pure function tests -- no database, no LLM, no I/O. Matches the style of
test_gate_engine.py and test_drift_detector.py: these two functions are what the DB-
backed evaluate_ars()/evaluate_error_budget() delegate arithmetic to, and that split
is what makes them testable here without any infrastructure.

Run from the repo root:
    pytest apps/api/tests/unit/test_ars_engine.py -v -m unit
"""
import pytest

from apps.api.services.ars_engine import (
    DEFAULT_ERROR_BUDGET_PCT,
    DEFAULT_TARGET_ARS,
    WEIGHT_CORRECTNESS,
    WEIGHT_COST,
    WEIGHT_LATENCY,
    WEIGHT_SAFETY,
    _compute_ars,
    compute_error_budget,
)

pytestmark = pytest.mark.unit


# ---------- _compute_ars: weights and formula ----------

def test_weights_sum_to_one():
    """If this ever drifts, ARS stops being a 0..1 number and every downstream
    threshold comparison (min_ars, error budget) silently breaks."""
    assert WEIGHT_CORRECTNESS + WEIGHT_SAFETY + WEIGHT_LATENCY + WEIGHT_COST == pytest.approx(1.0)


def test_perfect_run_scores_ars_of_one():
    result = _compute_ars(
        correctness_passed=5, safety_passed=5, latency_passed=5, cost_passed=5, total=5,
    )
    assert result.ars == pytest.approx(1.0)
    assert result.correctness == 1.0
    assert result.safety == 1.0
    assert result.latency == 1.0
    assert result.cost == 1.0


def test_total_failure_scores_ars_of_zero():
    result = _compute_ars(
        correctness_passed=0, safety_passed=0, latency_passed=0, cost_passed=0, total=5,
    )
    assert result.ars == 0.0


def test_correctness_is_weighted_highest():
    """The foundational doc's whole point in weighting correctness at 0.4 (double
    every other term) must actually show up in the arithmetic."""
    only_correctness = _compute_ars(
        correctness_passed=5, safety_passed=0, latency_passed=0, cost_passed=0, total=5,
    )
    only_safety = _compute_ars(
        correctness_passed=0, safety_passed=5, latency_passed=0, cost_passed=0, total=5,
    )
    assert only_correctness.ars == pytest.approx(0.4)
    assert only_safety.ars == pytest.approx(0.2)
    assert only_correctness.ars > only_safety.ars


def test_formula_matches_foundational_document_exactly():
    """0.4*correctness + 0.2*safety + 0.2*latency + 0.2*cost, worked by hand."""
    result = _compute_ars(
        correctness_passed=8, safety_passed=9, latency_passed=10, cost_passed=7, total=10,
    )
    expected = 0.4 * 0.8 + 0.2 * 0.9 + 0.2 * 1.0 + 0.2 * 0.7
    assert result.ars == pytest.approx(expected)


def test_zero_total_returns_zero_not_a_division_error():
    result = _compute_ars(
        correctness_passed=0, safety_passed=0, latency_passed=0, cost_passed=0, total=0,
    )
    assert result.ars == 0.0
    assert "no case results" in result.detail


def test_detail_string_is_legible():
    """This is the string a future dashboard breaks down for a user -- it must name
    every sub-score, not just report the composite number."""
    result = _compute_ars(
        correctness_passed=3, safety_passed=4, latency_passed=5, cost_passed=5, total=5,
    )
    assert "correctness" in result.detail
    assert "safety" in result.detail
    assert "latency" in result.detail
    assert "cost" in result.detail


# ---------- compute_error_budget: SRE mechanics ----------

def test_no_snapshots_yet_is_not_exhausted():
    result = compute_error_budget([])
    assert result.exhausted is False
    assert result.window_size == 0
    assert "no ARS snapshots" in result.detail


def test_all_runs_above_target_never_exhausts():
    result = compute_error_budget(
        [0.95, 0.96, 0.94, 0.97], target_ars=0.9, error_budget_pct=0.1,
    )
    assert result.exhausted is False
    assert result.breaches == 0


def test_budget_exhausted_when_breach_rate_exceeds_allowance():
    # 3/4 runs below target (0.75 breach rate) vs a 10% allowed budget.
    result = compute_error_budget(
        [0.5, 0.6, 0.55, 0.95], target_ars=0.9, error_budget_pct=0.1,
    )
    assert result.breaches == 3
    assert result.breach_rate == pytest.approx(0.75)
    assert result.exhausted is True


def test_budget_not_exhausted_when_breach_rate_is_within_allowance():
    # 1/10 runs below target = exactly the 10% allowance -- must NOT exhaust
    # ("exceeds," not "meets or exceeds," matches every other threshold in this
    # codebase using strict > for "exceeds max").
    scores = [0.95] * 9 + [0.5]
    result = compute_error_budget(scores, target_ars=0.9, error_budget_pct=0.1)
    assert result.breach_rate == pytest.approx(0.1)
    assert result.exhausted is False


def test_budget_exhausted_just_over_the_allowance():
    scores = [0.95] * 8 + [0.5, 0.5]  # 2/10 = 0.2 > 0.1 allowed
    result = compute_error_budget(scores, target_ars=0.9, error_budget_pct=0.1)
    assert result.exhausted is True


def test_a_score_exactly_at_target_is_not_a_breach():
    """Same '< min' vs '<= min' convention as _compute_gate_result's pass_rate
    check -- exactly meeting the target is meeting the SLO, not violating it."""
    result = compute_error_budget([0.9, 0.9, 0.9], target_ars=0.9, error_budget_pct=0.0)
    assert result.breaches == 0
    assert result.exhausted is False


def test_budget_remaining_pct_never_goes_negative():
    result = compute_error_budget(
        [0.1, 0.1, 0.1], target_ars=0.9, error_budget_pct=0.1,
    )
    assert result.budget_remaining_pct == 0.0


def test_budget_remaining_pct_reflects_unused_budget():
    result = compute_error_budget([0.95, 0.95], target_ars=0.9, error_budget_pct=0.2)
    assert result.budget_remaining_pct == pytest.approx(0.2)


def test_defaults_are_importable_and_sane():
    assert 0.0 < DEFAULT_TARGET_ARS <= 1.0
    assert 0.0 <= DEFAULT_ERROR_BUDGET_PCT <= 1.0


def test_single_breaching_snapshot_with_zero_tolerance_exhausts():
    result = compute_error_budget([0.5], target_ars=0.9, error_budget_pct=0.0)
    assert result.exhausted is True
    assert result.window_size == 1


def test_detail_names_the_breach_count_and_rate():
    result = compute_error_budget([0.5, 0.95], target_ars=0.9, error_budget_pct=0.1)
    assert "1/2" in result.detail
