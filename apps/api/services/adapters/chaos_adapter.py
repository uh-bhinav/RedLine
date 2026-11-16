"""
ChaosAdapter (Phase 4 Section 3 -- foundational doc §5.4).

Netflix's Chaos Monkey proved that deliberately breaking things in a controlled way
is the only honest way to know if a system is actually resilient. Agents depend on
tools, retrieval, memory, and an underlying model call -- all of which fail in
production constantly, and almost nobody tests how the agent behaves when they do.

The honest scope of what this can test
---------------------------------------
RedLine's AgentAdapter contract is deliberately a black box: the eval engine only
ever calls `run_turn(session_state, user_message) -> AgentTurnResult`. It has never
seen inside an agent's own internal tool-calling logic, and reaching in there would
mean framework-specific instrumentation -- exactly what the framework-agnostic
architecture (Section 8.1) exists to avoid.

So ChaosAdapter injects faults at the one boundary RedLine actually controls: the
call between the eval engine and the agent-under-test as a whole. For an
HTTPAdapter-wrapped deployed agent, that boundary is a REAL dependency (the network),
so these faults are genuinely representative. For a LocalPythonAdapter-wrapped local
agent, there is no real network to fail, so a fault here is synthetic -- it still
exercises the eval engine's and RecoveryScorer's handling honestly, but it is not
simulating a real infrastructure failure for that agent. This is a deliberate,
disclosed scope, not a claim that ChaosAdapter reaches inside an agent's own tool
calls.

Two families of fault, by whether the real adapter gets called at all
-----------------------------------------------------------------------
TIMEOUT / CONNECTION_RESET ("total failure"): the real adapter is never invoked.
Session state is left completely untouched, simulating a request that never
reached, or never completed with, the agent. This is what lets the NEXT turn
observe whether the conversation still makes sense with a gap in it -- exactly the
signal RecoveryScorer looks for.

MALFORMED_RESPONSE / PLAUSIBLE_WRONG / LATENCY_INJECTION: the real adapter IS
called first -- the agent's own logic and session_state mutation happen normally --
and only what the eval engine sees afterward is altered. This tests what happens
when a genuinely-produced response gets corrupted, replaced with something
confidently wrong, or arrives late.

Every faulted turn carries a reserved marker tool call (name=CHAOS_MARKER_TOOL_NAME)
so RecoveryScorer -- or a future dashboard -- can identify chaos-affected turns
without guessing from message text. This avoids widening the AgentTurnResult/
ToolCall STABLE CONTRACT models just to add a "was this faked" flag.
"""
from __future__ import annotations

import random
from enum import Enum

from apps.api.services.adapters.base import AgentAdapter, AgentTurnResult, ToolCall

CHAOS_MARKER_TOOL_NAME = "__chaos_fault__"

# One fixed canned answer, deliberately not varied. The point is that it is
# confidently, genially wrong -- not that it is realistic or diverse. A suite
# author wanting a specific wrong answer to test against should use
# MALFORMED_RESPONSE with a `contains`/`must_not_contain` expectation instead.
_PLAUSIBLE_WRONG_ANSWER = (
    "Yes, absolutely -- that's confirmed and there's nothing further you need to do."
)


class FaultMode(str, Enum):
    TIMEOUT = "timeout"
    CONNECTION_RESET = "connection_reset"
    MALFORMED_RESPONSE = "malformed_response"
    PLAUSIBLE_WRONG = "plausible_wrong"
    LATENCY_INJECTION = "latency_injection"


_TOTAL_FAILURE_MODES = frozenset({FaultMode.TIMEOUT, FaultMode.CONNECTION_RESET})


def has_chaos_marker(tool_calls) -> bool:
    """True if a turn's tool_calls include the reserved chaos marker -- the one
    place both ChaosAdapter and RecoveryScorer agree on what "this turn was
    chaos-affected" means, so the check lives here rather than being duplicated."""
    if not tool_calls:
        return False
    return any(
        (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None))
        == CHAOS_MARKER_TOOL_NAME
        for tc in tool_calls
    )


class ChaosAdapter:
    """Wraps any AgentAdapter and satisfies the same Protocol -- the eval engine
    cannot tell a chaos-wrapped adapter from a plain one, which is what keeps
    scorers, the gate, and every other call site unaware this exists.

    Two ways to select which call gets faulted:
      - target_turn_indices: an exact, deterministic set of 0-based call indices
        (the Nth invocation of run_turn() on THIS adapter instance -- a fresh
        ChaosAdapter is constructed per case, so this counts turns within one case).
        Use this for a reproducible eval suite case.
      - probability: a per-call random roll (ignored if target_turn_indices is set).
        Use this for broader, less deterministic chaos/load-style testing.
    """

    def __init__(
        self,
        target: AgentAdapter,
        mode: FaultMode,
        *,
        probability: float = 1.0,
        target_turn_indices: set[int] | None = None,
        latency_penalty_ms: int = 5000,
        rng: random.Random | None = None,
    ):
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability must be in [0.0, 1.0], got {probability}")
        self._target = target
        self._mode = mode
        self._probability = probability
        self._target_turn_indices = target_turn_indices
        self._latency_penalty_ms = latency_penalty_ms
        self._rng = rng or random.Random()
        self._call_index = -1

    def run_turn(self, session_state: dict, user_message: str) -> AgentTurnResult:
        self._call_index += 1
        if not self._should_fault(self._call_index):
            return self._target.run_turn(session_state, user_message)
        return self._inject_fault(session_state, user_message)

    def _should_fault(self, call_index: int) -> bool:
        if self._target_turn_indices is not None:
            return call_index in self._target_turn_indices
        return self._rng.random() < self._probability

    def _marker(self) -> ToolCall:
        return ToolCall(
            name=CHAOS_MARKER_TOOL_NAME,
            arguments={"mode": self._mode.value},
            result=None,
            latency_ms=0,
        )

    def _inject_fault(self, session_state: dict, user_message: str) -> AgentTurnResult:
        if self._mode in _TOTAL_FAILURE_MODES:
            # The real adapter is never called -- session_state is left byte-for-byte
            # as the agent last set it. Nothing agent-specific happens for this turn.
            return AgentTurnResult(
                assistant_message=f"[[CHAOS:{self._mode.value}]] no response obtained",
                tool_calls=[self._marker()],
                latency_ms=self._latency_penalty_ms,
                cost_usd=0.0,
            )

        real_result = self._target.run_turn(session_state, user_message)
        marker = self._marker()

        if self._mode == FaultMode.MALFORMED_RESPONSE:
            text = real_result.assistant_message
            cutoff = max(1, len(text) // 3)
            corrupted = text[:cutoff] + "�#$%&*��\x00<<TRUNCATED>>"
            return AgentTurnResult(
                assistant_message=corrupted,
                tool_calls=[*real_result.tool_calls, marker],
                latency_ms=real_result.latency_ms,
                cost_usd=real_result.cost_usd,
            )

        if self._mode == FaultMode.PLAUSIBLE_WRONG:
            return AgentTurnResult(
                assistant_message=_PLAUSIBLE_WRONG_ANSWER,
                tool_calls=[*real_result.tool_calls, marker],
                latency_ms=real_result.latency_ms,
                cost_usd=real_result.cost_usd,
            )

        if self._mode == FaultMode.LATENCY_INJECTION:
            return AgentTurnResult(
                assistant_message=real_result.assistant_message,
                tool_calls=[*real_result.tool_calls, marker],
                latency_ms=real_result.latency_ms + self._latency_penalty_ms,
                cost_usd=real_result.cost_usd,
            )

        raise AssertionError(f"unhandled FaultMode {self._mode!r}")  # exhaustive enum
