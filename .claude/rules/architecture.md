# RedLine Architecture Rules

These are **rules**, not guidelines. Any code that violates these rules is incorrect and must be fixed before merging.

---

## Rule 1: The Eval Engine Is Synchronous

The eval engine (`apps/api/services/eval_engine.py`), all scorers (`services/scorers/`), the gate engine (`services/gate_engine.py`), and both workers (`workers/eval_worker.py`, `workers/eval_worker_v2.py`) are **synchronous Python**.

**Never:**
- Add `async def` to `run_eval()`, `score()`, `_compute_gate_result()`, or `evaluate()`
- Use `await` inside any scorer
- Use `AsyncSession` from SQLAlchemy in any worker or service
- Import `asyncio` in `eval_engine.py`, `gate_engine.py`, or any scorer

**Rationale:** `confluent-kafka` is synchronous (librdkafka C binding). Mixing asyncio with synchronous SQLAlchemy Sessions and synchronous Kafka consumer calls is a concurrency trap that produces race conditions and deadlocks.

**Verification:**

```bash
grep -rn "async def\|await\|asyncio" apps/api/services/ apps/api/workers/
```

Zero matches in these paths.

---

## Rule 2: The STABLE CONTRACT — Never Change These Signatures

`JobQueue.publish(tenant_id: UUID, job_type: str, payload: dict) -> UUID`
`JobQueue.get_status(job_id: UUID) -> JobStatus`

Both `PostgresJobQueue` and `RedpandaJobQueue` implement these methods with these exact signatures.

**Never:**
- Add a required parameter
- Change return types
- Rename the methods
- Make either method async

**Why:** The STABLE CONTRACT is the seam that lets Phase 2 swap the transport (Postgres → Redpanda) without touching a single line of router or eval engine code. Breaking it means all callers must be updated simultaneously — the opposite of the contract's purpose.

---

## Rule 3: Route Ownership Is Fixed

| Route prefix | Owning service | Port |
|---|---|---|
| `/eval-runs` | eval_service | 8001 |
| `/ci` | eval_service | 8001 |
| `/auth` | eval_service | 8001 |
| `/diff-runs` | eval_service | 8001 |
| `/load-runs` | eval_service | 8001 |
| `/mining` | eval_service | 8001 |
| `/agents` | agent_service | 8002 |
| `/eval-suites` | agent_service | 8002 |
| `/dashboard` | gate_service | 8003 |

**Never** add a `/ci` or `/eval-runs` route to `agent_service`. **Never** add a `/dashboard` route to `eval_service`.

**In dev mode:** All routes are in the monolith `apps/api/main.py`. This does not change the ownership rule — it means the monolith includes all routers for local dev convenience.

---

## Rule 4: `emit_trace()` Must Never Raise

Every call to `emit_trace()` must be wrapped in a `try/except Exception` block. The except handler logs a warning but does NOT re-raise.

```python
# Required pattern at every call site
try:
    emit_trace(run_id=..., case_key=..., event_type=..., data=...)
except Exception as e:
    logger.warning(f"ClickHouse trace write failed (non-fatal): {e}")
```

**Why:** ClickHouse is an analytics store. A trace write failure is annoying but should never fail an eval run, corrupt a gate decision, or block a CI check. The eval run's correctness depends only on Postgres and Gemini — not ClickHouse.

---

## Rule 5: `_compute_gate_result()` Must Stay Pure

`_compute_gate_result(passed_count, total, avg_cost_usd, avg_latency_ms, min_pass_rate, max_avg_cost_usd, max_avg_latency_ms)` in `apps/api/services/gate_engine.py` is a pure function.

**Never inside this function:**
- Any SQLAlchemy Session access
- Any Redis calls
- Any file I/O
- Any network calls
- Raising exceptions (return a failed GateResult instead)

**Why:** The function is unit-tested by 12 tests that run in <100ms with no infrastructure. Purity is what makes this possible. The `evaluate(eval_run_id)` wrapper function is where DB access belongs.

---

## Rule 6: Agents Use `get_profile()`, Never Model Names

No agent file may contain a hardcoded model name string.

```python
# WRONG
model = genai.GenerativeModel("gemini-2.5-flash")

# CORRECT
from apps.api.core.model_profiles import get_profile
profile = get_profile("standard")
model = genai.GenerativeModel(profile.model_name)
```

**Why:** Eval suites declare `model_profile: standard`. If the model behind `standard` changes (e.g., `gemini-2.0-flash` → `gemini-2.5-flash`), only `config/model_profiles.yaml` changes. Zero agent code changes.

---

## Rule 7: The CLI Is HTTP-Only

`apps/cli/` is a **separate deployable**. It communicates with the RedLine API exclusively via `httpx` through `apps/cli/api_client.py`.

**Never in the CLI:**
- `from apps.api.models import ...`
- `from apps.api.core.db import get_db`
- Direct SQLAlchemy Session usage
- Direct Postgres connection

**Why:** The CLI is installed on developers' machines, which may not have Postgres access. It must work with only the HTTP API and an API key.

---

## Rule 8: Never Store Raw Credentials

**API keys:** Generate with `secrets.token_urlsafe(32)`, prefix with `"rl_live_"`. Store `SHA256(raw_key).hexdigest()` in `api_keys.key_hash`. Raw key shown once, never stored.

**Refresh tokens:** Generate with `secrets.token_urlsafe(48)`. Store `SHA256(raw_token).hexdigest()` in `refresh_tokens.token_hash`. Raw token returned once, never stored.

**Passwords:** Hash with `passlib.CryptContext(schemes=["bcrypt"])`. Never MD5, SHA1, or plaintext.

**Why:** A database breach must not expose usable credentials.

---

## Rule 9: `LocalPythonAdapter` Uses `importlib`, Never `subprocess`

The `LocalPythonAdapter` (`apps/api/services/adapters/local_python.py`) loads agents in-process using `importlib.import_module()`, not `subprocess`.

**Never:**
- `subprocess.run()` or `subprocess.Popen()` to invoke agents
- JSON serialization of `session_state` across process boundaries

**Why:** `session_state` is passed by reference across turns. In-process execution avoids serialization overhead and lets agents maintain complex objects (conversation history lists, graph state) between turns without defining a wire protocol.

---

## Rule 10: KEDA Owns the Worker's Replica Count

The eval worker Deployment in `helm/redline/templates/worker/` must NOT have `spec.replicas` set.

```yaml
# WRONG
spec:
  replicas: 2  # NEVER — KEDA owns this

# CORRECT
spec:
  # replicas intentionally omitted — managed by KEDA ScaledObject
```

**Why:** KEDA's ScaledObject creates an HPA-like controller that sets replica count based on Redpanda consumer lag. Specifying `spec.replicas` overrides KEDA and causes the worker to fight the autoscaler — resulting in oscillation between the hardcoded value and KEDA's target.
