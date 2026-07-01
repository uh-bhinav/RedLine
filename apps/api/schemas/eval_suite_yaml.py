"""
Pydantic models for the eval suite YAML format (Phase1 roadmap Section 8).

These exist to validate a suite file's shape before anything touches the database --
a malformed YAML should fail loudly here, not produce a half-written suite.
"""
from __future__ import annotations

from pydantic import BaseModel


class TurnYAML(BaseModel):
    role: str
    content: str


class ExpectationsYAML(BaseModel):
    contains: list[str] | None = None
    must_not_contain: list[str] | None = None
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None
    judge_rubric: str | None = None


class EvalCaseYAML(BaseModel):
    case_key: str
    description: str | None = None
    turns: list[TurnYAML]
    expectations: ExpectationsYAML


class EvalSuiteYAML(BaseModel):
    suite: str
    agent: str
    cases: list[EvalCaseYAML]