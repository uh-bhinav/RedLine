"""
Unit tests for HTTPAdapter and adapter selection (Phase 3 Section 2).

No network: every test injects an httpx.Client backed by a MockTransport, so these
run anywhere with no server and no Postgres.

Run from the repo root:
    pytest apps/api/tests/unit/test_http_adapter.py -v -m unit
"""
from __future__ import annotations

import httpx
import pytest

from apps.api.services.adapters import build_adapter
from apps.api.services.adapters.http_adapter import AgentHTTPError, HTTPAdapter
from apps.api.services.adapters.local_python import LocalPythonAdapter

pytestmark = pytest.mark.unit

ENDPOINT = "https://agent.example.com/turn"


def _adapter(handler, **kwargs) -> HTTPAdapter:
    """HTTPAdapter wired to a MockTransport running `handler`."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HTTPAdapter(ENDPOINT, client=client, **kwargs)


def _ok(body: dict):
    return lambda request: httpx.Response(200, json=body)


# ---------- happy path ----------

def test_returns_assistant_message():
    adapter = _adapter(_ok({"assistant_message": "Returns take 30 days."}))
    result = adapter.run_turn({}, "How long do returns take?")

    assert result.assistant_message == "Returns take 30 days."
    assert result.tool_calls == []
    assert result.cost_usd == 0.0


def test_sends_session_state_and_user_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"assistant_message": "ok"})

    adapter = _adapter(handler)
    adapter.run_turn({"history": ["earlier"]}, "next question")

    assert seen == {
        "session_state": {"history": ["earlier"]},
        "user_message": "next question",
    }


def test_parses_tool_calls_and_cost():
    adapter = _adapter(_ok({
        "assistant_message": "Found it.",
        "cost_usd": 0.00042,
        "tool_calls": [
            {"name": "search", "arguments": {"q": "refunds"}, "result": ["doc1"],
             "latency_ms": 12},
        ],
    }))
    result = adapter.run_turn({}, "find refunds")

    assert result.cost_usd == pytest.approx(0.00042)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search"
    assert result.tool_calls[0].arguments == {"q": "refunds"}
    assert result.tool_calls[0].latency_ms == 12


def test_latency_is_measured_not_taken_from_the_agent():
    """The latency gate asserts what a user experiences, which for a deployed agent
    includes the network. A self-reported internal number is always smaller."""
    adapter = _adapter(_ok({"assistant_message": "hi", "latency_ms": 999999}))
    result = adapter.run_turn({}, "hello")

    assert result.latency_ms != 999999
    assert result.latency_ms >= 0


# ---------- session state ----------

def test_session_state_is_mutated_in_place_not_rebound():
    """The eval engine holds one dict across every turn of a case. Rebinding it
    instead of mutating would silently drop multi-turn state."""
    adapter = _adapter(_ok({
        "assistant_message": "noted",
        "session_state": {"history": ["q1", "a1"], "cart": 3},
    }))

    state = {"history": []}
    original_id = id(state)
    adapter.run_turn(state, "q1")

    assert id(state) == original_id, "session_state object was replaced, not mutated"
    assert state == {"history": ["q1", "a1"], "cart": 3}


def test_stateless_agent_leaves_session_state_untouched():
    adapter = _adapter(_ok({"assistant_message": "no state here"}))

    state = {"history": ["preserved"]}
    adapter.run_turn(state, "hello")

    assert state == {"history": ["preserved"]}


def test_multi_turn_state_accumulates_across_turns():
    turns = [
        {"assistant_message": "a1", "session_state": {"history": ["q1", "a1"]}},
        {"assistant_message": "a2", "session_state": {"history": ["q1", "a1", "q2", "a2"]}},
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = turns[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=body)

    adapter = _adapter(handler)
    state: dict = {}
    adapter.run_turn(state, "q1")
    adapter.run_turn(state, "q2")

    assert state == {"history": ["q1", "a1", "q2", "a2"]}


# ---------- error handling ----------

def test_4xx_raises_immediately():
    adapter = _adapter(lambda r: httpx.Response(422, text="bad payload"))

    with pytest.raises(AgentHTTPError, match="422"):
        adapter.run_turn({}, "hi")


def test_non_json_response_raises():
    adapter = _adapter(lambda r: httpx.Response(200, text="<html>oops</html>"))

    with pytest.raises(AgentHTTPError, match="non-JSON"):
        adapter.run_turn({}, "hi")


def test_missing_assistant_message_raises():
    adapter = _adapter(_ok({"cost_usd": 0.1}))

    with pytest.raises(AgentHTTPError, match="assistant_message"):
        adapter.run_turn({}, "hi")


def test_json_array_response_raises():
    adapter = _adapter(lambda r: httpx.Response(200, json=["not", "an", "object"]))

    with pytest.raises(AgentHTTPError, match="expected a JSON object"):
        adapter.run_turn({}, "hi")


def test_malformed_tool_calls_raises():
    adapter = _adapter(_ok({"assistant_message": "hi", "tool_calls": "not-a-list"}))

    with pytest.raises(AgentHTTPError, match="tool_calls"):
        adapter.run_turn({}, "hi")


# ---------- retry policy ----------

def test_retries_connect_errors_then_succeeds():
    """A failed connection means the agent never saw the turn, so re-sending is safe."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"assistant_message": "recovered"})

    adapter = _adapter(handler, max_retries=2)
    result = adapter.run_turn({}, "hi")

    assert result.assistant_message == "recovered"
    assert calls["n"] == 3


def test_gives_up_after_max_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    adapter = _adapter(handler, max_retries=1)

    with pytest.raises(AgentHTTPError, match="unreachable after 2 attempts"):
        adapter.run_turn({}, "hi")
    assert calls["n"] == 2


def test_retries_503_from_an_intermediary():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="upstream unavailable")
        return httpx.Response(200, json={"assistant_message": "ok"})

    adapter = _adapter(handler, max_retries=2)
    assert adapter.run_turn({}, "hi").assistant_message == "ok"
    assert calls["n"] == 2


def test_read_timeout_is_never_retried():
    """The request was sent and the agent may have processed it. Retrying would make
    the platform cause the exact class of duplicate-side-effect incident it exists to
    catch."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("too slow", request=request)

    adapter = _adapter(handler, max_retries=3)

    with pytest.raises(AgentHTTPError, match="may have been processed"):
        adapter.run_turn({}, "hi")
    assert calls["n"] == 1, "a read timeout was retried -- turn could be applied twice"


def test_500_is_not_retried():
    """A plain 500 came from the agent itself, meaning it received the turn."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="agent exploded")

    adapter = _adapter(handler, max_retries=3)

    with pytest.raises(AgentHTTPError, match="500"):
        adapter.run_turn({}, "hi")
    assert calls["n"] == 1


# ---------- construction + selection ----------

def test_rejects_non_http_endpoint():
    with pytest.raises(ValueError, match="expected an http"):
        HTTPAdapter("agents.rag_agent.agent:run_turn")


def test_build_adapter_selects_http_for_urls():
    assert isinstance(build_adapter("https://agent.example.com/turn"), HTTPAdapter)
    assert isinstance(build_adapter("http://localhost:9000/turn"), HTTPAdapter)


def test_build_adapter_selects_local_python_for_module_paths():
    adapter = build_adapter("apps.api.tests.unit.fixtures.dummy_agent:run_turn")
    assert isinstance(adapter, LocalPythonAdapter)


def test_build_adapter_rejects_garbage():
    with pytest.raises(ValueError, match="invalid entrypoint"):
        build_adapter("just-some-text")

    with pytest.raises(ValueError, match="entrypoint is empty"):
        build_adapter("   ")


def test_build_adapter_rejects_http_options_on_a_python_entrypoint():
    """Silently dropping a timeout the caller asked for is worse than failing."""
    with pytest.raises(ValueError, match="not supported"):
        build_adapter(
            "apps.api.tests.unit.fixtures.dummy_agent:run_turn", timeout_seconds=5
        )


def test_both_adapters_satisfy_the_same_protocol():
    """The point of the STABLE CONTRACT: the eval engine cannot tell them apart."""
    local = build_adapter("apps.api.tests.unit.fixtures.dummy_agent:run_turn")
    http = build_adapter(ENDPOINT)

    for adapter in (local, http):
        assert hasattr(adapter, "run_turn")
        assert callable(adapter.run_turn)
