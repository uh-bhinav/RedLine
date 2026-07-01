"""
Unit tests for the deterministic scorers (Phase1 roadmap Section 9 acceptance criteria):
contains_match, cost, latency. Pure logic, fed fake transcripts -- no network, no DB.

Run from the repo root:
    pytest apps/api/tests/unit/test_scorers.py -v
"""
from apps.api.models.eval import EvalCase
from apps.api.services.scorers.contains_match import ContainsMatchScorer
from apps.api.services.scorers.cost import CostScorer
from apps.api.services.scorers.latency import LatencyScorer
from apps.api.services.scorers.base import Turn


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