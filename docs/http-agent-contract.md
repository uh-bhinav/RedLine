# The HTTP Agent Contract

**Status:** Stable as of Phase 3 Section 2
**Reference implementation:** `examples/http-agent/server.py`
**Adapter:** `apps/api/services/adapters/http_adapter.py`

RedLine evaluates any agent it can reach over HTTP. Your agent does not need to be
written in Python, does not need to live in this repository, and does not need to use
any particular framework. Implement one endpoint and RedLine can run eval suites,
gates, and (from Phase 4) chaos and load tests against it.

---

## Registering an HTTP agent

RedLine picks the adapter from the shape of the entrypoint. A URL selects `HTTPAdapter`;
a `module.path:function` string selects `LocalPythonAdapter`. No configuration flag, no
migration.

```bash
agentbench register-version \
    --version-label v1 \
    --model my-model-name \
    --entrypoint https://my-agent.example.com/turn
```

---

## Request

RedLine sends `POST` with `Content-Type: application/json`:

```json
{
  "session_state": {},
  "user_message": "How long do I have to return an item?"
}
```

| Field | Type | Notes |
|---|---|---|
| `session_state` | object | Whatever **you** returned on the previous turn of this eval case. `{}` on the first turn. RedLine never inspects it. |
| `user_message` | string | The scripted user turn from the eval case. |

`session_state` is how multi-turn evaluation works. Put a conversation history, a
thread id, a cart, a retrieval cache — anything your agent needs to behave correctly on
turn 2 — into it. RedLine passes it back verbatim.

---

## Response

```json
{
  "assistant_message": "You have 30 days to return an item for a full refund.",
  "session_state": {"history": ["..."], "turns": 1},
  "tool_calls": [
    {
      "name": "knowledge_base_lookup",
      "arguments": {"query": "return policy"},
      "result": "30 day return window",
      "latency_ms": 12
    }
  ],
  "cost_usd": 0.000012
}
```

| Field | Required | Default | Notes |
|---|---|---|---|
| `assistant_message` | **yes** | — | Must be a string. A missing or non-string value fails the turn. |
| `session_state` | no | unchanged | Omit if your agent is stateless. |
| `tool_calls` | no | `[]` | Report these if your agent uses tools. |
| `cost_usd` | no | `0.0` | RedLine cannot infer this. The cost gate is meaningless without it. |

**Do not send `latency_ms` at the top level.** It is ignored. RedLine measures the
observed round-trip itself, because the latency gate asserts what a user experiences
and for a deployed agent that includes the network. Your self-reported internal number
is always the smaller, less honest one. Per-tool `latency_ms` inside `tool_calls` *is*
recorded, since RedLine cannot observe it.

---

## Status codes and retry behaviour

Retries are deliberately narrow, because re-sending a turn an agent already processed
is an at-least-once delivery of a real side effect — a refund issued twice, a ticket
opened twice.

| Situation | RedLine retries? | Why |
|---|---|---|
| Connection refused / connect timeout | **Yes** | The connection was never established, so your agent never saw the turn. |
| `502` / `503` / `504` | **Yes** | An intermediary is reporting it could not reach your agent. |
| Read timeout | **No** | The request was sent. Your agent may have processed it and simply not answered in time. |
| `4xx` | **No** | The request was malformed. Retrying sends the same malformed request. |
| `500` | **No** | Your agent received the turn and failed while handling it. |

Default: 2 retries, 0.5s then 1.0s backoff, 60s timeout. All three are configurable on
`HTTPAdapter`.

A turn that exhausts retries raises `AgentHTTPError`, which fails the eval run rather
than silently recording a passing case.

---

## Concurrency and thread-safety

Eval suites and gate checks send your agent one turn at a time. **Load testing
(Phase 4.4) does not.** RedLine's load tester (`apps/api/services/load_engine.py`)
drives concurrent virtual users with a real `concurrent.futures.ThreadPoolExecutor` --
genuine OS-thread concurrency, not a sequential loop with a concurrency number attached
to it for show. At a load test's configured concurrency, your `/turn` endpoint will
receive that many requests genuinely in flight at once.

This means your agent's request handler needs to be safe under real concurrent
invocation, the same way any HTTP service does:

- No unsynchronized shared mutable state across requests (a module-level dict, list,
  or counter that different requests read and write without a lock).
- Any per-request client (an LLM SDK client, a DB connection, an HTTP session) must
  either be safe to share across threads or created fresh per request.
- `session_state` itself is scoped to one eval case and passed back to you verbatim --
  it is not shared across concurrent requests unless your own code makes it so (e.g. by
  keying a global cache on something that collides across virtual users).

If your framework's request handler is single-threaded by default (common for simple
`http.server`-based examples), a load test will simply serialize through it and the
concurrency number in your results won't reflect what RedLine asked for -- so this
matters for getting an honest load-test result, not only for correctness under
production traffic.

---

## Minimal implementation

Any language. This is the complete required surface:

```python
@app.post("/turn")
def turn(req):
    reply = my_agent(req["user_message"], state=req.get("session_state", {}))
    return {
        "assistant_message": reply.text,
        "session_state": reply.state,
        "cost_usd": reply.cost,
    }
```

See `examples/http-agent/server.py` for a runnable version with tool call reporting and
multi-turn state.

---

## Verifying your agent

Run the reference agent and the end-to-end test to see the expected shape:

```bash
python examples/http-agent/server.py            # listens on :9100
pytest apps/api/tests/integration/test_http_adapter_end_to_end.py -v -m integration
```

That test starts the reference agent, registers it with an HTTP entrypoint, runs a real
eval suite through the real eval engine, and asserts on the resulting gate verdict —
the same path your agent will take.
