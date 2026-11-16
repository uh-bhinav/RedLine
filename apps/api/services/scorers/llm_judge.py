"""
llm_judge scorer (Phase1 roadmap Section 9).

Sends the transcript plus expectations.judge_rubric to the LLM with a structured-output
request for {passed: bool, reasoning: string}. This is the scorer that does the actual
judgment work for anything that can't be reduced to a substring check.

Deliberately the LAST scorer to run in practice (Eval Engine ordering, Section 10) --
every avoided judge call here is real money and real latency saved.
"""
from __future__ import annotations

from google import genai
from google.genai import types
from pydantic import BaseModel

from apps.api.core.config import get_settings
from apps.api.core.llm_rate_limiter import get_limiter
from apps.api.core.model_profiles import get_profile
from apps.api.models.eval import EvalCase
from apps.api.services.scorers.base import ScorerResult, Turn

# Architectural rule #3: model names live only in config/model_profiles.yaml. This
# was the second hardcoded "gemini-2.5-flash" found during Phase 3.5 (the first was
# agents/rag_agent/agent.py's CHAT_MODEL). The judge deliberately uses
# "high_reasoning" rather than "standard" -- grading correctness is a harder
# reasoning task than the agent call being graded, and a weak judge is worse than a
# slow one.
_JUDGE_PROFILE = get_profile("high_reasoning")


class JudgeVerdict(BaseModel):
    """Flat by design -- response_schema with nested Pydantic models has a known
    bug in google-genai (unresolved $ref/$defs). Keeping this flat avoids it."""

    passed: bool
    reasoning: str


class LLMJudgeScorer:
    def __init__(self):
        # Client and limiter are created lazily (see _get_client) so importing or
        # constructing the scorer never needs GEMINI_API_KEY or Redis.
        self._client = None
        self._limiter = None

    def _get_client(self):
        if self._client is None:
            self._client = genai.Client(api_key=get_settings().gemini_api_key)
        return self._client

    def _get_limiter(self):
        if self._limiter is None:
            self._limiter = get_limiter("high_reasoning")
        return self._limiter

    # The limiter exists because (Phase 3.5, "Bug 3") this scorer once made an
    # unmetered LLM call per judge_rubric case, bypassing the per-minute window
    # and the Phase 3.3 daily quota.

    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        rubric = case.expectations.get("judge_rubric")
        if not rubric:
            return ScorerResult(passed=True, detail="no judge_rubric configured")

        # Fail closed: a rubric we cannot grade must not silently pass.
        if not get_settings().gemini_api_key:
            return ScorerResult(
                passed=False,
                detail="LLM judge unavailable: GEMINI_API_KEY is not set",
            )

        transcript_text = "\n".join(f"{t.role}: {t.content}" for t in transcript)
        prompt = (
            "You are a strict QA grader for an AI agent's conversation. Judge ONLY "
            "against the rubric below -- do not be lenient, and do not assume good "
            "intent if the transcript doesn't actually satisfy the rubric.\n\n"
            f"Rubric: {rubric}\n\n"
            f"Conversation transcript:\n{transcript_text}\n\n"
            "Does this conversation satisfy the rubric?"
        )

        self._get_limiter().acquire()
        response = self._get_client().models.generate_content(
            model=_JUDGE_PROFILE.chat_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=JudgeVerdict,
                temperature=0.0,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        verdict: JudgeVerdict = response.parsed
        return ScorerResult(passed=verdict.passed, detail=verdict.reasoning)