"""A minimal stand-in agent used only to test LocalPythonAdapter in isolation,
before the real RAG agent (Section 7) exists."""
from apps.api.services.adapters.base import AgentTurnResult, ToolCall


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    turn_count = session_state.get("turn_count", 0) + 1
    session_state["turn_count"] = turn_count
    return AgentTurnResult(
        assistant_message=f"echo: {user_message} (turn {turn_count})",
        tool_calls=[
            ToolCall(name="noop_tool", arguments={"echo": user_message}, result="ok", latency_ms=1)
        ],
        latency_ms=5,
        cost_usd=0.0001,
    )