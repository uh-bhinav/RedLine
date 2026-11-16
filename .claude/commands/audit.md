# /audit — RedLine Codebase Audit

Run this command to verify RedLine's invariants are intact. Check each item in order. Each has a pass/fail criterion. **All must pass before any release or Phase 3 work begins.**

---

## 1. Gate Threshold Default — `apps/api/models/gate.py`

**Check:** `GatePolicy.min_pass_rate` default is exactly `0.90`.

```bash
grep -n "min_pass_rate" apps/api/models/gate.py
```

**Pass:** Output shows `server_default=text("0.9")` or `default=0.9`.  
**Fail:** Any other value, or no default at all (missing policy must NOT silently auto-pass).

---

## 2. API Keys — SHA256 Hash Stored, Never Raw — `apps/api/models/api_key.py`, `apps/api/scripts/create_api_key.py`

**Check:** The raw API key (prefixed `rl_live_`) is never written to the database.

```bash
grep -n "key_hash\|sha256\|hexdigest" apps/api/scripts/create_api_key.py
grep -n "INSERT\|key_hash" apps/api/models/api_key.py
```

**Pass:** `create_api_key.py` computes `hashlib.sha256(raw_key.encode()).hexdigest()` before calling `db.add(ApiKey(key_hash=...))`. The raw key is only printed once to stdout.  
**Fail:** Any code that stores `raw_key` or `api_key` string directly into the DB row.

---

## 3. Refresh Tokens — `revoked_at` is Nullable — `apps/api/models/refresh_token.py`

**Check:** `revoked_at` column allows NULL (active tokens have no revocation timestamp).

```bash
grep -n "revoked_at" apps/api/models/refresh_token.py
```

**Pass:** `revoked_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)` or equivalent.  
**Fail:** `nullable=False` or missing `Optional`.

---

## 4. `emit_trace()` Always Wrapped in Try/Except — `apps/api/services/eval_engine.py`

**Check:** Every call to `emit_trace()` is inside a `try/except` block so a ClickHouse failure never kills an eval run.

```bash
grep -n "emit_trace" apps/api/services/eval_engine.py
```

Then visually confirm each call site is surrounded by `try: ... except Exception:`.

**Pass:** All `emit_trace()` calls are in `try/except`. The `except` block logs a warning but does NOT re-raise.  
**Fail:** Any `emit_trace()` call outside a `try/except`, or an `except` that re-raises.

Also check `clickhouse_client.py` itself:

```bash
grep -n "except" apps/api/core/clickhouse_client.py
```

**Pass:** `emit_trace()` in `clickhouse_client.py` catches all exceptions internally and logs without raising.

---

## 5. No Hardcoded Model Names in Agents — `agents/`

**Check:** Agents call `get_profile()` for model resolution. No model name strings like `"gemini-2.5-flash"` or `"gemini-2.0-flash"` appear directly in agent code.

```bash
grep -rn "gemini-2.5-flash\|gemini-2.0-flash\|gemini-2.0-flash-lite" agents/
```

**Pass:** Zero matches in `agents/` directory.  
**Fail:** Any match outside `config/model_profiles.yaml` and `.env`/`.env.example`.

Cross-check that agents use the profile system:

```bash
grep -rn "get_profile\|model_profile" agents/
```

**Pass:** Each agent file references `get_profile(...)`.

---

## 6. CLI Has No Direct DB Imports — `apps/cli/`

**Check:** The CLI never imports from `apps.api.models` or `apps.api.core.db`. It communicates with the API only via httpx.

```bash
grep -rn "from apps.api\|import apps.api" apps/cli/
```

**Pass:** Zero matches.  
**Fail:** Any import from `apps.api.*` in the CLI package.

Cross-check CLI uses httpx:

```bash
grep -rn "httpx\|api_client" apps/cli/
```

**Pass:** All API calls go through `apps/cli/api_client.py` which uses `httpx`.

---

## 7. Scorers Return `ScorerResult` — `apps/api/services/scorers/`

**Check:** Every scorer's `score()` method returns a `ScorerResult` object, never a raw `bool`.

```bash
grep -n "return " apps/api/services/scorers/contains_match.py apps/api/services/scorers/cost.py apps/api/services/scorers/latency.py apps/api/services/scorers/llm_judge.py
```

**Pass:** Every `return` in a `score()` method is `return ScorerResult(passed=..., detail=...)`.  
**Fail:** Any `return True`, `return False`, or `return {"passed": ...}` raw dict.

---

## 8. ClickHouse Password in `.env` — `.env`

**Check:** `CLICKHOUSE_PASSWORD` is set to a non-empty value (default: `redline_dev` for local dev).

```bash
grep "CLICKHOUSE_PASSWORD" .env
```

**Pass:** `CLICKHOUSE_PASSWORD=redline_dev` (or non-empty value).  
**Fail:** `CLICKHOUSE_PASSWORD=` (empty string) or key missing. An empty password causes 403 errors from ClickHouse when running on Docker network.

---

## 9. prometheus-fastapi-instrumentator Not in Requirements — `apps/api/requirements.txt`

**Check:** This package is NOT installed (it requires `starlette>=1.0.0`, incompatible with FastAPI 0.115.6's `starlette 0.41.x`).

```bash
grep "prometheus-fastapi" apps/api/requirements.txt
```

**Pass:** Zero matches.  
**Fail:** Any match — this will cause an import error at startup.

---

## 10. STABLE CONTRACT Intact — `apps/api/core/jobqueue.py`, `apps/api/core/redpanda_queue.py`

**Check:** Both `PostgresJobQueue` and `RedpandaJobQueue` expose exactly `publish(tenant_id, job_type, payload) -> UUID` and `get_status(job_id) -> JobStatus`. Signature must not have changed.

```bash
grep -n "def publish\|def get_status" apps/api/core/jobqueue.py apps/api/core/redpanda_queue.py
```

**Pass:** Both files show matching signatures.  
**Fail:** Any signature mismatch, extra required parameters, or missing methods.

---

## 11. Debug `print()` Removed from RAG Agent — `agents/rag_agent/agent.py`

**Check:** The known bug — debug print statements in `_load_chunks()` — has been removed.

```bash
grep -n "^    print\|^        print" agents/rag_agent/agent.py
```

**Pass:** Zero matches inside `_load_chunks()`.  
**Fail:** Any print() call producing PosixPath lists or chunk dumps on every eval run.

---

## Audit Summary

| Check | File | Pass Condition |
|-------|------|----------------|
| Gate default 0.90 | `models/gate.py` | `default=0.9` |
| API key SHA256 only | `scripts/create_api_key.py` | hexdigest stored |
| refresh_token revoked_at nullable | `models/refresh_token.py` | `Optional[datetime]` |
| emit_trace in try/except | `services/eval_engine.py` | all sites wrapped |
| No hardcoded model names | `agents/` | zero grep hits |
| CLI no DB imports | `apps/cli/` | zero grep hits |
| Scorers return ScorerResult | `services/scorers/` | no raw bool returns |
| ClickHouse password set | `.env` | non-empty value |
| No prometheus-fastapi-instrumentator | `requirements.txt` | zero grep hits |
| STABLE CONTRACT intact | `jobqueue.py`, `redpanda_queue.py` | matching signatures |
| Debug prints removed | `agents/rag_agent/agent.py` | zero print() hits |
