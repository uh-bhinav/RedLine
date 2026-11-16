# Stop Hook — RedLine

Before ending any work session on RedLine, run these verification checks. Do not stop until all checks pass.

---

## Check 1: No Debug `print()` in Agent Files

```bash
grep -n "print(" agents/rag_agent/agent.py agents/stateful_support_agent/agent.py agents/research_pipeline_agent/agent.py
```

**Pass:** Zero matches, or only `print()` inside `if __name__ == "__main__"` blocks.

**Known issue (unfixed as of Phase 2):** `agents/rag_agent/agent.py` has debug print statements in `_load_chunks()` that dump PosixPath lists and chunk content. If you worked on the RAG agent, confirm these are removed:

```bash
grep -n "_load_chunks\|print" agents/rag_agent/agent.py
```

---

## Check 2: No Hardcoded Model Names Outside Config Files

```bash
grep -rn "gemini-2.5-flash\|gemini-2.0-flash\|gemini-2.0-flash-lite\|claude-sonnet\|claude-opus\|gpt-4o\|gpt-4\|gpt-3.5" \
  agents/ \
  apps/api/services/ \
  apps/api/workers/ \
  apps/cli/
```

**Pass:** Zero matches.

**The only acceptable locations for hardcoded model strings:**
- `config/model_profiles.yaml` (the source of truth)
- `.env` and `.env.example` (for `GEMINI_API_KEY` docs)
- `docs/` (documentation only)
- Test fixtures in `apps/api/tests/` where a specific model name is being tested

---

## Check 3: STABLE CONTRACT Is Intact

```bash
grep -n "def publish\|def get_status" apps/api/core/jobqueue.py apps/api/core/redpanda_queue.py
```

**Pass:** Both files show matching signatures:

```
apps/api/core/jobqueue.py:    def publish(self, tenant_id: UUID, job_type: str, payload: dict) -> UUID:
apps/api/core/jobqueue.py:    def get_status(self, job_id: UUID) -> JobStatus:
apps/api/core/redpanda_queue.py:    def publish(self, tenant_id: UUID, job_type: str, payload: dict) -> UUID:
apps/api/core/redpanda_queue.py:    def get_status(self, job_id: UUID) -> JobStatus:
```

**Fail:** Any signature mismatch, missing method, or changed parameter.

---

## Check 4: All New DB Models Are Registered

If you added a new SQLAlchemy model file during this session:

```bash
# Check what's in models/
ls apps/api/models/

# Check what's imported in __init__.py
cat apps/api/models/__init__.py
```

**Pass:** Every `.py` file in `apps/api/models/` (except `__init__.py`) has a corresponding import in `apps/api/models/__init__.py` and is listed in `__all__`.

**Why this matters:** Alembic's `--autogenerate` only detects tables that are imported into `Base.metadata`. A model class not imported will silently never be migrated.

---

## Check 5: Unit Tests Still Pass

```bash
pytest -m unit -q
```

**Pass:** All tests pass, exit code 0. The count should be 58 or more (never decreasing).

**If tests fail:** Do NOT stop work until they pass. A failing unit test means a regression was introduced.

---

## Check 6: No Async Contamination in Sync Pipeline

If you edited anything in the eval pipeline:

```bash
grep -rn "async def\|await\|asyncio.run\|AsyncSession" \
  apps/api/services/eval_engine.py \
  apps/api/services/gate_engine.py \
  apps/api/services/scorers/ \
  apps/api/workers/eval_worker.py \
  apps/api/workers/eval_worker_v2.py
```

**Pass:** Zero matches.

---

## Check 7: `emit_trace()` Calls Are Wrapped

```bash
grep -c "emit_trace" apps/api/services/eval_engine.py
```

Note the count. Then:

```bash
grep -c "try:" apps/api/services/eval_engine.py
```

The number of `try:` blocks should be >= the number of `emit_trace` calls (each trace call site needs a try/except).

---

## Check 8: CLI Has No Internal Imports

```bash
grep -rn "from apps.api\|import apps.api" apps/cli/
```

**Pass:** Zero matches.

---

## Final Stop Checklist

| Check | Command | Pass Condition |
|-------|---------|----------------|
| No debug prints in agents | `grep -rn "print(" agents/` | Zero or only `__main__` |
| No hardcoded model names | `grep -rn "gemini-2.5-flash" agents/ apps/api/services/` | Zero |
| STABLE CONTRACT intact | `grep "def publish\|def get_status" *.py` | Matching signatures |
| All new models registered | `cat apps/api/models/__init__.py` | All files imported |
| Unit tests pass | `pytest -m unit -q` | Exit code 0 |
| No async in sync pipeline | `grep -rn "async def" apps/api/services/eval_engine.py` | Zero |
| emit_trace wrapped | Manual review | All in try/except |
| CLI no internal imports | `grep -rn "from apps.api" apps/cli/` | Zero |
