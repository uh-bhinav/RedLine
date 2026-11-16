# Pre-Tool-Use Hooks — RedLine

These checks must be performed **before** editing the listed files. They protect architectural invariants that are expensive to fix after the fact.

---

## Hook 1: Before Editing `apps/api/services/eval_engine.py`

**Check:** All `emit_trace()` calls remain inside `try/except` blocks.

**Run before editing:**

```bash
grep -n "emit_trace" apps/api/services/eval_engine.py
```

Count the number of `emit_trace` call sites. After your edit, run the same command and confirm the count is the same or higher — you cannot have removed a trace call.

**Then verify each one is wrapped:**

```bash
grep -B3 "emit_trace" apps/api/services/eval_engine.py
```

The line 3 above each `emit_trace()` should be `try:`.

**Why this matters:** A ClickHouse write failure must never kill an eval run. The `emit_trace()` function itself has internal error handling, but defense-in-depth requires the call site to also catch. If you unwrap a trace call, a ClickHouse connection error will propagate to the worker and mark the eval run as `failed` — corrupting CI results.

**Pass condition:** Every `emit_trace()` call in `eval_engine.py` is inside a `try/except Exception` block that does NOT re-raise.

---

## Hook 2: Before Editing `apps/api/services/gate_engine.py`

**Check:** `_compute_gate_result` remains a pure function (no DB, no I/O, no side effects).

**Run before editing:**

```bash
grep -n "^from\|^import" apps/api/services/gate_engine.py
```

**Imports that must NOT appear:**
- `from apps.api.core.db import ...` or `SessionLocal`
- `from sqlalchemy ...` (except for type hints)
- `import redis`
- `import httpx`
- `import requests`
- `open(` or any file I/O

**Then read the function signature:**

```bash
grep -n "def _compute_gate_result" apps/api/services/gate_engine.py
```

The function must take only primitive arguments: `passed_count: int, total: int, avg_cost_usd: float, avg_latency_ms: float, min_pass_rate: float, max_avg_cost_usd: Optional[float], max_avg_latency_ms: Optional[float]`.

**Why this matters:** `_compute_gate_result` is unit-tested without a database (12 tests in `test_gate_engine.py`). If you add DB access to it, all those tests break and the function can no longer be unit-tested in isolation. The gate engine's correctness guarantee comes from it being a pure function that can be fully verified in isolation.

**Pass condition:** No external imports in `_compute_gate_result`. Function takes only primitive types.

---

## Hook 3: Before Editing Any Router File

**Check:** The route belongs in the correct service.

**Before editing any router, confirm the service ownership:**

```bash
# Which service owns this route?
grep -rn "include_router" apps/eval_service/main.py apps/agent_service/main.py apps/gate_service/main.py
```

**Ownership map:**

| Router file | Owned by | Service port |
|---|---|---|
| `routers/eval_runs.py` | eval_service | 8001 |
| `routers/ci.py` | eval_service | 8001 |
| `routers/auth.py` | eval_service | 8001 |
| `routers/agents.py` | agent_service | 8002 |
| `routers/eval_suites.py` | agent_service | 8002 |
| `routers/dashboard.py` | gate_service | 8003 |

**If you are adding a new route:**

1. Decide which service logically owns it (eval data → eval_service, registry data → agent_service, read-heavy dashboard → gate_service)
2. Add the route to the correct service's `main.py`
3. Also add it to `apps/api/main.py` for monolith dev mode

**Check nginx is updated:**

```bash
grep -A 5 "location" infra/gateway.nginx.conf
```

If your new route has a new URL prefix, add a `location` block to `gateway.nginx.conf`.

**Pass condition:** The router file is included in the correct service's `main.py` and in the monolith `apps/api/main.py`.

---

## Hook 4: Before Editing `apps/api/core/redpanda_queue.py`

**Check:** The STABLE CONTRACT signatures `publish()` and `get_status()` are unchanged.

**Run before editing:**

```bash
grep -n "def publish\|def get_status" apps/api/core/redpanda_queue.py apps/api/core/jobqueue.py
```

**Save the exact output.** After your edit, run the same command and diff manually.

**Required signatures (must not change):**

```python
def publish(self, tenant_id: UUID, job_type: str, payload: dict) -> UUID: ...
def get_status(self, job_id: UUID) -> JobStatus: ...
```

**Never:**
- Add a required parameter to `publish()` or `get_status()`
- Change `-> UUID` to any other return type on `publish()`
- Make either method `async`
- Rename either method

**Also check all callers:**

```bash
grep -rn "\.publish(\|\.get_status(" apps/api/routers/ apps/api/workers/
```

If you change the contract, every caller must be updated simultaneously — the contract exists specifically to prevent this.

**Pass condition:** Signatures are byte-for-byte identical before and after your edit.

---

## Hook 5: Before Editing Any Agent File (`agents/`)

**Check:** Model names come from `get_profile()`, not hardcoded strings.

**Run before editing:**

```bash
grep -n "gemini-2.5-flash\|gemini-2.0-flash\|gemini-2.0-flash-lite\|claude-\|gpt-4\|gpt-3" agents/rag_agent/agent.py agents/stateful_support_agent/agent.py agents/research_pipeline_agent/agent.py
```

**Pass:** Zero matches.

**If you are adding a new LLM call in an agent:**

```python
# Correct — use profile system
from apps.api.core.model_profiles import get_profile

profile = get_profile("standard")  # resolves from config/model_profiles.yaml
model = genai.GenerativeModel(profile.model_name)
```

**Never:**

```python
# WRONG — hardcoded model name
model = genai.GenerativeModel("gemini-2.5-flash")
```

**Also check the rate limiter is called:**

```bash
grep -n "rate_limiter.acquire\|llm_rate_limiter" agents/rag_agent/agent.py
```

Every `generate_content()` call must be preceded by `rate_limiter.acquire()`.

**Pass condition:** Zero hardcoded model name strings in any agent file.
