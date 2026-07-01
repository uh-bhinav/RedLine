"""cost scorer (Phase1 roadmap Section 9). Checks total transcript cost against
expectations.max_cost_usd. Sums cost_usd across all assistant turns -- a multi-turn
case's cost is the cost of the whole session, not just the last turn."""
from __future__ import annotations

from apps.api.models.eval import EvalCase
from apps.api.services.scorers.base import ScorerResult, Turn


class CostScorer:
    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        max_cost = case.expectations.get("max_cost_usd")
        if max_cost is None:
            return ScorerResult(passed=True, detail="no max_cost_usd expectation configured")

        total_cost = sum(t.cost_usd or 0.0 for t in transcript if t.role == "assistant")
        if total_cost <= max_cost:
            return ScorerResult(passed=True, detail=f"total cost ${total_cost:.6f} <= max ${max_cost}")
        return ScorerResult(passed=False, detail=f"total cost ${total_cost:.6f} exceeds max ${max_cost}")