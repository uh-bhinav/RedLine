"""
Pydantic models for the eval suite YAML format (Phase1 roadmap Section 8).

These exist to validate a suite file's shape before anything touches the database --
a malformed YAML should fail loudly here, not produce a half-written suite.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class TurnYAML(BaseModel):
    role: str
    content: str


class ChaosConfigYAML(BaseModel):
    """Phase 4 Section 3 -- configures ChaosAdapter for this case.

    mode is validated against FaultMode's actual values (not hardcoded here a
    second time) so a typo in a suite YAML fails at push time, not at eval-run
    time deep inside the adapter.
    """
    mode: str
    probability: float = 1.0
    target_turn_indices: list[int] | None = None
    latency_penalty_ms: int = 5000

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        from apps.api.services.adapters.chaos_adapter import FaultMode
        valid = {m.value for m in FaultMode}
        if v not in valid:
            raise ValueError(f"unknown chaos mode '{v}' -- must be one of {sorted(valid)}")
        return v

    @field_validator("probability")
    @classmethod
    def _validate_probability(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"probability must be in [0.0, 1.0], got {v}")
        return v


class ExpectationsYAML(BaseModel):
    contains: list[str] | None = None
    must_not_contain: list[str] | None = None
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None
    judge_rubric: str | None = None
    safety_rubric: str | None = None  # Phase 4 Section 1 -- SafetyScorer's optional judge escape hatch
    recovery_rubric: str | None = None  # Phase 4 Section 3 -- RecoveryScorer's optional judge escape hatch
    chaos: ChaosConfigYAML | None = None  # Phase 4 Section 3 -- configures ChaosAdapter for this case


class EvalCaseYAML(BaseModel):
    case_key: str
    description: str | None = None
    turns: list[TurnYAML]
    expectations: ExpectationsYAML


class EvalSuiteYAML(BaseModel):
    suite: str
    agent: str
    cases: list[EvalCaseYAML]