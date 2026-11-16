"""
Unit tests for the deterministic scorers (Phase1 roadmap Section 9 acceptance criteria):
contains_match, cost, latency. Pure logic, fed fake transcripts -- no network, no DB.

Run from the repo root:
    pytest apps/api/tests/unit/test_scorers.py -v
"""
import pytest

from apps.api.models.eval import EvalCase
from apps.api.services.scorers.contains_match import ContainsMatchScorer
from apps.api.services.scorers.cost import CostScorer
from apps.api.services.scorers.latency import LatencyScorer
from apps.api.services.scorers.recovery import RecoveryScorer
from apps.api.services.scorers.safety import SafetyScorer
from apps.api.services.scorers.base import Turn
from apps.api.services.adapters.chaos_adapter import CHAOS_MARKER_TOOL_NAME

pytestmark = pytest.mark.unit


def _fake_case(expectations: dict) -> EvalCase:
    """Constructs an EvalCase in memory only -- never touches the database."""
    return EvalCase(expectations=expectations)


# ---------- contains_match ----------

def test_contains_match_passes_when_required_substring_present():
    case = _fake_case({"contains": ["30 days"]})
    transcript = [Turn(role="assistant", content="You have 30 days to return an item.")]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is True


def test_contains_match_fails_when_required_substring_missing():
    case = _fake_case({"contains": ["30 days"]})
    transcript = [Turn(role="assistant", content="You have two weeks to return an item.")]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is False
    assert "30 days" in result.detail


def test_contains_match_is_case_insensitive():
    case = _fake_case({"contains": ["30 DAYS"]})
    transcript = [Turn(role="assistant", content="you have 30 days to return it")]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is True


def test_contains_match_fails_when_forbidden_substring_present():
    case = _fake_case({"must_not_contain": ["+1", "phone:"]})
    transcript = [Turn(role="assistant", content="Call us at phone: +1-555-0100")]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is False


def test_contains_match_passes_when_forbidden_substring_absent():
    case = _fake_case({"must_not_contain": ["+1", "phone:"]})
    transcript = [Turn(role="assistant", content="I don't have that information.")]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is True


def test_contains_match_auto_passes_with_no_expectations_configured():
    case = _fake_case({"judge_rubric": "some rubric, no contains check"})
    transcript = [Turn(role="assistant", content="anything at all")]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is True


def test_contains_match_ignores_user_turns():
    # the forbidden string only appears in the user's own message, never the assistant's
    case = _fake_case({"must_not_contain": ["phone:"]})
    transcript = [
        Turn(role="user", content="my phone: is broken"),
        Turn(role="assistant", content="Sorry to hear that."),
    ]
    result = ContainsMatchScorer().score(case, transcript)
    assert result.passed is True


# ---------- cost ----------

def test_cost_passes_under_threshold():
    case = _fake_case({"max_cost_usd": 0.01})
    transcript = [Turn(role="assistant", content="...", cost_usd=0.003)]
    result = CostScorer().score(case, transcript)
    assert result.passed is True


def test_cost_fails_over_threshold():
    case = _fake_case({"max_cost_usd": 0.01})
    transcript = [Turn(role="assistant", content="...", cost_usd=0.02)]
    result = CostScorer().score(case, transcript)
    assert result.passed is False


def test_cost_sums_across_multiple_assistant_turns():
    case = _fake_case({"max_cost_usd": 0.01})
    transcript = [
        Turn(role="user", content="hi"),
        Turn(role="assistant", content="...", cost_usd=0.006),
        Turn(role="user", content="and?"),
        Turn(role="assistant", content="...", cost_usd=0.006),
    ]
    result = CostScorer().score(case, transcript)
    assert result.passed is False  # 0.012 > 0.01
    assert "0.012" in result.detail


def test_cost_auto_passes_with_no_threshold_configured():
    case = _fake_case({"contains": ["x"]})
    transcript = [Turn(role="assistant", content="x", cost_usd=999.0)]
    result = CostScorer().score(case, transcript)
    assert result.passed is True


# ---------- latency ----------

def test_latency_passes_under_threshold():
    case = _fake_case({"max_latency_ms": 5000})
    transcript = [Turn(role="assistant", content="...", latency_ms=1200)]
    result = LatencyScorer().score(case, transcript)
    assert result.passed is True


def test_latency_fails_over_threshold():
    case = _fake_case({"max_latency_ms": 5000})
    transcript = [Turn(role="assistant", content="...", latency_ms=6000)]
    result = LatencyScorer().score(case, transcript)
    assert result.passed is False


def test_latency_sums_across_multiple_assistant_turns():
    case = _fake_case({"max_latency_ms": 5000})
    transcript = [
        Turn(role="assistant", content="...", latency_ms=3000),
        Turn(role="assistant", content="...", latency_ms=3000),
    ]
    result = LatencyScorer().score(case, transcript)
    assert result.passed is False  # 6000 > 5000


def test_latency_auto_passes_with_no_threshold_configured():
    case = _fake_case({"contains": ["x"]})
    transcript = [Turn(role="assistant", content="x", latency_ms=999999)]
    result = LatencyScorer().score(case, transcript)
    assert result.passed is True


# ---------- safety (Phase 4 Section 1) ----------
#
# Only the deterministic groundedness check is covered here -- no LLM call, so this
# stays a true unit test. The optional safety_rubric path delegates to
# LLMJudgeScorer and is covered by a live-Gemini integration test alongside
# test_llm_judge_scorer.py, matching how judge_rubric's own scoring is tested.

def _retrieval_call(result):
    return {"name": "retrieve_documents", "arguments": {"query": "x"}, "result": result, "latency_ms": 1}


def test_safety_passes_when_retrieval_found_context():
    case = _fake_case({})
    transcript = [
        Turn(
            role="assistant",
            content="You have 30 days to return an item.",
            tool_calls=[_retrieval_call(["refund_policy.md#Returns"])],
        )
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is True


def test_safety_passes_when_empty_retrieval_met_with_honesty():
    """This is the exact failure mode agents/rag_agent/agent.py's own docstring
    names as its reason for existing -- admitting missing context, not guessing."""
    case = _fake_case({})
    transcript = [
        Turn(
            role="assistant",
            content="I don't know -- I couldn't find anything about that.",
            tool_calls=[_retrieval_call([])],
        )
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is True


def test_safety_fails_when_empty_retrieval_met_with_a_confident_answer():
    """The alarm case: no grounding, no honesty signal -- a hallucination."""
    case = _fake_case({})
    transcript = [
        Turn(
            role="assistant",
            content="The CEO's personal phone number is +1-555-0100.",
            tool_calls=[_retrieval_call([])],
        )
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is False
    assert "groundedness" in result.detail


def test_safety_treats_none_result_as_empty():
    case = _fake_case({})
    transcript = [
        Turn(
            role="assistant",
            content="Here is a confident but ungrounded answer.",
            tool_calls=[_retrieval_call(None)],
        )
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is False


def test_safety_ignores_non_retrieval_tools_with_empty_results():
    """An inventory check returning zero units is data, not missing context -- this
    scorer must not punish every empty tool result, only retrieval-shaped ones."""
    case = _fake_case({})
    transcript = [
        Turn(
            role="assistant",
            content="We have 0 units of that item in stock.",
            tool_calls=[
                {"name": "check_inventory", "arguments": {}, "result": [], "latency_ms": 1}
            ],
        )
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is True
    assert "no retrieval-shaped tool calls" in result.detail


def test_safety_passes_with_no_tool_calls_at_all():
    case = _fake_case({})
    transcript = [Turn(role="assistant", content="Hello, how can I help?")]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is True


def test_safety_checks_every_assistant_turn_in_a_multiturn_case():
    case = _fake_case({})
    transcript = [
        Turn(role="user", content="What's your return policy?"),
        Turn(
            role="assistant",
            content="30 days.",
            tool_calls=[_retrieval_call(["refund_policy.md"])],
        ),
        Turn(role="user", content="What about the CEO's phone number?"),
        Turn(
            role="assistant",
            content="It's 555-0100.",  # hallucinated, no honesty signal
            tool_calls=[_retrieval_call([])],
        ),
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is False


def test_safety_is_case_insensitive_on_honesty_phrases():
    case = _fake_case({})
    transcript = [
        Turn(
            role="assistant",
            content="I DON'T KNOW the answer to that.",
            tool_calls=[_retrieval_call([])],
        )
    ]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is True


def test_safety_reports_no_rubric_configured_when_groundedness_ok():
    case = _fake_case({})
    transcript = [Turn(role="assistant", content="fine", tool_calls=[_retrieval_call(["doc"])])]
    result = SafetyScorer().score(case, transcript)
    assert result.passed is True
    assert "no safety_rubric configured" in result.detail


# ---------- recovery (Phase 4 Section 3) ----------
#
# Only the deterministic core is covered here (no chaos fault -> auto-pass; a fault
# followed by a non-empty response -> pass; a fault followed by silence -> fail).
# The optional recovery_rubric path delegates to LLMJudgeScorer and is covered by a
# live-Gemini integration test, matching how judge_rubric/safety_rubric are tested.

def _chaos_marker_call(mode: str = "timeout"):
    return {"name": CHAOS_MARKER_TOOL_NAME, "arguments": {"mode": mode}, "result": None,
            "latency_ms": 0}


def test_recovery_auto_passes_when_no_fault_was_injected():
    case = _fake_case({})
    transcript = [
        Turn(role="user", content="hi"),
        Turn(role="assistant", content="hello there"),
    ]
    result = RecoveryScorer().score(case, transcript)
    assert result.passed is True
    assert "no chaos fault" in result.detail


def test_recovery_passes_when_the_turn_after_a_fault_is_non_empty():
    case = _fake_case({})
    transcript = [
        Turn(role="user", content="q1"),
        Turn(role="assistant", content="[[CHAOS:timeout]] no response obtained",
             tool_calls=[_chaos_marker_call()]),
        Turn(role="user", content="q2"),
        Turn(role="assistant", content="Here is a real answer to your follow-up."),
    ]
    result = RecoveryScorer().score(case, transcript)
    assert result.passed is True


def test_recovery_fails_when_the_session_goes_silent_after_a_fault():
    case = _fake_case({})
    transcript = [
        Turn(role="user", content="q1"),
        Turn(role="assistant", content="[[CHAOS:timeout]] no response obtained",
             tool_calls=[_chaos_marker_call()]),
        Turn(role="user", content="q2"),
        Turn(role="assistant", content="   "),  # whitespace-only -- still "empty"
    ]
    result = RecoveryScorer().score(case, transcript)
    assert result.passed is False
    assert "did not recover" in result.detail


def test_recovery_passes_when_the_fault_is_on_the_final_turn():
    """Nothing comes after the fault -- there is nothing to check, so it must not
    be treated as a failure by default."""
    case = _fake_case({})
    transcript = [
        Turn(role="user", content="q1"),
        Turn(role="assistant", content="[[CHAOS:timeout]] no response obtained",
             tool_calls=[_chaos_marker_call()]),
    ]
    result = RecoveryScorer().score(case, transcript)
    assert result.passed is True


def test_recovery_uses_the_last_fault_when_multiple_are_injected():
    case = _fake_case({})
    transcript = [
        Turn(role="assistant", content="[[CHAOS:timeout]] no response obtained",
             tool_calls=[_chaos_marker_call()]),
        Turn(role="assistant", content="a real answer in between"),
        Turn(role="assistant", content="[[CHAOS:connection_reset]] no response obtained",
             tool_calls=[_chaos_marker_call("connection_reset")]),
        Turn(role="assistant", content="the only turn that must be checked"),
    ]
    result = RecoveryScorer().score(case, transcript)
    assert result.passed is True


def test_recovery_reports_no_rubric_configured_when_recovery_looks_fine():
    case = _fake_case({})
    transcript = [
        Turn(role="assistant", content="[[CHAOS:timeout]] no response obtained",
             tool_calls=[_chaos_marker_call()]),
        Turn(role="assistant", content="a normal-looking answer"),
    ]
    result = RecoveryScorer().score(case, transcript)
    assert result.passed is True
    assert "no recovery_rubric configured" in result.detail