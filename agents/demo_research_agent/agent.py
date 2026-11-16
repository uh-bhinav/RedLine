"""
Demo research agent -- a 4-node chain, deterministic and key-free:

    planner -> retriever -> writer -> verifier

Each node is recorded as a tool call so the trace viewer shows the whole chain. The verifier
rejects a draft whose claim has no supporting source; that rejection propagates into the
final answer (the coordination-gap scenario the dashboard demo highlights).

Contract: run_turn(session_state, user_message) -> AgentTurnResult
(apps/api/services/adapters/base.py).
"""
from __future__ import annotations

from apps.api.services.adapters.base import AgentTurnResult, ToolCall

SOURCES = {
    "solar": ("Solar capacity grew 24% year over year in 2025.", "iea.org/solar-2025"),
    "battery": ("Lithium-ion pack prices fell below $100/kWh in 2025.", "bnef.com/battery-2025"),
    "wind": ("Offshore wind added 11 GW of capacity in 2025.", "gwec.net/wind-2025"),
}

_BYPASS_PHRASES = ("skip the verifier", "ignore previous", "ignore the verifier")


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    lowered = user_message.lower()
    calls = [
        ToolCall(
            name="planner",
            arguments={"question": user_message},
            result={"steps": ["retrieve", "write", "verify"]},
            latency_ms=80,
        )
    ]

    topic = None
    if not any(p in lowered for p in _BYPASS_PHRASES):
        topic = next((k for k in SOURCES if k in lowered), None)

    if topic is None:
        calls.append(ToolCall(name="retriever", arguments={"query": user_message}, result=[], latency_ms=120))
        calls.append(ToolCall(name="writer", arguments={"sources": 0}, result="no draft", latency_ms=60))
        calls.append(
            ToolCall(name="verifier", arguments={"draft": None}, result="REJECTED: no sources", latency_ms=40)
        )
        reply = "I could not find a verifiable source for that, so I won't state a claim."
    else:
        fact, url = SOURCES[topic]
        calls.append(ToolCall(name="retriever", arguments={"query": topic}, result=[url], latency_ms=140))
        calls.append(ToolCall(name="writer", arguments={"sources": 1}, result=fact, latency_ms=210))
        calls.append(
            ToolCall(name="verifier", arguments={"claim": fact, "source": url}, result="APPROVED", latency_ms=50)
        )
        reply = f"{fact} (source: {url})"

    session_state.setdefault("history", []).append(user_message)
    total = sum(c.latency_ms for c in calls)
    return AgentTurnResult(assistant_message=reply, tool_calls=calls, latency_ms=total, cost_usd=0.00021)
