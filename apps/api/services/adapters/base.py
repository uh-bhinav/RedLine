"""
The Agent Adapter abstraction (Phase1 roadmap Section 6) — STABLE CONTRACT.

The Eval Engine (Section 10) only ever calls adapter.run_turn(...). It never imports
anything from agents/ directly. LocalPythonAdapter (local_python.py) is the one place
in the codebase that knows how to load agent code in-process; Phase 2 adds an
HTTPAdapter implementing the same interface, and the Eval Engine's calling code
does not change at all.
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class ToolCall(BaseModel):
    name: str
    arguments: dict
    result: Any
    latency_ms: int


class AgentTurnResult(BaseModel):
    assistant_message: str
    tool_calls: list[ToolCall]
    latency_ms: int
    cost_usd: float


class AgentAdapter(Protocol):
    def run_turn(self, session_state: dict, user_message: str) -> AgentTurnResult:
        """Runs one turn of a multi-turn session against the agent under test.

        session_state is opaque to the adapter caller and is passed back unchanged
        on the next turn — it is whatever the underlying agent needs to remember
        context (e.g. a conversation history list, a LangGraph thread id, etc.).
        The agent function may mutate it in place to track state across turns;
        run_turn's return type only ever carries this turn's result.
        """
        ...