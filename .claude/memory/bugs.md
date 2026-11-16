# RedLine — Known Bugs

Active bugs discovered during Phase 1 and Phase 2. Each entry has a symptom, file, root cause, and fix.

---

## Bug 1: Debug `print()` Statements in RAG Agent

**Status:** ⚠️ OPEN — unfixed as of Phase 2 completion

**Symptom:** Every eval run that invokes the RAG agent produces garbage output in worker stdout:

```
[PosixPath('agents/rag_agent/knowledge_base/docs/refund_policy.md'), ...]
True
Chunk 0: TrailLight Gear — Refund Policy...
Chunk 1: ...
```

This output appears during `_load_chunks()` on every call to `run_turn()`, polluting worker logs and making it impossible to read meaningful log output.

**File:** `agents/rag_agent/agent.py`

**Location:** Inside `_load_chunks()` function

**Root cause:** Debug print statements were left in during development and never removed.

**Fix:**

```bash
# Locate the print statements
grep -n "print(" agents/rag_agent/agent.py

# Remove all print() calls inside _load_chunks()
# They should look like:
#   print(list(self.docs_path.glob("*.md")))
#   print(True)
#   print(f"Chunk {i}: {chunk[:100]}")
```

**Impact:** Low (cosmetic, no functional impact on eval results). High annoyance during debugging — worker logs are unreadable. **Must fix before Phase 3.**

---

## Bug 2: k3d `eval-service` Pod Uses `localhost:19092` for Redpanda

**Status:** ⚠️ OPEN — unfixed as of Phase 2 completion

**Symptom:** In k3d deployment, eval runs submitted via the API are published to Redpanda (`localhost:19092` from the eval-service pod's perspective), but the eval worker pod — also running in k3d — cannot consume them because `localhost:19092` inside the pod resolves to the pod itself, not the Docker host.

**Effect:** Eval runs stay in `pending` status forever in k3d mode. The Redpanda console shows messages published to `eval-jobs` but the consumer group lag never decreases.

**File:** `docker-compose.yml` — `eval_service` service `environment` block

**Root cause:** The `REDPANDA_BOOTSTRAP_SERVERS` environment variable is not set for the `eval_service` container. It defaults to `localhost:19092`, which is correct when running locally but wrong inside k3d pods where `localhost` refers to the pod's loopback interface.

**Fix:**

Add to the `eval_service` environment block in `docker-compose.yml`:

```yaml
eval_service:
  environment:
    REDPANDA_BOOTSTRAP_SERVERS: "192.168.65.254:19092"
```

`192.168.65.254` is the Docker Desktop host gateway IP (Mac-specific). Alternatively, use `host.k3d.internal:19092` if the k3d cluster has `host-gateway` extra hosts configured.

**Also update the Helm configmap** (`helm/redline/templates/base/configmap.yaml`):

```yaml
REDPANDA_BOOTSTRAP_SERVERS: "host.k3d.internal:19092"
```

**Impact:** High — k3d eval runs are completely broken without this fix. Docker Compose mode is unaffected (localhost:19092 works correctly there because the service and Redpanda share the Docker network).

---

## Bug 3: Section 10 Acceptance Tests Not Run — Level 3 and Level 4

**Status:** ⚠️ OPEN — blocked on Gemini free-tier daily quota

**Symptom:** The Phase 2 acceptance criteria require verifying gate verdicts for:
- Level 3: `stateful-support-agent` (7-case eval suite, `stateful-support-agent/baseline.yaml`)
- Level 4: `research-pipeline-agent` (6-case eval suite, `research-pipeline-agent/baseline.yaml`)

These suites have NOT been run end-to-end. Gate verdicts for these agents are unverified.

**File:** `eval-suites/stateful-support-agent/baseline.yaml`, `eval-suites/research-pipeline-agent/baseline.yaml`

**Root cause:** The LLM judge scorer makes one Gemini API call per case. Running 7 + 6 = 13 cases, plus the research pipeline agent's internal Gemini calls (Planner + Agent A + Agent B + Verifier + Synthesizer = 5 calls per research step), exhausts the free-tier daily quota (`GenerateRequestsPerDayPerProject`) before all cases complete.

**Fix:**

Option A — Run during off-peak hours with quota reset:

```bash
# Wait for midnight PST quota reset
REDLINE_TEST_MODEL=gemini-2.0-flash python -m apps.cli.main run --suite baseline --agent stateful-support-agent
```

Option B — Upgrade to a paid Gemini tier for these acceptance tests.

Option C — Mock the LLM judge for the acceptance test run to verify the eval infrastructure (not the agent quality):

```bash
SKIP_LLM_JUDGE=1 pytest apps/api/tests/integration/test_eval_end_to_end.py -v
```

**Impact:** Medium — the eval and gate infrastructure is proven to work via the RAG agent (Level 1). Level 3 and Level 4 gate verdicts are functionally equivalent paths through the same code. The risk is unknown agent quality, not unknown infrastructure correctness.

---

## Bug 4: `eval_worker_v2.py` May Not Set `enable.auto.commit=False`

**Status:** ⚠️ VERIFY — not confirmed from Phase 2 code review

**Symptom:** If `enable.auto.commit=True` (Kafka consumer default), offsets are committed before `run_eval()` completes. A worker crash after commit but before eval completion results in silent job loss — the eval run stays in `running` status forever.

**File:** `apps/api/workers/eval_worker_v2.py`

**Check:**

```bash
grep -n "auto.commit\|enable.auto" apps/api/workers/eval_worker_v2.py
```

**Required:** `"enable.auto.commit": False` in the consumer config dict.

**Fix if missing:**

```python
consumer_config = {
    "bootstrap.servers": settings.REDPANDA_BOOTSTRAP_SERVERS,
    "group.id": "eval-worker-group",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,  # REQUIRED — manual commit after processing
}
```

And verify `consumer.commit()` is called after `run_eval()` returns successfully.

---

## Bug Tracker Summary

| # | Description | File | Status | Impact |
|---|-------------|------|--------|--------|
| 1 | Debug prints in RAG agent `_load_chunks()` | `agents/rag_agent/agent.py` | OPEN | Low (cosmetic) |
| 2 | k3d eval-service uses `localhost:19092` | `docker-compose.yml` | OPEN | High (k3d broken) |
| 3 | Level 3 + Level 4 gate verdicts not verified | eval-suites/\*/baseline.yaml | OPEN | Medium (quota) |
| 4 | `enable.auto.commit` may not be False | `workers/eval_worker_v2.py` | VERIFY | High (data loss) |
