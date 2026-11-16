# Post-Tool-Use Hooks — RedLine

These checks must be performed **after** editing the listed files. They catch issues that are easy to create but expensive to debug later.

---

## Hook 1: After Editing Any Model File (`apps/api/models/`)

**Check:** Does the schema change require an Alembic migration?

**Run after editing:**

```bash
# Check if Alembic detects schema drift
alembic check 2>&1
```

If `alembic check` reports "No changes in schema detected" — no migration needed.

If it reports "Detected the following changes" — a new migration is required:

```bash
# Generate a new migration
alembic revision --autogenerate -m "describe_your_change_here"

# Review the generated migration file before applying
cat apps/api/migrations/versions/$(ls -t apps/api/migrations/versions/ | head -1)

# Apply
alembic upgrade head
```

**Migration file naming convention:** `000N_verb_noun.py` (e.g., `0005_add_triggered_by_col.py`).

**Also check:** Is the new model class imported in the models package so `Base.metadata` includes it?

```bash
grep -n "from apps.api.models" apps/api/models/__init__.py
```

If your new model file is not imported here, Alembic's autogenerate will not detect it.

**Pass condition:** `alembic check` reports no drift, or a migration has been generated and applied.

---

## Hook 2: After Editing `apps/api/requirements.txt`

**Check:** The `prometheus-fastapi-instrumentator` package is NOT present. Verify no new dependency introduced a starlette version conflict.

```bash
grep "prometheus-fastapi-instrumentator" apps/api/requirements.txt
```

**Pass:** Zero matches.

**Check starlette version compatibility:**

FastAPI 0.115.6 ships with `starlette==0.41.x`. Any package requiring `starlette>=1.0.0` will cause an import-time conflict.

```bash
# Check what starlette version is installed
pip show starlette | grep Version

# Check if any installed package conflicts
pip check 2>&1 | grep starlette
```

**If you see a conflict:**

```
prometheus-fastapi-instrumentator 8.x requires starlette>=1.0.0, but you have starlette 0.41.3
```

Remove `prometheus-fastapi-instrumentator` from requirements. Use `prometheus-client 0.21.1` directly — the metrics setup is already in `apps/api/core/telemetry.py`.

**Also check OpenTelemetry version compatibility:**

```bash
grep "opentelemetry" apps/api/requirements.txt
```

OpenTelemetry SDK `1.34.1` is the tested version. Do not upgrade without testing all OTel instrumentation in `telemetry.py`.

**Pass condition:** `pip check` reports no conflicts. `prometheus-fastapi-instrumentator` absent from requirements.

---

## Hook 3: After Adding a New Route

**Check:** The route is included in the correct service's `main.py` AND in the monolith `apps/api/main.py`.

```bash
# Check monolith
grep "include_router" apps/api/main.py

# Check service apps
grep "include_router" apps/eval_service/main.py
grep "include_router" apps/agent_service/main.py
grep "include_router" apps/gate_service/main.py
```

**Verify the route is reachable:**

```bash
# Start monolith
python -m uvicorn apps.api.main:app --port 8000

# Check OpenAPI includes the new route
curl http://localhost:8000/openapi.json | python -m json.tool | grep "your-new-path"
```

**Check nginx routes correctly (microservice mode):**

```bash
grep -A 8 "location" infra/gateway.nginx.conf
```

If the new route has a URL prefix not already in nginx config, add a `location` block.

**Also check the Helm configmap** if the route needs an env var:

```bash
cat helm/redline/templates/base/configmap.yaml
```

**Pass condition:** Route appears in OpenAPI spec. Correct service `main.py` includes it. Nginx routes it if in microservice mode.

---

## Hook 4: After Editing `apps/api/workers/eval_worker_v2.py`

**Check:** Kafka offsets are committed **after** successful processing, never before.

```bash
grep -n "commit\|consumer.commit\|auto.commit" apps/api/workers/eval_worker_v2.py
```

**Pass:** `consumer.commit()` (or equivalent) is called **after** `run_eval()` returns successfully and the job status is updated in Postgres.

**Fail:** `consumer.commit()` before `run_eval()`, or `enable.auto.commit = true` in the consumer config (this would commit offsets before the job is processed, causing silent job loss on worker crash).

**Also verify the consumer config:**

```bash
grep -A 20 "Consumer\|consumer_config" apps/api/workers/eval_worker_v2.py | grep "auto.commit\|enable.auto"
```

**Pass:** `"enable.auto.commit": False` in the consumer configuration.

**Verify error handling — what happens when `run_eval()` raises:**

```bash
grep -B5 -A10 "except" apps/api/workers/eval_worker_v2.py
```

On exception:
1. The job's Postgres record should be updated to `status="failed"` with the error message
2. The Kafka offset should NOT be committed (message will be redelivered to another worker)
3. The exception should be logged, not swallowed silently

**Pass condition:** `enable.auto.commit: False`. Commit only after successful processing. Exception path updates job status and does not commit offset.

---

## Hook 5: After Editing `apps/api/core/auth.py`

**Check:** Refresh token rotation is correct — old token is revoked, new token is issued.

```bash
grep -n "revoked_at\|rotate\|refresh" apps/api/core/auth.py | head -30
```

**Verify the reuse detection path:**

```bash
grep -n "reuse\|all.*revoke\|revoke.*all" apps/api/core/auth.py
```

If a refresh token is replayed (reuse detected):
1. The replayed token's `revoked_at` must be set
2. **All** refresh tokens for that `user_id` must be revoked — not just the replayed one
3. A `401 Unauthorized` must be returned with a message indicating session invalidation

**Pass condition:** On token reuse, `UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = '<user_id>'` (all tokens, not just the specific one).

---

## Hook 6: After Editing Any Agent File (`agents/`)

**Check:** No debug `print()` statements were introduced.

```bash
grep -n "^    print\|^        print\|print(" agents/rag_agent/agent.py agents/stateful_support_agent/agent.py agents/research_pipeline_agent/agent.py
```

**Pass:** Zero matches, or only `print()` calls that are deliberately console-facing (e.g., standalone script mode under `if __name__ == "__main__"`).

**The known bug:** `agents/rag_agent/agent.py`'s `_load_chunks()` function has debug print statements that dump PosixPath lists and raw chunks on every eval run. These must be removed before Phase 3.

**Also check after editing agents:**

```bash
grep -n "gemini-\|claude-\|gpt-4\|gpt-3" agents/rag_agent/agent.py agents/stateful_support_agent/agent.py agents/research_pipeline_agent/agent.py
```

**Pass:** Zero matches outside comment blocks.
