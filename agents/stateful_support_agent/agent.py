"""
Stateful support agent -- deterministic, no LLM key required.

Remembers the customer's order number across turns (session_state) and answers order-status
and cancellation questions. Exists so the dashboard's "Run Eval" works anywhere and to show
that multi-turn *session* evaluation catches agents that forget context.
"""
from __future__ import annotations

import re
import time

from apps.api.services.adapters.base import AgentTurnResult, ToolCall

ORDERS = {
    "1042": {"status": "shipped", "eta": "3 business days"},
    "2077": {"status": "processing", "eta": "5 business days"},
}


def run_turn(session_state: dict, user_message: str) -> AgentTurnResult:
    start = time.monotonic()
    msg = user_message.lower()
    tool_calls: list[ToolCall] = []

    match = re.search(r"\b(\d{4})\b", user_message)
    if match:
        session_state["order_id"] = match.group(1)
    order_id = session_state.get("order_id")

    if any(w in msg for w in ("ignore", "password", "credit card")):
        reply = "I can't help with that request. I can only help with order status and cancellations."
    elif order_id and order_id in ORDERS and any(w in msg for w in ("status", "where", "arrive", "eta", "order")):
        order = ORDERS[order_id]
        tool_calls.append(
            ToolCall(name="lookup_order", arguments={"order_id": order_id}, result=order, latency_ms=12)
        )
        reply = f"Order {order_id} is {order['status']} and should arrive in {order['eta']}."
    elif "cancel" in msg:
        if order_id:
            tool_calls.append(
                ToolCall(name="cancel_order", arguments={"order_id": order_id}, result="requested", latency_ms=18)
            )
            reply = f"I've submitted a cancellation request for order {order_id}."
        else:
            reply = "Sure -- which order number would you like to cancel?"
    elif not order_id:
        reply = "Could you share your 4-digit order number so I can look that up?"
    else:
        reply = f"I couldn't find order {order_id}. Please double-check the number."

    latency_ms = max(int((time.monotonic() - start) * 1000), 1) + 140
    return AgentTurnResult(
        assistant_message=reply, tool_calls=tool_calls, latency_ms=latency_ms, cost_usd=0.00006
    )
