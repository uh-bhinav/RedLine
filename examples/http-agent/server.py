"""
Reference HTTP agent for RedLine (Phase 3 Section 2).

This is the smallest complete implementation of the agent-side HTTP contract. If you
have an agent built with LangChain, LangGraph, CrewAI, or raw SDK calls, wrap it in a
handler shaped like this one and RedLine can evaluate it without importing any of your
code.

Run it:
    pip install fastapi uvicorn
    python examples/http-agent/server.py            # listens on :9100

Point RedLine at it:
    agentbench register-version \\
        --version-label v1 \\
        --model my-model \\
        --entrypoint http://localhost:9100/turn

RedLine selects HTTPAdapter automatically because the entrypoint is a URL.

The contract
------------
RedLine POSTs:

    {"session_state": {...}, "user_message": "..."}

`session_state` is whatever YOU returned on the previous turn of the same eval case.
It starts as {} on the first turn. RedLine never inspects it -- store a conversation
history, a thread id, a cart, whatever your agent needs.

Your response:

    {
      "assistant_message": "...",   # REQUIRED, string
      "session_state": {...},       # optional -- omit if your agent is stateless
      "tool_calls": [               # optional, defaults to []
        {"name": "...", "arguments": {...}, "result": ..., "latency_ms": 0}
      ],
      "cost_usd": 0.0               # optional -- RedLine cannot infer this, and the
                                    # cost gate is only meaningful if you report it
    }

Notes
-----
- latency_ms is measured by RedLine as observed round-trip. Do not send it; it is
  ignored. RedLine gates on what a user experiences, which includes the network.
- Return 4xx for a malformed request and 5xx for a genuine internal failure. RedLine
  retries neither a 4xx nor a plain 500 -- it assumes your agent received the turn.
  Only connection failures and 502/503/504 are retried.
- Report tool_calls if your agent uses tools. Phase 4's chaos and reliability scoring
  read them; an agent that reports none is scored as a single-step agent.
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="RedLine reference HTTP agent")


class TurnRequest(BaseModel):
    session_state: dict = {}
    user_message: str


class TurnResponse(BaseModel):
    assistant_message: str
    session_state: dict = {}
    tool_calls: list[dict] = []
    cost_usd: float = 0.0


# A deliberately tiny knowledge base so the reference agent produces answers the
# example eval suite can actually assert on.
_FACTS = {
    "return": "You have 30 days to return an item for a full refund.",
    "shipping": "Standard shipping takes 3-5 business days within the US.",
    "international": "International shipping takes 10-14 business days.",
}


@app.post("/turn", response_model=TurnResponse)
def turn(req: TurnRequest) -> TurnResponse:
    history = req.session_state.get("history", [])
    message = req.user_message.lower()

    matched = next((v for k, v in _FACTS.items() if k in message), None)

    if matched:
        answer = matched
    elif history:
        # Multi-turn: a follow-up with no keyword falls back to context, which is
        # what makes the session_state round-trip observable in an eval. Named
        # honestly -- this turn found nothing new in the knowledge base, so the
        # answer says so explicitly rather than implying it re-checked and
        # confirmed the earlier fact. Phase 4's SafetyScorer checks exactly this:
        # a retrieval call that came back empty must be paired with an honesty
        # signal, not presented as if it were freshly grounded.
        answer = f"I don't have new information on that, but earlier I said: {history[-1]}"
    else:
        # Honest refusal rather than a confident guess -- the behaviour the
        # missing-context eval case checks for.
        answer = "I don't have information about that in my knowledge base."

    history = [*history, answer]

    return TurnResponse(
        assistant_message=answer,
        session_state={"history": history, "turns": len(history)},
        tool_calls=[
            {
                "name": "knowledge_base_lookup",
                "arguments": {"query": req.user_message},
                "result": matched or None,
                "latency_ms": 1,
            }
        ],
        cost_usd=0.000012,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "redline-reference-http-agent"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100)
