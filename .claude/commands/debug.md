# /debug — RedLine Issue Debugger

Use this command when something is broken. Each section maps a symptom to a root cause, the exact check to run, and the fix.

---

## Symptom 1: Eval Run Stuck in `pending`

**Most common cause:** The worker process is not running.

**Check:**

```bash
# Is the Phase 2 Redpanda worker running?
ps aux | grep eval_worker_v2

# Is the Phase 1 Postgres worker running?
ps aux | grep eval_worker
```

**If worker is dead — restart it:**

```bash
# Phase 2 (default for current stack)
python -m apps.api.workers.eval_worker_v2

# Phase 1 fallback (Postgres polling)
python -m apps.api.workers.eval_worker
```

**If worker is running but still stuck — check Redpanda connectivity:**

```bash
# Is Redpanda container up?
docker ps | grep redpanda

# Can the worker consumer reach Redpanda on 19092?
docker logs redline_redpanda | tail -30

# Try listing topics
docker exec -it redline_redpanda rpk topic list --brokers localhost:19092
```

**k3d-specific:** If the eval-service pod is consuming from `localhost:19092` instead of `host.k3d.internal:19092`, messages are published but never consumed. Check:

```bash
kubectl exec -it deploy/eval-service -- env | grep REDPANDA
```

**Fix:** Add `REDPANDA_BOOTSTRAP_SERVERS: "192.168.65.254:19092"` to the eval_service environment block in `docker-compose.yml`.

---

## Symptom 2: 429 from Gemini API

**Two different 429 causes — they look identical but require different fixes:**

**A) Per-minute quota (RPM limit):**
- `quotaId` in the error JSON is `GenerateRequestsPerMinutePerProject` or similar RPM field.
- The `LLMRateLimiter` should have caught this before the call.

Check current limiter state:

```bash
grep -n "current_usage\|_requests\|_window" apps/api/core/llm_rate_limiter.py
```

Inspect the rate limiter in the running worker — add a temporary debug log or check `llm_rate_limiter.py`'s deque length.

**Fix:** The `LLMRateLimiter.acquire()` uses a sliding window deque. Verify every LLM call in `llm_judge.py` and all three agents calls `rate_limiter.acquire()` before `generate_content()`.

**B) Daily quota (hard daily cap, free tier):**
- `quotaId` is `GenerateRequestsPerDayPerProject`.
- This cannot be rate-limited around — you are out of free quota for the day.

**Fix:** Wait until midnight PST for quota reset. For integration tests use `REDLINE_TEST_MODEL=gemini-2.0-flash` (cheaper, higher quota).

Check which model the LLM judge is using:

```bash
grep -n "get_profile\|judge_profile\|gemini" apps/api/services/scorers/llm_judge.py
```

The judge always uses `gemini-2.5-flash` regardless of the agent under test — if you're hitting judge quota, the Level 3 and Level 4 suites (7 and 6 cases respectively, each with a judge call) drain quota fast.

---

## Symptom 3: k3d Pod Can't Reach Postgres

**Check — verify host resolution from inside the pod:**

```bash
kubectl exec -it deploy/eval-service -- nslookup host.k3d.internal
kubectl exec -it deploy/eval-service -- env | grep DATABASE_URL
```

**Common cause:** `DATABASE_URL` in the pod still points to `localhost:5433` instead of `host.k3d.internal:5433`.

**Fix:** The `commonEnv` block in `helm/redline/templates/base/configmap.yaml` must set:

```yaml
DATABASE_URL: "postgresql://redline:redline_dev@host.k3d.internal:5433/redline"
```

Note: port is **5433**, not 5432. Local Postgres occupies 5432.

**Also check:** The `host-gateway` extra host is in the k3d cluster config so `host.k3d.internal` resolves. Verify with:

```bash
k3d cluster list
kubectl get nodes -o wide
```

---

## Symptom 4: Gate Always Fails — Every Eval Run is Blocked

**Step 1 — Check raw pass_rate from last run:**

```bash
# Get the most recent eval_run_id from Postgres (port 5433)
psql -h localhost -p 5433 -U redline -d redline -c "
  SELECT id, status, created_at FROM eval_runs ORDER BY created_at DESC LIMIT 5;
"

# Check case results for that run
psql -h localhost -p 5433 -U redline -d redline -c "
  SELECT case_id, passed, scorer_results FROM eval_case_results WHERE eval_run_id = '<run_id>';
"
```

**Step 2 — Check GatePolicy thresholds:**

```bash
psql -h localhost -p 5433 -U redline -d redline -c "
  SELECT * FROM gate_policies;
"
```

Compare `pass_rate = passed_cases / total_cases` vs `min_pass_rate`. If `pass_rate >= min_pass_rate` and the gate still fails, something is wrong in `_compute_gate_result`.

**Step 3 — Check `case_003` LLM judge rubric:**

`case_003` in the RAG agent baseline is a multi-turn session test. The judge rubric is strict: the second turn must address international shipping directly. If the RAG agent's second turn ignores session context, `case_003` fails.

```bash
grep -A 20 "case_003\|case_key: case_003" eval-suites/rag-agent/baseline.yaml
```

**Fix if judge rubric is too strict:** Edit `eval-suites/rag-agent/baseline.yaml` → `judge_rubric` for case_003. Then `python -m apps.api.scripts.push_suite` to re-load.

**Fix if LLM judge is rubber-stamping (everything passes):** Check `llm_judge.py`'s structured output prompt. The prompt must request `{"passed": bool, "reasoning": string}` and validate the response schema.

---

## Symptom 5: ClickHouse Traces Missing from Dashboard / Analytics

**ClickHouse is non-fatal by design.** A failed trace write must never fail an eval run. If traces are missing:

```bash
# Check ClickHouse container logs
docker logs redline_clickhouse 2>&1 | tail -50

# Check if the traces table exists
curl -s "http://localhost:8123/?query=SHOW+TABLES+FROM+redline" | grep traces

# Check row count
curl -s "http://localhost:8123/?query=SELECT+count(*)+FROM+redline.traces"
```

**Common causes:**

1. `init_clickhouse.py` was not run:
   ```bash
   python -m apps.api.scripts.init_clickhouse
   ```

2. `CLICKHOUSE_PASSWORD` is empty in `.env`:
   ```bash
   grep CLICKHOUSE_PASSWORD .env
   # Must be: CLICKHOUSE_PASSWORD=redline_dev
   ```

3. ClickHouse container on port 8123 (HTTP) or 9000 (native) is not responding:
   ```bash
   curl http://localhost:8123/ping
   # Should return: Ok.
   ```

---

## Symptom 6: "Invalid Token" / "Token Already Used" on Refresh

**By design:** Refresh token reuse triggers immediate revocation of ALL sessions for that user.

**Why:** Section ADR — if an old refresh token is replayed, it signals session hijacking. RedLine revokes all tokens for that user_id immediately (not just the reused one).

**To verify this happened:**

```bash
psql -h localhost -p 5433 -U redline -d redline -c "
  SELECT id, revoked_at FROM refresh_tokens WHERE user_id = '<user_id>' ORDER BY created_at DESC;
"
```

**Fix:** User must log in again with email + password. No shortcut — this is the correct security response to token reuse.

**If this is happening unexpectedly in development:** Check if you have multiple browser tabs or CLI sessions sharing the same refresh token. Each refresh rotates the token; the old one is immediately invalidated.

---

## Symptom 7: KEDA `ScaledObject` Shows `Unknown` Status

**This is usually correct behavior, not an error.**

```bash
kubectl get scaledobject -n redline
# Shows: READY=True, ACTIVE=Unknown or False
```

**"Unknown" or "False" for ACTIVE means:** The Redpanda consumer group lag is 0 — no messages are in the queue. KEDA scales the worker to 0 replicas when there's nothing to process.

**Verify lag is actually 0:**

```bash
docker exec -it redline_redpanda rpk group describe eval-worker-group --brokers localhost:19092
```

**If lag > 0 and KEDA is still not scaling:**

```bash
# Check KEDA operator logs
kubectl logs -n keda deploy/keda-operator | tail -30

# Verify TriggerAuthentication is bound
kubectl get triggerauthentication -n redline

# Check ScaledObject spec references correct topic and consumer group
kubectl get scaledobject eval-worker -n redline -o yaml | grep -A 10 triggers
```

The ScaledObject must reference `topic: eval-jobs`, `consumerGroup: eval-worker-group`, and `bootstrapServers: host.k3d.internal:19092`.

---

## Symptom 8: Alembic Migration Fails — `column already exists` or `table already exists`

**Check current migration state:**

```bash
alembic current
alembic history
```

**If the DB is ahead of Alembic's records (manual schema changes were made):**

```bash
# Stamp current head without running migrations
alembic stamp head
```

**If a migration is half-applied:**

```bash
# Downgrade one step
alembic downgrade -1

# Then re-apply
alembic upgrade head
```

**Never edit migration files that have already been applied to a real database.** Create a new migration instead.

---

## Quick Reference — Ports

| Service | Port | Check |
|---------|------|-------|
| Postgres | 5433 | `psql -h localhost -p 5433 -U redline -d redline` |
| Redis | 6379 | `redis-cli ping` |
| Redpanda Kafka | 19092 | `rpk topic list --brokers localhost:19092` |
| Redpanda Admin | 9644 | `curl localhost:9644/v1/brokers` |
| ClickHouse HTTP | 8123 | `curl localhost:8123/ping` |
| eval_service | 8001 | `curl localhost:8001/health` |
| agent_service | 8002 | `curl localhost:8002/health` |
| gate_service | 8003 | `curl localhost:8003/health` |
| nginx gateway | 8085 | `curl localhost:8085/health` |
| k3d gateway | 8000 | `curl localhost:8000/health` |
| Prometheus | 9090 | `curl localhost:9090/-/healthy` |
