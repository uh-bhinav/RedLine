"""A second zero-cost fixture agent, distinct from dummy_agent.py, whose responses
are deliberately different text for the same input.

Exists only for test_diff_engine_end_to_end.py's silent-drift scenario: registering
this under the SAME content_hash as dummy_agent.py simulates the exact real-world
case the Behavioral Diff Engine's alarm exists for -- the platform's code-change
signal (content_hash) says nothing changed, but the agent's actual output did.
"""
from apps.api.services.adapters.base import AgentTurnResult, ToolCall


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    turn_count = session_state.get("turn_count", 0) + 1
    session_state["turn_count"] = turn_count
    return AgentTurnResult(
        assistant_message=(
            f"After careful consideration, my answer to '{user_message}' is "
            f"completely different from before (turn {turn_count})"
        ),
        tool_calls=[
            ToolCall(name="noop_tool", arguments={"echo": user_message}, result="ok", latency_ms=1)
        ],
        latency_ms=5,
        cost_usd=0.0001,
    )
