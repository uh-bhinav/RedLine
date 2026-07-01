"""
contains_match scorer (Phase1 roadmap Section 9).

Deterministic substring check against expectations.contains / must_not_contain.
Cheap and fast -- run first so obviously-broken cases fail without spending an
LLM call. Matching is case-insensitive, since failing a case over capitalization
("30 Days" vs "30 days") would be a false negative, not a real failure.
"""
from __future__ import annotations

from apps.api.models.eval import EvalCase
from apps.api.services.scorers.base import ScorerResult, Turn


class ContainsMatchScorer:
    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        expectations = case.expectations
        contains = expectations.get("contains")
        must_not_contain = expectations.get("must_not_contain")

        if not contains and not must_not_contain:
            return ScorerResult(passed=True, detail="no contains/must_not_contain expectations configured")

        assistant_text = " ".join(t.content for t in transcript if t.role == "assistant").lower()

        missing = [s for s in (contains or []) if s.lower() not in assistant_text]
        if missing:
            return ScorerResult(passed=False, detail=f"missing required substrings: {missing}")

        present = [s for s in (must_not_contain or []) if s.lower() in assistant_text]
        if present:
            return ScorerResult(passed=False, detail=f"contains forbidden substrings: {present}")

        return ScorerResult(passed=True, detail="all contains/must_not_contain checks passed")