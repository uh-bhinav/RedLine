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
from apps.api.models.eval import EvalCase
from apps.api.services.scorers.base import ScorerResult, Turn

JUDGE_MODEL = "gemini-2.5-flash"


class JudgeVerdict(BaseModel):
    """Flat by design -- response_schema with nested Pydantic models has a known
    bug in google-genai (unresolved $ref/$defs). Keeping this flat avoids it."""

    passed: bool
    reasoning: str


class LLMJudgeScorer:
    def __init__(self):
        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult:
        rubric = case.expectations.get("judge_rubric")
        if not rubric:
            return ScorerResult(passed=True, detail="no judge_rubric configured")

        transcript_text = "\n".join(f"{t.role}: {t.content}" for t in transcript)
        prompt = (
            "You are a strict QA grader for an AI agent's conversation. Judge ONLY "
            "against the rubric below -- do not be lenient, and do not assume good "
            "intent if the transcript doesn't actually satisfy the rubric.\n\n"
            f"Rubric: {rubric}\n\n"
            f"Conversation transcript:\n{transcript_text}\n\n"
            "Does this conversation satisfy the rubric?"
        )

        response = self._client.models.generate_content(
            model=JUDGE_MODEL,
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