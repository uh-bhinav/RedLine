"""
Unit tests for ChaosAdapter (Phase 4 Section 3).

No network, no LLM, no real agent -- wraps a tiny stub AgentAdapter so every fault
mode's exact effect on the returned AgentTurnResult (and on session_state) can be
asserted deterministically.

Run from the repo root:
    pytest apps/api/tests/unit/test_chaos_adapter.py -v -m unit
"""
import random

import pytest

from apps.api.services.adapters.base import AgentTurnResult, ToolCall
from apps.api.services.adapters.chaos_adapter import (
    CHAOS_MARKER_TOOL_NAME,
    ChaosAdapter,
    FaultMode,
    has_chaos_marker,
)

pytestmark = pytest.mark.unit


class _StubAdapter:
    """Records every call it receives and always answers the same way, unless told
    to mutate session_state so tests can prove chaos left it untouched."""

    def __init__(self, mutate_state: bool = True):
        self.calls: list[tuple[dict, str]] = []
        self._mutate_state = mutate_state

    def run_turn(self, session_state: dict, user_message: str) -> AgentTurnResult:
        self.calls.append((dict(session_state), user_message))
        if self._mutate_state:
            session_state["seen"] = session_state.get("seen", 0) + 1
        return AgentTurnResult(
            assistant_message=f"real answer to: {user_message}",
            tool_calls=[ToolCall(name="real_tool", arguments={}, result="ok", latency_ms=1)],
            latency_ms=100,
            cost_usd=0.001,
        )


# ---------- construction ----------

def test_rejects_probability_outside_zero_one():
    stub = _StubAdapter()
    with pytest.raises(ValueError, match="probability"):
        ChaosAdapter(stub, mode=FaultMode.TIMEOUT, probability=1.5)
    with pytest.raises(ValueError, match="probability"):
        ChaosAdapter(stub, mode=FaultMode.TIMEOUT, probability=-0.1)


# ---------- deterministic selection via target_turn_indices ----------

def test_target_turn_indices_faults_only_those_calls():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.TIMEOUT, target_turn_indices={1})

    r0 = chaos.run_turn({}, "turn 0")   # call_index 0 -- not targeted
    r1 = chaos.run_turn({}, "turn 1")   # call_index 1 -- targeted
    r2 = chaos.run_turn({}, "turn 2")   # call_index 2 -- not targeted

    assert not has_chaos_marker([tc.model_dump() for tc in r0.tool_calls])
    assert has_chaos_marker([tc.model_dump() for tc in r1.tool_calls])
    assert not has_chaos_marker([tc.model_dump() for tc in r2.tool_calls])
    assert len(stub.calls) == 2, "the real adapter must not be called for a targeted timeout turn"


def test_probability_one_faults_every_call():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.TIMEOUT, probability=1.0)
    for i in range(5):
        result = chaos.run_turn({}, f"turn {i}")
        assert has_chaos_marker([tc.model_dump() for tc in result.tool_calls])
    assert stub.calls == []


def test_probability_zero_never_faults():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.TIMEOUT, probability=0.0)
    for i in range(5):
        result = chaos.run_turn({}, f"turn {i}")
        assert not has_chaos_marker([tc.model_dump() for tc in result.tool_calls])
    assert len(stub.calls) == 5


def test_probability_respects_an_injected_rng_for_reproducibility():
    stub_a = _StubAdapter()
    stub_b = _StubAdapter()
    chaos_a = ChaosAdapter(stub_a, mode=FaultMode.TIMEOUT, probability=0.5, rng=random.Random(42))
    chaos_b = ChaosAdapter(stub_b, mode=FaultMode.TIMEOUT, probability=0.5, rng=random.Random(42))

    faulted_a = [has_chaos_marker([tc.model_dump() for tc in chaos_a.run_turn({}, "x").tool_calls])
                 for _ in range(10)]
    faulted_b = [has_chaos_marker([tc.model_dump() for tc in chaos_b.run_turn({}, "x").tool_calls])
                 for _ in range(10)]
    assert faulted_a == faulted_b, "same seed must produce the same fault pattern"


# ---------- total-failure modes: real adapter never called, session untouched ----------

@pytest.mark.parametrize("mode", [FaultMode.TIMEOUT, FaultMode.CONNECTION_RESET])
def test_total_failure_modes_never_call_the_real_adapter(mode):
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=mode)
    chaos.run_turn({}, "hello")
    assert stub.calls == []


def test_total_failure_modes_leave_session_state_completely_untouched():
    stub = _StubAdapter(mutate_state=True)
    chaos = ChaosAdapter(stub, mode=FaultMode.TIMEOUT)

    state = {"history": ["previous turn"], "seen": 3}
    original = dict(state)
    chaos.run_turn(state, "hello")

    assert state == original, "a total-failure fault must not mutate session_state at all"


def test_timeout_response_carries_the_marker_and_no_real_content():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.TIMEOUT, latency_penalty_ms=9000)
    result = chaos.run_turn({}, "hello")

    assert has_chaos_marker([tc.model_dump() for tc in result.tool_calls])
    assert "timeout" in result.assistant_message.lower()
    assert result.latency_ms == 9000
    assert result.cost_usd == 0.0


def test_connection_reset_is_distinguishable_from_timeout_in_the_marker():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.CONNECTION_RESET)
    result = chaos.run_turn({}, "hello")
    marker = next(tc for tc in result.tool_calls if tc.name == CHAOS_MARKER_TOOL_NAME)
    assert marker.arguments["mode"] == "connection_reset"


# ---------- modes that call through: real logic runs, only what's returned changes ----------

def test_malformed_response_calls_the_real_adapter_and_corrupts_the_text():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.MALFORMED_RESPONSE)
    result = chaos.run_turn({}, "hello")

    assert len(stub.calls) == 1, "the agent must actually run for this fault family"
    assert "real answer" not in result.assistant_message or len(result.assistant_message) < len(
        "real answer to: hello"
    ) + 20
    assert has_chaos_marker([tc.model_dump() for tc in result.tool_calls])
    # The agent's own tool call is preserved alongside the marker, not replaced.
    assert any(tc.name == "real_tool" for tc in result.tool_calls)


def test_malformed_response_preserves_latency_and_cost():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.MALFORMED_RESPONSE)
    result = chaos.run_turn({}, "hello")
    assert result.latency_ms == 100
    assert result.cost_usd == 0.001


def test_plausible_wrong_calls_the_real_adapter_and_replaces_the_text():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.PLAUSIBLE_WRONG)
    result = chaos.run_turn({}, "hello")

    assert len(stub.calls) == 1
    assert "real answer" not in result.assistant_message
    assert has_chaos_marker([tc.model_dump() for tc in result.tool_calls])


def test_latency_injection_calls_through_and_preserves_the_real_answer():
    stub = _StubAdapter()
    chaos = ChaosAdapter(stub, mode=FaultMode.LATENCY_INJECTION, latency_penalty_ms=4000)
    result = chaos.run_turn({}, "hello")

    assert len(stub.calls) == 1
    assert result.assistant_message == "real answer to: hello", (
        "latency injection must not alter the agent's real content"
    )
    assert result.latency_ms == 100 + 4000
    assert has_chaos_marker([tc.model_dump() for tc in result.tool_calls])


def test_calls_through_modes_do_mutate_session_state_normally():
    """Unlike the total-failure family, these modes let the real agent run, so its
    normal session_state effects must still happen."""
    stub = _StubAdapter(mutate_state=True)
    chaos = ChaosAdapter(stub, mode=FaultMode.PLAUSIBLE_WRONG)

    state: dict = {}
    chaos.run_turn(state, "hello")
    assert state == {"seen": 1}


# ---------- has_chaos_marker helper ----------

def test_has_chaos_marker_handles_none_and_empty():
    assert has_chaos_marker(None) is False
    assert has_chaos_marker([]) is False


def test_has_chaos_marker_true_only_for_the_reserved_name():
    assert has_chaos_marker([{"name": "real_tool"}]) is False
    assert has_chaos_marker([{"name": "real_tool"}, {"name": CHAOS_MARKER_TOOL_NAME}]) is True
