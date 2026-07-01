"""latency scorer (Phase1 roadmap Section 9). Checks total transcript latency against
expectations.max_latency_ms. Sums latency_ms across all assistant turns -- a multi-turn
case's latency is the total session latency, not just the last turn."""
from __future__ import annotations

from apps.api.models.eval import EvalCase
from apps.api.services.scorers.base import ScorerResult, Turn


class LatencyScorer:
    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        max_latency = case.expectations.get("max_latency_ms")
        if max_latency is None:
            return ScorerResult(passed=True, detail="no max_latency_ms expectation configured")

        total_latency = sum(t.latency_ms or 0 for t in transcript if t.role == "assistant")
        if total_latency <= max_latency:
            return ScorerResult(passed=True, detail=f"total latency {total_latency}ms <= max {max_latency}ms")
        return ScorerResult(
            passed=False, detail=f"total latency {total_latency}ms exceeds max {max_latency}ms"
        )