# /refactor — RedLine Refactoring Guide

Use this command before making any structural change to RedLine. Read the relevant rule, understand what you must NOT do, and follow the prescribed pattern.

---

## Rule 1: Never Break the STABLE CONTRACT

**The STABLE CONTRACT:** `JobQueue.publish(tenant_id, job_type, payload) -> UUID` and `get_status(job_id) -> JobStatus`.

Both `PostgresJobQueue` and `RedpandaJobQueue` implement this interface. Zero calling code in routers or the eval engine knows which implementation is active.

**Before editing `apps/api/core/jobqueue.py` or `apps/api/core/redpanda_queue.py`:**

```bash
grep -n "def publish\|def get_status" apps/api/core/jobqueue.py apps/api/core/redpanda_queue.py
```

Save these signatures. After your edit, re-run this grep and confirm they are byte-for-byte identical.

**Never:**
- Add a required parameter to `publish()` or `get_status()`
- Change the return type of either method
- Rename either method
- Make either method async

**If you need to add metadata to a job:** Put it in the `payload: dict` argument. The payload is opaque to the contract.

---

## Rule 2: Never Add `async` to the Synchronous Eval Engine Path

The eval engine (`apps/api/services/eval_engine.py`), all scorers, the gate engine, and the worker are **synchronous**. `confluent-kafka` was chosen specifically because it is synchronous and librdkafka-backed — switching to `aiokafka` would require making the entire pipeline async.

**Never:**
- Add `async def` to `run_eval()`, `score()`, `_compute_gate_result()`, or `evaluate()`
- Add `await` inside any scorer
- Import `asyncio` in eval_engine.py, gate_engine.py, or any scorer file
- Use `AsyncSession` from SQLAlchemy in the worker

**Check before editing:**

```bash
grep -n "async def\|await\|asyncio" apps/api/services/eval_engine.py apps/api/services/gate_engine.py apps/api/services/scorers/*.py
```

**Pass:** Zero matches.

**When the FastAPI router is async (which it is for the endpoint layer), it must call `run_eval` via a thread pool:**

```python
# Correct pattern in a router
import asyncio
loop = asyncio.get_event_loop()
loop.run_in_executor(None, run_eval, eval_run_id)
```

The worker calls `run_eval` directly in the main thread — no async needed there.

---

## Rule 3: Never Hardcode Model Names — Use `get_profile()`

All agent code must call `get_profile("standard")`, `get_profile("high_reasoning")`, or `get_profile("cheap")` to resolve the actual model name. Never write `"gemini-2.5-flash"` or `"gemini-2.0-flash"` directly in agent code.

**Pattern to follow:**

```python
# apps/api/core/model_profiles.py
from apps.api.core.model_profiles import get_profile

profile = get_profile("standard")  # Returns ModelProfile
model_name = profile.model_name    # "gemini-2.5-flash" resolved at runtime
```

**Check after editing any agent file:**

```bash
grep -rn "gemini-2.5-flash\|gemini-2.0-flash\|claude-\|gpt-4\|gpt-3" agents/
```

**Pass:** Zero matches.

**To add a new model:** Edit `config/model_profiles.yaml` only. Add a new profile name with `model_name`, `provider`, and `rpm`. Never hardcode in Python.

---

## Rule 4: CLI Must Never Import from `apps.api`

The CLI (`apps/cli/`) is a **separate deployable** that talks to the RedLine API over HTTP. It must never import from `apps.api.models`, `apps.api.core.db`, or any other `apps.api` module.

**Why:** The CLI is installed by developers on their machines. It does not have access to the Postgres connection, the SQLAlchemy session, or the ORM models. All data comes from HTTP responses.

**Never:**
- `from apps.api.models.eval import EvalRun` in CLI code
- `from apps.api.core.db import get_db` in CLI code
- Any direct `Session()` usage in CLI code

**Correct pattern:** All API calls go through `apps/cli/api_client.py`, which wraps `httpx.Client`.

```python
# Correct in apps/cli/commands/run.py
from apps.cli.api_client import RedLineClient

client = RedLineClient(base_url=config.base_url, api_key=config.api_key)
run = client.post_eval_run(agent_version_id=..., suite_id=...)
```

**Check:**

```bash
grep -rn "from apps.api\|import apps.api" apps/cli/
```

**Pass:** Zero matches.

---

## Rule 5: Never Make `emit_trace()` Raise

`emit_trace()` in `apps/api/core/clickhouse_client.py` must be non-fatal. A ClickHouse write failure must never fail an eval run or crash the worker.

**Correct pattern for every emit_trace call site:**

```python
try:
    emit_trace(
        run_id=str(eval_run.id),
        case_key=case.case_key,
        event_type="case_completed",
        data={"passed": result.passed}
    )
except Exception as e:
    logger.warning(f"ClickHouse trace write failed (non-fatal): {e}")
```

**Never:**
- Remove the `try/except` wrapper
- Re-raise the exception inside the except block
- Let `emit_trace()` itself raise (the function should catch internally too, as defense-in-depth)

**Check after editing eval_engine.py:**

```bash
grep -B2 -A5 "emit_trace" apps/api/services/eval_engine.py
```

Visually confirm every call site has `try:` above and `except Exception` below.

---

## Rule 6: Every New Scorer Gets Unit Tests in `test_scorers.py`

When adding a scorer to `apps/api/services/scorers/`:

1. The scorer class must inherit from or satisfy the protocol in `scorers/base.py`
2. The `score()` method must return `ScorerResult(passed=bool, detail=str)` — never a raw bool
3. Add unit tests to `apps/api/tests/unit/test_scorers.py`

**Unit test template for a new scorer:**

```python
# In apps/api/tests/unit/test_scorers.py
import pytest
from apps.api.services.scorers.my_new_scorer import MyNewScorer
from apps.api.services.scorers.base import ScorerResult

pytestmark = pytest.mark.unit  # Required — no DB, no network

def test_my_new_scorer_passes_when_condition_met():
    scorer = MyNewScorer(threshold=0.8)
    fake_transcript = [...]
    result = scorer.score(case=fake_case, transcript=fake_transcript)
    assert isinstance(result, ScorerResult)
    assert result.passed is True

def test_my_new_scorer_fails_when_condition_not_met():
    ...
    assert result.passed is False
    assert "reason" in result.detail.lower()
```

**Run to verify:**

```bash
pytest apps/api/tests/unit/test_scorers.py -v -m unit
```

---

## Rule 7: New Routes Belong in the Correct Service

RedLine's three microservices own their routes:

| Route prefix | Service | File |
|---|---|---|
| `/eval-runs`, `/ci` | `eval_service` | `apps/eval_service/main.py` |
| `/agents`, `/eval-suites` | `agent_service` | `apps/agent_service/main.py` |
| `/dashboard` | `gate_service` | `apps/gate_service/main.py` |
| `/auth` | `eval_service` | `apps/eval_service/main.py` |

**Also add to monolith for dev mode:**

```python
# apps/api/main.py
from apps.api.routers.my_new_router import router as my_router
app.include_router(my_router)
```

**After adding a route:**

```bash
curl http://localhost:8000/openapi.json | python -m json.tool | grep "my-new-route"
```

**Verify nginx routes it correctly** if in microservice mode:

```bash
grep -A 5 "location /my-route" infra/gateway.nginx.conf
```

---

## Rule 8: `_compute_gate_result` Must Stay Pure

`_compute_gate_result(passed_count, total, avg_cost_usd, avg_latency_ms, min_pass_rate, max_avg_cost_usd, max_avg_latency_ms)` in `apps/api/services/gate_engine.py` is a pure function. It has no side effects.

**Never inside `_compute_gate_result`:**
- DB access (`Session`, `db.query`, any SQLAlchemy calls)
- File I/O
- Network calls
- Logging with side effects (reading a file, writing to Redis)
- Raising exceptions (return a failed `GateResult` instead)

**The DB-backed wrapper is `evaluate(eval_run_id)`** — that's where Postgres access belongs. `_compute_gate_result` does pure math.

**To verify it stays pure, check for imports:**

```bash
grep -n "^from\|^import" apps/api/services/gate_engine.py | grep -v "typing\|dataclass\|pydantic"
```

**Pass:** No SQLAlchemy, Redis, httpx, or IO imports in the function's scope.

---

## Refactoring Checklist

Before opening a PR with a structural change:

- [ ] `grep -rn "gemini-2.5-flash\|gemini-2.0-flash" agents/` → zero results
- [ ] `grep -rn "from apps.api" apps/cli/` → zero results
- [ ] `grep -n "def publish\|def get_status" apps/api/core/jobqueue.py apps/api/core/redpanda_queue.py` → signatures unchanged
- [ ] `grep -n "async def\|await" apps/api/services/eval_engine.py` → zero results
- [ ] All new scorers have unit tests with `pytestmark = pytest.mark.unit`
- [ ] `_compute_gate_result` has no DB imports
- [ ] All `emit_trace()` calls are in `try/except`
- [ ] `pytest -m unit` passes (37+ tests, <2s)
