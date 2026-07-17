"""
Drift detection service (Phase 2 Section 9 -- Holy Grail §5.6).

detect_model_drift() is a pure function: given a list of recent snapshots and a
threshold, it returns a DriftDetectionResult. No DB, no side effects. The
scheduler process calls it and decides whether to persist a DriftAlert.

Phase 2 implements model drift only (scheduled re-runs of the reference eval
suite, score comparison). Behavior drift and RAG drift are Phase 3.

Drift threshold design:
  The default threshold (0.10 = 10 percentage points) is calibrated against the
  observation that LLM providers rarely cause >5pp regressions on typical task
  suites from routine model updates, but genuine capability regressions or
  prompt-breaking changes tend to move scores by 10-20pp. A 10pp threshold
  catches real problems while avoiding false positives from LLM non-determinism.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_DRIFT_THRESHOLD = 0.10  # 10 percentage points
BASELINE_WINDOW = 5             # compare against the mean of the last N snapshots


@dataclass
class DriftDetectionResult:
    drifted: bool
    baseline_pass_rate: float
    current_pass_rate: float
    delta: float           # negative = regression, positive = improvement
    threshold: float
    detail: str


def detect_model_drift(
    recent_pass_rates: list[float],
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> DriftDetectionResult:
    """
    Pure function: takes a list of recent pass_rates (oldest first, newest last)
    and returns a DriftDetectionResult.

    Requires at least 2 snapshots (one for the baseline, one current).
    The baseline is the mean of all snapshots except the most recent.
    The current score is the most recent snapshot.
    Drift is detected if |current - baseline| >= threshold AND current < baseline
    (regressions are drift; improvements are not alerted, just logged).

    Args:
        recent_pass_rates: List of pass_rate floats, oldest first. Must have >= 2.
        threshold: How many percentage points of regression trigger an alert.
    """
    if len(recent_pass_rates) < 2:
        return DriftDetectionResult(
            drifted=False,
            baseline_pass_rate=0.0,
            current_pass_rate=recent_pass_rates[0] if recent_pass_rates else 0.0,
            delta=0.0,
            threshold=threshold,
            detail="not enough snapshots for comparison (need >= 2)",
        )

    # Baseline = mean of all snapshots except the most recent
    baseline_scores = recent_pass_rates[:-1]
    baseline = sum(baseline_scores) / len(baseline_scores)
    current = recent_pass_rates[-1]
    delta = current - baseline  # negative = regression

    drifted = delta <= -threshold  # only alert on regressions

    if drifted:
        detail = (
            f"pass_rate dropped from {baseline:.3f} (baseline over {len(baseline_scores)} runs) "
            f"to {current:.3f} (delta={delta:+.3f}, threshold={threshold:.3f})"
        )
    elif delta > 0:
        detail = f"pass_rate improved from {baseline:.3f} to {current:.3f} (delta={delta:+.3f})"
    else:
        detail = f"pass_rate stable: {current:.3f} vs baseline {baseline:.3f} (delta={delta:+.3f})"

    return DriftDetectionResult(
        drifted=drifted,
        baseline_pass_rate=baseline,
        current_pass_rate=current,
        delta=delta,
        threshold=threshold,
        detail=detail,
    )