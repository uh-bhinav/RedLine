"""
The Scorer abstraction (Phase1 roadmap Section 9) — STABLE CONTRACT.

Each scorer implements one method: score(case, transcript) -> ScorerResult.
The Eval Engine (Section 10) runs every scorer configured in a case's `expectations`
block and a case passes only if ALL configured scorers pass.
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from apps.api.models.eval import EvalCase


class Turn(BaseModel):
    """One turn of a transcript, as consumed by scorers. Built by the Eval Engine
    from each AgentTurnResult plus the scripted user turn that preceded it.
    tool_calls/latency_ms/cost_usd are only populated on assistant turns."""

    role: str  # "user" | "assistant"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None


class ScorerResult(BaseModel):
    passed: bool
    detail: str


class Scorer(Protocol):
    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        ...