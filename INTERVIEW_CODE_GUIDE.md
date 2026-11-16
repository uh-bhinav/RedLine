# RedLine — Interview Code Guide (v1: Map & Navigation)

This is a 3-part guide. **This file (v1)** is the map: where to go, what's high-value, and a ranked hotspot list.
**[INTERVIEW_CODE_GUIDE_v2.md](INTERVIEW_CODE_GUIDE_v2.md)** is the meat: exact functions and logic blocks to master.
**[INTERVIEW_CODE_GUIDE_v3.md](INTERVIEW_CODE_GUIDE_v3.md)** is practice: design-decision drills, rewrite list, 65 mock-interview questions tied to real code, and the 80/20 study plan.

Read v1 once to orient. Then work v2 with the source open beside it. Use v3 the night before.

---

## 1. Project Entry Map

Open files in this order. This is dependency order, not file-tree order — each step exists because the previous one doesn't make sense without it.

1. **`apps/api/models/eval.py`** and **`apps/api/models/gate.py`** — Everything else operates on these four tables (`EvalSuite`, `EvalCase`, `EvalRun`, `EvalCaseResult`, `GatePolicy`). Pay attention to: `EvalCase.turns`/`expectations` being untyped JSONB (not normalized columns), the `EvalRun` status CheckConstraint, and the `min_pass_rate` default on `GatePolicy` (it's duplicated elsewhere — see v2 §4).

2. **`apps/api/services/eval_engine.py`** — The core loop: `run_eval()`. This is the single most important file in the repo. Pay attention to: the `_build_case_adapter` → `_run_case` → `_compute_metrics` chain, the session lifecycle (`SessionLocal()`/`finally: db.close()`), and the exception handler's documented bug-fix history (real prior bugs, fixed, explained in comments).

3. **`apps/api/services/gate_engine.py`** — The gate: `_compute_gate_result()` (pure) and `evaluate()` (impure wrapper). Pay attention to: what's inside the pure function vs. what isn't and why (error-budget freeze), and the zero-total-defaults-to-fail guard.

4. **`apps/api/services/scorers/`** — Six files, all implementing the same `Scorer` Protocol from `base.py`. Pay attention to: the two-phase pattern repeated in `safety.py` and `recovery.py` (deterministic check first, optional LLM-judge escalation second), and why `SafetyScorer` explicitly declines to build a generic prompt-injection heuristic.

5. **`apps/api/services/adapters/`** — How an agent actually gets invoked: `base.py` (the `AgentAdapter` Protocol + `AgentTurnResult`), `local_python.py` (importlib, in-process), `http_adapter.py` (HTTP with asymmetric retry logic), `chaos_adapter.py` (decorator that wraps any adapter). Pay attention to: `local_python.py`'s `rsplit(":", 1)` entrypoint parsing, and why `http_adapter.py` never retries a `ReadTimeout`.

6. **`apps/api/core/jobqueue.py`** and **`apps/api/core/redpanda_queue.py`** — The STABLE CONTRACT: two implementations of the same `publish()`/`get_status()` signature, one Postgres-backed (`SELECT ... FOR UPDATE SKIP LOCKED`), one Kafka-backed. Pay attention to: the contract's exact signature, and the comment describing a real bug (`job_type` was silently ignored before a fix).

7. **`apps/api/workers/eval_worker.py`** and **`eval_worker_v2.py`** — The two consumers of the queue above: fixed-interval polling vs. Kafka consumer-group long-poll. Pay attention to: where the DB row lock is held (briefly) vs. where the Kafka offset commit happens (after processing, not before).

8. **`apps/api/core/security.py`** and **`apps/api/core/auth.py`** — Auth: dual credential-type dispatch (API key vs JWT) into one `AuthContext`, JWT issuance/decode, and refresh-token rotation with reuse detection. Pay attention to: the `rotate_refresh_token()` step sequence (v2 §2) — this is the highest-density security function in the repo.

9. **`apps/api/routers/eval_runs.py`**, **`ci.py`**, **`eval_suites.py`**, **`dashboard.py`** — The HTTP surface. Pay attention to: `ci.py`'s deliberate indirection (it does NOT return pass/fail — the gate verdict comes from polling a different endpoint), and `dashboard.py`'s `_owned_agent()` 404-not-403 pattern.

10. **`apps/api/services/ars_engine.py`**, **`diff_engine.py`**, **`mining/engine.py`**, **`load_engine.py`** — The four "novelty feature" engines with real algorithms (chaos engineering lives in the adapter from step 5, not here). Pay attention to: each one splits into a pure function + a DB-backed orchestrator, the same discipline as `gate_engine.py`.

11. **`apps/cli/`** — `api_client.py`, `main.py`, `commands/run.py`, `commands/register_version.py`. Pay attention to: the HTTP-only architecture rule and how `register_version.py` computes content hashes differently for local-Python vs. HTTP entrypoints.

12. **`agents/rag_agent/agent.py`**, **`agents/stateful_support_agent/agent.py`**, **`agents/research_pipeline_agent/agent.py`** — The three agents-under-test. Pay attention to: the RAG agent's threshold-based deterministic refusal (not left to the LLM), and the research-pipeline agent's dead cost-tracking variables (a real bug — great "find it" material).

---

## 2. High-Value Files

Only files with real interview value. Config, migrations, boilerplate CRUD, and generated code are excluded — see the "Low Interview Value" callout at the end of this section.

| File | Why interviewers care | Study time | Priority |
|---|---|---|---|
| `apps/api/services/eval_engine.py` | The core orchestration loop; documented bug-fix history in comments | 45 min | ⭐⭐⭐⭐⭐ |
| `apps/api/services/gate_engine.py` | Textbook pure/impure split; the single most likely "write this" ask | 25 min | ⭐⭐⭐⭐⭐ |
| `apps/api/core/auth.py` | Refresh-token rotation + reuse detection; real security depth | 30 min | ⭐⭐⭐⭐⭐ |
| `apps/api/core/jobqueue.py` + `redpanda_queue.py` | The STABLE CONTRACT — transport-swappable interface, a real system-design pattern | 40 min | ⭐⭐⭐⭐⭐ |
| `apps/api/services/adapters/local_python.py` + `http_adapter.py` + `base.py` | The Protocol every agent execution path satisfies; importlib mechanics; retry-safety reasoning | 30 min | ⭐⭐⭐⭐⭐ |
| `apps/api/workers/eval_worker.py` + `eval_worker_v2.py` | Polling vs. event-driven consumer contrast — classic distributed-systems interview topic | 25 min | ⭐⭐⭐⭐ |
| `apps/api/core/security.py` | Dual-credential dispatch, tenant-replay-after-deletion check, RBAC dependency composition | 25 min | ⭐⭐⭐⭐ |
| `apps/api/services/scorers/base.py` + `safety.py` + `recovery.py` | Protocol-based plugin design; two-phase deterministic+LLM scoring pattern | 25 min | ⭐⭐⭐⭐ |
| `apps/api/services/ars_engine.py` | Weighted composite score + SLO/error-budget — clean, quotable, ML-adjacent | 20 min | ⭐⭐⭐⭐ |
| `apps/api/services/diff_engine.py` | 2×2 classification of code-change × behavior-change via embedding cosine similarity | 20 min | ⭐⭐⭐⭐ |
| `apps/api/services/mining/engine.py` | The one real unsupervised-ML component (DBSCAN clustering) | 20 min | ⭐⭐⭐⭐ |
| `apps/api/services/load_engine.py` | Percentile math + `ThreadPoolExecutor` concurrency while staying Rule-1-synchronous | 20 min | ⭐⭐⭐⭐ |
| `apps/api/services/adapters/chaos_adapter.py` | Decorator-over-Protocol fault injection; marker-based detection | 15 min | ⭐⭐⭐ |
| `apps/api/core/redis_client.py` | Sliding-window rate limiter — has a real subtlety worth understanding (v2 §2) | 15 min | ⭐⭐⭐ |
| `apps/api/routers/ci.py` | The endpoint that embodies the whole product thesis ("physically blocks bad deploys") | 10 min | ⭐⭐⭐⭐ |
| `apps/api/routers/dashboard.py` | `_owned_agent()` security idiom; also has a real N+1 perf bug worth being able to discuss | 20 min | ⭐⭐⭐ |
| `apps/api/routers/eval_suites.py` | YAML→DB upsert transaction pattern (`flush` vs `commit`) | 15 min | ⭐⭐⭐ |
| `apps/api/schemas/eval_suite_yaml.py` | Validates against a live enum instead of duplicating values — a good idiom to name-drop | 10 min | ⭐⭐⭐ |
| `apps/cli/api_client.py` + `commands/register_version.py` | HTTP-only CLI architecture; content-hash computation split by entrypoint type | 15 min | ⭐⭐⭐ |
| `agents/rag_agent/agent.py` | Deterministic threshold-based refusal — the RAG failure mode this benchmark exists to catch | 15 min | ⭐⭐⭐⭐ |
| `agents/stateful_support_agent/agent.py` | In-place `session_state` mutation across turns; silent extraction-failure fallback | 15 min | ⭐⭐⭐ |
| `agents/research_pipeline_agent/agent.py` | Multi-agent pipeline with a genuine "fails open" bug in the verifier + dead cost variables | 15 min | ⭐⭐⭐ |

**Low Interview Value — skim only or skip entirely:** `apps/api/main.py` (monolith router-include boilerplate), `apps/eval_service/main.py`/`agent_service/main.py`/`gate_service/main.py` (thin FastAPI app factories), `apps/api/migrations/versions/*` (Alembic-generated), `apps/api/core/config.py` (pydantic-settings field list), `apps/api/core/telemetry.py` (Prometheus counter declarations — know it exists, don't memorize it), `helm/` and `infra/` (covered in the separate Docker guide, not code logic), any router endpoint that's plain CRUD with no business logic (e.g. simple agent-registration GETs), `apps/api/scripts/*.py` (one-shot seed/init scripts — know what they do, not how).

---

## 5. Code Navigation Checklist

Work through this in order. Each box names the actual file — don't skip ahead.

```
□ Read apps/api/models/eval.py + models/gate.py — know the four core tables cold
□ Read apps/api/services/eval_engine.py — trace run_eval() top to bottom once, on paper
□ Read apps/api/services/gate_engine.py — be able to write _compute_gate_result() from memory
□ Read all 6 files in apps/api/services/scorers/ — note the two-phase pattern in safety.py/recovery.py
□ Read apps/api/services/adapters/base.py, local_python.py, http_adapter.py — the Protocol + two real implementations
□ Read apps/api/core/jobqueue.py + redpanda_queue.py side by side — same signature, different transport
□ Read apps/api/workers/eval_worker.py then eval_worker_v2.py — contrast polling vs. consumer-group
□ Read apps/api/core/auth.py — trace rotate_refresh_token() step by step, know every line number
□ Read apps/api/core/security.py — trace require_api_key()'s dual-dispatch branch
□ Read apps/api/routers/ci.py — understand why it does NOT return pass/fail
□ Read apps/api/routers/eval_runs.py + eval_suites.py + dashboard.py
□ Read apps/api/services/ars_engine.py — the weighted-sum + error-budget formulas
□ Read apps/api/services/diff_engine.py — the 2x2 classification logic
□ Read apps/api/services/mining/engine.py — the DBSCAN clustering + significance filter
□ Read apps/api/services/load_engine.py — percentile calc + ThreadPoolExecutor pattern
□ Read apps/api/services/adapters/chaos_adapter.py — fault modes + marker-based detection
□ Read apps/cli/api_client.py + commands/run.py + commands/register_version.py
□ Read agents/rag_agent/agent.py — retrieval + threshold refusal
□ Read agents/stateful_support_agent/agent.py — session_state structure + memory extraction
□ Read agents/research_pipeline_agent/agent.py — planner/researcher/verifier/synthesizer chain
□ Review v2's "known gaps" list (§4 bottom) — these are your best debugging-question answers
□ Do one full pass of v3's Rewrite Practice list, from memory, no code open
```

---

## 6. Interview Hotspots

Ranked most-likely to least-likely to come up, based on how central and how "explainable in 90 seconds" each piece is.

1. **The STABLE CONTRACT job queue** (`jobqueue.py` + `redpanda_queue.py`) — "How would you swap a synchronous DB queue for Kafka without breaking callers?" is a textbook systems-design question, and this repo has a real, working answer.
2. **`_compute_gate_result()`** (`gate_engine.py`) — "Write a function that decides pass/fail against configurable thresholds" — almost certain to be asked as a live-coding warm-up.
3. **Refresh-token rotation with reuse detection** (`auth.py:rotate_refresh_token`) — the highest-density security question in the repo; if they ask one auth question, it's this.
4. **RAG retrieval + refusal** (`rag_agent/agent.py`) — AI/ML-flavored interviewers will zero in on this: "how do you stop your agent from hallucinating?"
5. **Polling vs. event-driven workers** (`eval_worker.py` vs `eval_worker_v2.py`) — classic "why did you move from X to Y" architecture narrative.
6. **DBSCAN failure clustering** (`mining/engine.py`) — the one place with a genuine unsupervised-ML algorithm; expect a "why DBSCAN and not k-means" follow-up.
7. **`ci.py`'s indirection** — "does your CI endpoint return pass/fail synchronously?" — the honest answer (no, it polls) is more interesting than a synchronous design would be.
8. **The eval engine's documented bug-fix history** (`eval_engine.py`'s exception handler) — "tell me about a bug you found and fixed" — you have three real ones with comments explaining each, verbatim.
9. **Tenant isolation via 404-not-403** (`dashboard.py:_owned_agent`, `security.py:get_tenant_context`) — a sharp, quotable security decision.
10. **Behavioral diff classification** (`diff_engine.py`) — the cleverest of the five novelty features; the run-id-vs-version-id parameterization decision is a good "why did you design it this way" story.
11. **`ThreadPoolExecutor` for load testing while staying synchronous** (`load_engine.py`) — a good concurrency-without-asyncio talking point, directly ties back to architecture Rule 1.
12. **The chaos-adapter decorator pattern** — smaller, but a clean "explain a design pattern you used" answer if asked.
13. **Known gaps** (missing `iat` claim, dead cache write in `get_eval_run`, N+1 in `dashboard.py`, dead cost-tracking variables in the research-pipeline agent) — lower probability of being *asked* directly, but very high value if a debugging question comes up, since you can point at real code instead of hypothesizing.

Full detail on every item above is in v2. Practice questions for each are in v3.
