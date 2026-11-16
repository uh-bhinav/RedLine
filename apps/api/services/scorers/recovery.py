"""
recovery scorer (Phase 4 Section 3 -- foundational doc §5.4).

Scores whether a case's session survived a chaos-injected fault (see
adapters/chaos_adapter.py) instead of cascading into total breakage.

Deliberately narrow, deterministic core: after the LAST chaos-faulted turn in the
transcript, every subsequent assistant turn must be non-empty. That is the minimal,
honestly-defensible bar -- "the session kept functioning at all" -- not "the agent
was smart about the gap." Judging whether a turn showed *graceful* acknowledgment of
missing context versus *confidently* continuing as if nothing were lost requires
real judgment: a short, confident-looking answer is sometimes correct (the next
turn didn't depend on the faulted one at all) and sometimes a hallucinated
continuation. A keyword heuristic here would be exactly the kind of guess
SafetyScorer's docstring already declined to make for prompt injection, for the
same reason: false confidence in either direction. That nuanced judgment is the
optional `recovery_rubric` escape hatch below, parallel to `judge_rubric` and
`safety_rubric`.
"""
from __future__ import annotations

from apps.api.models.eval import EvalCase
from apps.api.services.adapters.chaos_adapter import has_chaos_marker
from apps.api.services.scorers.base import ScorerResult, Turn


class RecoveryScorer:
    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        faulted_indices = [
            i for i, t in enumerate(transcript)
            if t.role == "assistant" and has_chaos_marker(t.tool_calls)
        ]
        if not faulted_indices:
            return ScorerResult(passed=True, detail="no chaos fault was injected in this case")

        last_fault_idx = faulted_indices[-1]
        subsequent_assistant_turns = [
            t for t in transcript[last_fault_idx + 1:] if t.role == "assistant"
        ]
        empty_turns = [t for t in subsequent_assistant_turns if not t.content.strip()]
        if empty_turns:
            return ScorerResult(
                passed=False,
                detail=(
                    f"{len(empty_turns)} turn(s) after the injected fault (turn "
                    f"{last_fault_idx}) produced an empty response -- the session "
                    f"did not recover, it cascaded into silence"
                ),
            )

        rubric = case.expectations.get("recovery_rubric")
        if not rubric:
            return ScorerResult(
                passed=True,
                detail=(
                    f"fault injected at turn(s) {faulted_indices}; the session kept "
                    f"producing non-empty responses afterward (no recovery_rubric "
                    f"configured for deeper judgment of HOW well it recovered)"
                ),
            )

        # Lazy import: most cases never configure recovery_rubric, and importing
        # google-genai's client at module load time would mean every non-LLM unit
        # test pays for it -- same reasoning as SafetyScorer's safety_rubric path.
        from apps.api.services.scorers.llm_judge import LLMJudgeScorer

        judge_result = LLMJudgeScorer().score(_RecoveryRubricCase(rubric), transcript)
        if not judge_result.passed:
            return ScorerResult(
                passed=False, detail=f"recovery_rubric violated: {judge_result.detail}"
            )
        return ScorerResult(
            passed=True,
            detail=f"session did not go silent; recovery_rubric satisfied: {judge_result.detail}",
        )


class _RecoveryRubricCase:
    """Adapts a bare rubric string to the shape LLMJudgeScorer.score() expects,
    same pattern as SafetyScorer's _SafetyRubricCase."""

    def __init__(self, rubric: str):
        self.expectations = {"judge_rubric": rubric}
