"""
HTTPAdapter (Phase 3 Section 2) -- the second AgentAdapter implementation.

Why this exists
---------------
Until now the only adapter was LocalPythonAdapter, which imports the agent with
importlib and calls it in-process. That means an agent under test must be a Python
function importable from inside *this* repository. The foundational document (§8.1)
promises "any agent that can be called via HTTP or Python function," so without this
adapter the framework-agnostic claim is false and no outside user can point RedLine
at their own deployed agent.

It is also a hard dependency for two Phase 4 features:
  - Chaos engineering (§5.4) injects faults on the boundary between RedLine and the
    agent. Over HTTP that boundary is real; over importlib it is monkeypatching.
  - Load testing (§5.5) fires N concurrent sessions at an agent. With
    LocalPythonAdapter those all execute inside the worker process, which measures
    RedLine's concurrency rather than the agent's.

The agent-side contract
-----------------------
RedLine POSTs to the configured endpoint:

    {"session_state": {...}, "user_message": "..."}

and expects back:

    {
      "assistant_message": "...",          # required
      "session_state": {...},              # optional -- see "Session state" below
      "tool_calls": [                      # optional, defaults to []
        {"name": "...", "arguments": {...}, "result": ..., "latency_ms": 0}
      ],
      "cost_usd": 0.0                      # optional, defaults to 0.0
    }

Session state
-------------
The AgentAdapter contract says session_state is passed back unchanged on the next
turn and that the agent "may mutate it in place." An HTTP agent cannot mutate our
dict -- it is in another process, possibly on another machine. So the agent returns
its new state and this adapter writes it back into the caller's dict *in place*
(clear + update, not rebind), which preserves the contract exactly as the eval engine
observes it. An agent that omits session_state is treated as stateless and the
caller's dict is left untouched.

Latency
-------
latency_ms is the observed round-trip measured here, not whatever the agent reports
about itself. The latency gate asserts what a user experiences, and for a deployed
agent that includes the network. An agent's self-reported internal latency is always
the smaller, less honest number.

Retries
-------
Retries are deliberately narrow. A retry re-sends the turn, and re-sending a turn an
agent already processed is an at-least-once delivery of a side effect (a refund, a
ticket, an email). So this retries only where the request provably did not reach the
agent:

  - httpx.ConnectError / ConnectTimeout -- the connection was never established
  - 502 / 503 / 504 -- an intermediary is reporting it could not reach the upstream

It deliberately does NOT retry on ReadTimeout: the request was sent, the agent may
well have processed it, and we simply did not hear back. Retrying there would be the
platform causing exactly the class of production incident it exists to catch.
"""
from __future__ import annotations

import time

import httpx

from apps.api.services.adapters.base import AgentTurnResult, ToolCall

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2
RETRYABLE_STATUS = frozenset({502, 503, 504})


class AgentHTTPError(RuntimeError):
    """The agent endpoint was unreachable, timed out, or returned an unusable response."""


class HTTPAdapter:
    """Invokes an agent deployed behind an HTTP endpoint.

    Satisfies the AgentAdapter Protocol, so the eval engine's per-turn calling code
    (`adapter.run_turn(session_state, message)`) is identical to LocalPythonAdapter's.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        headers: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ):
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError(
                f"invalid endpoint '{endpoint}' -- expected an http:// or https:// URL"
            )
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._headers = {"Content-Type": "application/json", **(headers or {})}
        # An injected client keeps this unit-testable without a live server and lets
        # a future load runner share one connection pool across many sessions.
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    # ---------- AgentAdapter Protocol ----------

    def run_turn(self, session_state: dict, user_message: str) -> AgentTurnResult:
        payload = {"session_state": session_state, "user_message": user_message}

        start = time.perf_counter()
        response = self._post_with_retries(payload)
        latency_ms = int((time.perf_counter() - start) * 1000)

        body = self._parse_body(response)
        self._apply_session_state(session_state, body)

        return AgentTurnResult(
            assistant_message=self._require_assistant_message(body),
            tool_calls=self._parse_tool_calls(body),
            latency_ms=latency_ms,
            cost_usd=float(body.get("cost_usd") or 0.0),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HTTPAdapter":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ---------- internals ----------

    def _post_with_retries(self, payload: dict) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    self.endpoint, json=payload, headers=self._headers
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Never established a connection -- the agent did not see this turn,
                # so re-sending is safe.
                last_error = exc
            except httpx.ReadTimeout as exc:
                # Sent but unanswered. The agent may have processed it. Do not retry.
                raise AgentHTTPError(
                    f"agent at {self.endpoint} did not respond within "
                    f"{self.timeout_seconds}s (not retried -- the turn may have been "
                    f"processed)"
                ) from exc
            except httpx.HTTPError as exc:
                raise AgentHTTPError(f"agent at {self.endpoint} failed: {exc}") from exc
            else:
                if response.status_code in RETRYABLE_STATUS:
                    last_error = AgentHTTPError(
                        f"agent at {self.endpoint} returned {response.status_code}"
                    )
                elif response.status_code >= 400:
                    raise AgentHTTPError(
                        f"agent at {self.endpoint} returned {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                else:
                    return response

            if attempt < self.max_retries:
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1.0s

        raise AgentHTTPError(
            f"agent at {self.endpoint} unreachable after {self.max_retries + 1} "
            f"attempts: {last_error}"
        )

    def _parse_body(self, response: httpx.Response) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise AgentHTTPError(
                f"agent at {self.endpoint} returned non-JSON response: "
                f"{response.text[:200]}"
            ) from exc

        if not isinstance(body, dict):
            raise AgentHTTPError(
                f"agent at {self.endpoint} returned {type(body).__name__}, expected a "
                f"JSON object"
            )
        return body

    def _require_assistant_message(self, body: dict) -> str:
        message = body.get("assistant_message")
        if not isinstance(message, str):
            raise AgentHTTPError(
                f"agent at {self.endpoint} response is missing a string "
                f"'assistant_message' field (got {type(message).__name__})"
            )
        return message

    @staticmethod
    def _apply_session_state(session_state: dict, body: dict) -> None:
        """Writes the agent's returned state back into the caller's dict in place.

        In place, not rebound: the eval engine holds a reference to this dict across
        every turn of the case, so replacing the object would silently drop state.
        """
        new_state = body.get("session_state")
        if isinstance(new_state, dict):
            session_state.clear()
            session_state.update(new_state)

    def _parse_tool_calls(self, body: dict) -> list[ToolCall]:
        raw = body.get("tool_calls") or []
        if not isinstance(raw, list):
            raise AgentHTTPError(
                f"agent at {self.endpoint} returned 'tool_calls' as "
                f"{type(raw).__name__}, expected a list"
            )

        calls: list[ToolCall] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise AgentHTTPError(
                    f"agent at {self.endpoint} returned tool_calls[{i}] as "
                    f"{type(item).__name__}, expected an object"
                )
            calls.append(
                ToolCall(
                    name=str(item.get("name", "")),
                    arguments=item.get("arguments") or {},
                    result=item.get("result"),
                    latency_ms=int(item.get("latency_ms") or 0),
                )
            )
        return calls
