"""A third zero-cost fixture agent whose output is controlled by a module-level
flag the test flips between two eval runs of the SAME registered agent version.

Exists only for test_diff_engine_end_to_end.py's over-time silent-drift scenario.
compute_diff_over_time() compares the SAME agent_version_id across two of its own
completed runs -- the only way "code did not change" is representable at all, given
agent_versions' UNIQUE(agent_id, content_hash) constraint. To get a REAL (not
fabricated) similarity drop between those two runs without a live LLM's
non-determinism, this fixture's actual output changes between calls, simulating
exactly what a real silent-drift event is: the SAME registered version answering
differently because something external (here, this test) changed, not because
anyone edited the agent's code.
"""
from apps.api.services.adapters.base import AgentTurnResult, ToolCall

# Mutated directly by the test between eval runs -- deliberately global and
# deliberately test-only. Never do this in real agent code.
MODE = "v1"

_RESPONSES = {
    "v1": "Our refund window is 30 days from the date of purchase.",
    "v2": "We do not offer refunds under any circumstances after purchase.",
}


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    turn_count = session_state.get("turn_count", 0) + 1
    session_state["turn_count"] = turn_count
    return AgentTurnResult(
        assistant_message=_RESPONSES[MODE],
        tool_calls=[
            ToolCall(name="noop_tool", arguments={"echo": user_message}, result="ok", latency_ms=1)
        ],
        latency_ms=5,
        cost_usd=0.0001,
    )
