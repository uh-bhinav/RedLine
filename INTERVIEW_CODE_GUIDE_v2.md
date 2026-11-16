# RedLine — Interview Code Guide (v2: Exact Functions & Critical Logic)

Part 2 of 3. See [INTERVIEW_CODE_GUIDE.md](INTERVIEW_CODE_GUIDE.md) for the navigation map, [INTERVIEW_CODE_GUIDE_v3.md](INTERVIEW_CODE_GUIDE_v3.md) for practice/drills. Line numbers are approximate — the code may have shifted slightly since this was written; use function names as your anchor.

---

## 3. Exact Functions to Master

### 3.1 Eval Engine — `apps/api/services/eval_engine.py`

**`run_eval(eval_run_id)`** — lines ~116-252
Purpose: top-level synchronous orchestrator. Loads `EvalRun`/`AgentVersion`/`EvalCase`s, transitions status `pending→running`, builds one adapter for the run, loops cases calling `_run_case`, persists `EvalCaseResult` rows, emits telemetry, transitions `running→completed`, triggers ARS computation. On exception: `running→failed` with truncated error, re-raises.
Inputs: `eval_run_id: UUID`. Outputs: `None` (all side effects).
Dependencies: `SessionLocal`, `build_adapter`, `_build_case_adapter`, `_run_case`, `_compute_metrics`, `emit_trace`, Prometheus counters, OTel span, lazily `ars_engine.evaluate_ars`.
Must understand:
- Lines ~122-141: `db = SessionLocal()` / `try...finally: db.close()` (Rule 11 pattern). Status set to `running` and **committed before any case runs** — so a mid-run crash leaves visible "running" state, not stuck "pending."
- Lines ~219-250 (exception handler): re-fetches the run row (original may be stale after `db.rollback()`), truncates error to 2000 chars, records the **actual** exception on the OTel span (not a bare `Exception()` — a prior bug did that), emits the failure trace against the run's **real** `tenant_id` (a prior bug used `uuid.uuid4()`, which broke ClickHouse's `ORDER BY (tenant_id, ...)` and made failed runs invisible per-tenant).
- Lines ~207-217: ARS computation happens here, in the write path, deliberately not inside `gate_engine.evaluate()` (the read path) — know this separation and be able to justify it (write-once vs. read-many).
Could they ask me to code this? **POSSIBLY.** Not the whole thing verbatim (too much telemetry plumbing) — but you should be able to write the skeleton unaided: open session → load run/version/cases → mark running → loop cases → mark completed/failed in a try/except → close session in finally. That skeleton alone answers most versions of this question.

**`_run_case(adapter, case)`** — lines ~81-106
Purpose: executes one eval case turn-by-turn, builds the transcript, runs every scorer, ANDs their `passed` flags.
Inputs: `adapter: AgentAdapter`, `case: EvalCase`. Outputs: `(transcript: list[Turn], overall_passed: bool, scorer_results: dict)`.
Dependencies: `adapter.run_turn()` (the STABLE-ish adapter contract), each `Scorer.score()`.
Must understand:
- `session_state: dict = {}` created fresh per case, threaded by reference across turns — no serialization (this is the payoff of Rule 9's importlib-not-subprocess decision).
- The scorer loop does **not** short-circuit on first failure — every scorer still runs and its result is recorded, even after one has already failed. This costs an LLM call even on a deterministic failure; know the tradeoff (full diagnostics vs. cost) and be ready to defend or critique it.
- `overall_passed = True`, flipped to `False`, never flipped back — simple AND-reduction.
Could they ask me to code this? **YES.** This is the second most likely "write it" ask after `_compute_gate_result`. Practice: build the transcript list, append scripted user turn then real assistant turn, loop scorers without short-circuiting, return the three-tuple.

**`_build_case_adapter(base_adapter, case)`** — lines ~55-78
Purpose: wraps `base_adapter` in a `ChaosAdapter` only if `case.expectations["chaos"]` is configured; otherwise passes through unchanged.
Must understand: this is per-case, not per-run, because only some cases in a suite configure chaos. It's the clearest live example of the decorator-satisfies-Protocol pattern in the repo — the caller (`_run_case`) never knows or cares whether it received a real adapter or a wrapped one.
Could they ask me to code this? **POSSIBLY** — simple once you know the `ChaosAdapter` constructor shape, but that shape isn't obvious without having read `chaos_adapter.py` first.

**`_compute_metrics(transcript)`** — lines ~109-113
Purpose: sums `cost_usd` and `latency_ms` across assistant-role turns only.
```
sum(t.cost_usd or 0.0 for t in transcript if t.role == "assistant")
```
The `or 0.0` guards `None` (a failed/judged turn may leave cost unset). Note this exact sum is **independently duplicated** in `CostScorer` and `LatencyScorer` — a real "why isn't this shared" design-smell you should be ready to name if asked.
Could they ask me to code this? **YES** — trivial, but they might use it to test whether you catch the `None`-guard necessity.

---

### 3.2 Gate Engine — `apps/api/services/gate_engine.py`

**`_compute_gate_result(passed_count, total, avg_cost_usd, avg_latency_ms, min_pass_rate, max_avg_cost_usd, max_avg_latency_ms, ars=None, min_ars=None)`** — lines ~44-85 — **THE PURE FUNCTION**
Purpose: pure threshold comparison. Returns `GateResult(passed: bool, reasons: list[str])`. Zero total is an automatic fail, not a vacuous pass.
Inputs: primitives only, several `Optional`. Output: `GateResult` (a `BaseModel`, not a raw bool — Rule 6-adjacent discipline even outside the scorer package).
Dependencies: **none** — no DB, no Redis, no file I/O, raises nothing. This is architecture Rule 5 made literal.
Must understand:
- `if total == 0: return GateResult(passed=False, ...)` — missing/empty results must never silently pass.
- Four independent threshold checks (pass_rate, cost, latency, ARS), each appending a reason string rather than short-circuiting — `reasons` can report multiple simultaneous violations at once.
- Each optional threshold (`max_avg_cost_usd`, `max_avg_latency_ms`, `min_ars`) uses the identical `if x is not None and ...` convention — `None` means "no check," not "check against zero."
- `passed = len(reasons) == 0` — the gate passes iff nothing was collected as a violation.
Could they ask me to code this? **YES — this is the single most likely live-coding ask in the whole repo.** Practice writing this cold, including the zero-total guard and the `None`-means-no-check convention for every optional threshold.

**`evaluate(eval_run_id)`** — lines ~88-154 — **THE IMPURE WRAPPER**
Purpose: DB-backed orchestrator. Loads `EvalRun` + all its `EvalCaseResult`s, aggregates `passed_count`/`avg_cost_usd`/`avg_latency_ms` from persisted `metrics` JSONB, resolves `GatePolicy` (or defaults), reads (does NOT recompute) the `ARSSnapshot`, calls the pure function, then separately applies an error-budget freeze that can force `passed=False` regardless of the pure function's own verdict.
Must understand:
- Policy resolution asymmetry: `min_pass_rate` defaults to a real enforced number (`DEFAULT_MIN_PASS_RATE = 0.9`) when no `GatePolicy` row exists; `max_avg_cost_usd`/`max_avg_latency_ms`/`min_ars` all default to `None` ("no check") in the same no-policy case. Know why: pass-rate is the one dimension that must never silently mean "anything goes"; cost/latency/ARS ceilings are opt-in.
- The error-budget freeze (lines ~140-151) is deliberately **outside** the pure function — it's a statement about recent history (a window of past runs), not this run's own numbers, so folding it in would break purity. This is the SRE mechanic: an exhausted budget freezes deployment regardless of how well the current run scored.
Could they ask me to code this? **POSSIBLY** — the aggregation + policy-resolution + call into the pure function is YES-level; the ARS-snapshot read and error-budget call depend on `ars_engine` internals you'd need to have studied separately.

**Known duplication to flag if asked "any tech debt you'd fix":** `GatePolicy.min_pass_rate` has `server_default="0.9"` in the model (`models/gate.py`) and `gate_engine.DEFAULT_MIN_PASS_RATE = 0.9` is a separate Python constant — these two `0.9`s are not DRY and could drift out of sync silently.

---

### 3.3 Scorers — `apps/api/services/scorers/`

**`Scorer` Protocol** — `base.py` lines ~34-36 — `score(self, case, transcript) -> ScorerResult`. Structural typing via `Protocol`, not ABC inheritance — know why (no import coupling required, any class with a matching method signature satisfies it; good for the chaos-adapter-style decorator pattern elsewhere too).

**`ContainsMatchScorer.score()`** — `contains_match.py` lines ~15-33
Concatenates ALL assistant turns into one lowercased blob before matching (multi-turn aware), checks all `expectations["contains"]` strings are present and none of `must_not_contain` are. Builds `missing`/`present` lists via comprehensions (not early-exit) so `detail` reports exactly what failed.
Could they ask me to code this? **YES** — small, deterministic, good warm-up question.

**`LLMJudgeScorer`** — `llm_judge.py`
- `__init__` (~41-51): resolves `get_profile("high_reasoning")` — deliberately a **stronger** profile than the agent's own `"standard"` profile (Rule 6: never hardcode model names). Gets a rate limiter scoped to `"high_reasoning"`.
- `score()` (~53-79): if `expectations["judge_rubric"]` is set, sends transcript + rubric to Gemini with `response_schema=JudgeVerdict` (a deliberately **flat** schema — `passed: bool`, `reasoning: str` — because nested Pydantic models hit an unresolved `$ref`/`$defs` bug in the `google-genai` SDK's structured-output support; know this as a real "worked around a library bug" story). `self._limiter.acquire()` is called **before** the LLM call (blocking rate-limit acquire, per security Rule 5). `temperature=0.0` for determinism, `thinking_config=ThinkingConfig(thinking_budget=0)`.
Could they ask me to code this? **POSSIBLY** — the flow (rate-limit acquire → structured-output call → parse verdict) is understandable, but exact `genai` SDK call shape requires familiarity you should mention rather than fake.

**`SafetyScorer`** — `safety.py`
- `_check_groundedness(transcript)` (~89-118): for every assistant turn that called a retrieval-shaped tool (name matched against `_RETRIEVAL_TOOL_NAME_MARKERS`) and got an **empty** result back, the assistant's answer must contain an honesty signal phrase or it's flagged as ungrounded/hallucinated. Deliberately scoped only to retrieval-shaped tools — an empty result from, say, an inventory-count tool is legitimate data, not missing context, so it's not checked.
- `score()` (~121-149): runs groundedness first (free, deterministic); only escalates to `LLMJudgeScorer` (via a duck-typed `_SafetyRubricCase` adapter exposing just `.expectations`) if groundedness passed AND a `safety_rubric` is configured.
- **The single best "why we didn't build X" quote in the repo** (lines ~35-40): prompt-injection compliance is deliberately not attempted as a generic keyword heuristic, because it would either miss real injections or false-flag legitimate content — "giving false confidence in either direction." Real injection resilience is instead measured by `ChaosAdapter` + `RecoveryScorer` (controlled fault injection + graded recovery), which the docstring calls "the honest way to measure this, not a guess from transcript text." **Memorize this reasoning — it's your best answer to "what did you choose not to build and why."**
Could they ask me to code this? **POSSIBLY** for `_check_groundedness`'s deterministic core; the rubric-escalation wrapper pattern is easy to reproduce once you've seen it once.

**`RecoveryScorer.score()`** — `recovery.py` lines ~28-75
Finds the LAST turn carrying a chaos marker (`has_chaos_marker()`, imported from `chaos_adapter.py`), requires every assistant turn strictly **after** that one to be non-empty — a deliberately minimal, "honestly-defensible" bar, not a keyword-based recovery-quality heuristic. Optionally escalates to `LLMJudgeScorer` via the same duck-typed adapter-case pattern as `SafetyScorer`.
Could they ask me to code this? **POSSIBLY** for the deterministic core (lines ~28-49).

**`CostScorer`/`LatencyScorer`** — trivial, `None`-config-means-auto-pass pattern, structurally identical to each other. **YES**, rewrite either from memory in under a minute as a sanity check.

---

### 3.4 Adapters — `apps/api/services/adapters/`

**`AgentAdapter` Protocol + `AgentTurnResult`** — `base.py` lines ~17-41
`AgentTurnResult{assistant_message, tool_calls, latency_ms, cost_usd}` is the shape every adapter must return. The docstring is the canonical statement of the session_state-by-reference contract: `session_state` is opaque to the caller and passed back unchanged each turn; the agent function may mutate it in place. Know this contract cold — it's the seam that makes `LocalPythonAdapter`, `HTTPAdapter`, and `ChaosAdapter` all interchangeable.

**`LocalPythonAdapter._load_entrypoint(entrypoint)`** — `local_python.py` lines ~23-34 — **the exact importlib mechanism**
```python
module_path, function_name = entrypoint.rsplit(":", 1)
module = importlib.import_module(module_path)
fn = getattr(module, function_name, None)
if fn is None or not callable(fn):
    raise ValueError(...)
```
`rsplit(":", 1)` splits on the **last** colon, so a dotted qualname edge case can't confuse it. `run_turn()` then just calls `self._fn(session_state, user_message)` directly — no serialization, no subprocess. `session_state` persists across turns purely because it's the same dict object in the same process's heap.
Could they ask me to code this? **YES.** This 12-line function is a favorite kind of "explain and reproduce" ask because it directly demonstrates you understand *why* Rule 9 (importlib not subprocess) exists — reference semantics for `session_state` would require a wire protocol under subprocess.

**`HTTPAdapter._post_with_retries()`** — `http_adapter.py` lines ~145-185 — the trickiest block in the whole adapter package
Retry semantics are narrow and deliberately asymmetric:
- `ConnectError`/`ConnectTimeout` → retryable ("the agent never saw this turn").
- `ReadTimeout` → **raised immediately, never retried** — "sent but unanswered; the agent may have already processed it; retrying risks a duplicate side effect (a refund, a ticket, an email)."
- HTTP 502/503/504 → retryable.
- Any other 4xx/5xx → raised immediately.
- Backoff: `0.5 * (2 ** attempt)` for `max_retries=2` → 0.5s, 1.0s.
Could they ask me to code this? **YES**, specifically the retry-decision branch (which exceptions/statuses retry vs. which don't) — this is a genuinely good distributed-systems question and the reasoning (idempotency risk on `ReadTimeout`) is the actual answer they're listening for.

**`HTTPAdapter._apply_session_state()`** — `http_adapter.py` lines ~212-222
`session_state.clear(); session_state.update(new_state)` — **in-place mutation, not rebinding** — because the eval engine holds a reference to the same dict across every turn of a case; replacing the object (`session_state = new_state`) would silently drop the caller's reference to the updated data. A sharp "why `.clear()`/`.update()` instead of reassignment" question with a precise answer.
Could they ask me to code this? **YES** — two lines, but the reasoning is the actual test.

**`build_adapter(entrypoint, **kwargs)`** — `adapters/__init__.py` lines ~38-68
URL-scheme-based selection: `entrypoint.startswith(("http://", "https://"))` → `HTTPAdapter`; else must contain `":"` → `LocalPythonAdapter`; HTTP-only kwargs passed to a local entrypoint raise `ValueError` (programming error, caught early). Selection is by the *shape* of the stored `entrypoint` string, not a separate DB column — no schema migration was needed to add HTTP-agent support.
Could they ask me to code this? **YES** — simple dispatch, good for demonstrating you understand why shape-based dispatch avoided a migration.

**`ChaosAdapter`** — `chaos_adapter.py` lines ~88-183
Wraps any `AgentAdapter`, satisfies the same Protocol. Two fault families: "total failure" (`TIMEOUT`, `CONNECTION_RESET` — real adapter never called, `session_state` untouched) vs. "corrupted response" (`MALFORMED_RESPONSE`, `PLAUSIBLE_WRONG`, `LATENCY_INJECTION` — real adapter IS called, output altered after). `_should_fault()` (~128-131) is either deterministic (`target_turn_indices`) or probabilistic (`rng.random() < probability`). Every faulted turn carries a reserved marker tool call `CHAOS_MARKER_TOOL_NAME = "__chaos_fault__"` so `RecoveryScorer` can detect it without widening the `AgentTurnResult`/`ToolCall` contract.
Could they ask me to code this? **POSSIBLY** — the fault dispatch is mostly a switch statement; the interesting part (adapter-as-transparent-wrapper, marker-based detection instead of contract-widening) is better explained verbally than typed live.

---

### 3.5 STABLE CONTRACT — `apps/api/core/jobqueue.py` + `redpanda_queue.py`

**`JobQueue` Protocol** — `jobqueue.py` lines ~46-53
```python
class JobQueue(Protocol):
    def publish(self, tenant_id: UUID, job_type: str, payload: dict) -> UUID: ...
    def get_status(self, job_id: UUID) -> JobStatus: ...
```
This exact two-method signature is what "STABLE CONTRACT" means — architecture Rule 2 forbids ever changing it. Both implementations below satisfy it identically from the caller's point of view.

**`PostgresJobQueue.publish()`** — `jobqueue.py` lines ~69-74 — INSERT a `Job` row, commit, refresh, return `job.id`. One DB round trip.

**`PostgresJobQueue.claim_next_job()`** — `jobqueue.py` lines ~82-103 — **not** part of the STABLE CONTRACT (worker-internal), but the single best SQL-and-concurrency artifact in the repo:
```python
stmt = (
    select(Job).where(Job.status == "pending")
    .order_by(Job.created_at).limit(1)
    .with_for_update(skip_locked=True)
)
```
`SKIP LOCKED` means two worker processes can never claim the same pending job — a row already locked by another transaction is simply skipped, not waited on. The row lock is held only for select+update+commit, never across actual eval execution. Comment: required "even with a single worker process — it costs nothing now and prevents a real bug the moment a second worker is started."
Could they ask me to code this? **YES.** This exact query (or its conceptual equivalent) is a legitimate "write a job queue claim function" interview ask.

**`RedpandaJobQueue.publish()`** — `redpanda_queue.py` lines ~109-154 — same signature, different transport: INSERT a `Job` row for audit/recovery (112-120), serialize a JSON envelope (125-133), resolve topic via `_resolve_topic(job_type)` (135), produce **partitioned by `key=tenant_id`** (139 — "so one tenant's burst never delays another's job"), bounded `flush(timeout=10)` (147-149, raises `RuntimeError` on timeout — "a bare flush() blocks forever when the broker is unreachable... failing loudly after 10s is the difference between a debuggable error and a hung request"), warms the Redis `JobStatusCache` (152).
**Real historical bug worth quoting:** a comment at lines ~42-51 explains `publish()` previously ignored `job_type` entirely and always produced to one hardcoded topic — the STABLE CONTRACT's signature never *promised* correct topic routing, that was a separate implementation gap. Good "what did the contract not protect you from" answer.

**`RedpandaJobQueue.get_status()`** — `redpanda_queue.py` lines ~156-165 — cache-first: Redis lookup, fallback to `db.get(Job, job_id)` on miss. Contrast with `PostgresJobQueue.get_status()` (lines ~76-80), which always reads Postgres directly — no cache layer needed since Postgres *is* the source of truth there.
Could they ask me to code this? **YES** for `publish()`'s core shape (INSERT + produce + bounded flush); **POSSIBLY** for the exact cache-then-fallback `get_status()` — conceptually simple, but you'd need to know the `JobStatusCache` API.

---

### 3.6 Workers — `apps/api/workers/eval_worker.py` + `eval_worker_v2.py`

**`eval_worker.py: run_worker_loop()`** — lines ~23-45
`db = SessionLocal()` created fresh **inside** the loop body, `try/finally: db.close()` on every iteration — avoids stale/expired ORM objects across a potentially long-running eval. `claim_next_job()` returning `None` → `time.sleep(2)`, no jitter, no backoff. Bare `except Exception` around the run converts to `mark_failed` with the full traceback — **no retry, one shot**, no dead-letter concept in this version.
Could they ask me to code this? **YES** — the loop skeleton (claim → run → mark complete/failed → sleep-if-idle) is a fair live-coding ask.

**`eval_worker_v2.py: run_worker_loop()`** — lines ~27-77
- Lines ~46-51: `DistributedLock.acquire(job_id)` guards against re-delivery — "if a previous worker crashed and this message was re-delivered, the lock prevents us from running the same eval twice." If the lock can't be acquired, it skips **and still commits the offset** — a redelivered message that lost the lock race must still advance past it or the consumer loops forever on it.
- Lines ~60-70: on exception, calls `retry_or_dead_letter()` (republishes with incremented `retry_count` up to `max_job_retries=3`, else routes to `<topic>.dead-letter`), then **always** commits the offset on the original message regardless of outcome — the retry is a brand-new message appended to the topic tail, not a redelivery of the original, so the original's offset must advance either way.
- Lines ~34-36: `consume_one(timeout_seconds=2.0)` returning `None` just loops immediately — event-driven long-poll, not a fixed sleep.
Could they ask me to code this? **NO** for the full function (too many Kafka-specific details); **YES** for explaining, precisely, why the offset commit happens *after* processing and why the lock-miss path still commits.

**Polling vs. event-driven — the contrast table to have memorized:**

| | `eval_worker.py` | `eval_worker_v2.py` |
|---|---|---|
| Claim mechanism | `SELECT ... FOR UPDATE SKIP LOCKED` | Kafka consumer-group partition assignment |
| Idle behavior | `time.sleep(2)` fixed interval | `poll(timeout=2.0)` blocking long-poll |
| Completion ack | Postgres `status="in_progress"` committed inline within the claim | Kafka offset commit deferred until **after** processing |
| Delivery guarantee | Exactly-once (single-row semantics) | At-least-once by design; dedup via `DistributedLock` |
| Retry on failure | None — straight to `mark_failed` | `retry_or_dead_letter()`, up to 3 attempts, then dead-letter topic |
| Scaling | Manual | KEDA watches consumer lag (architecture Rule 10) |

---

### 3.7 Auth — `apps/api/core/security.py` + `apps/api/core/auth.py`

**`require_api_key()`** — `security.py` lines ~52-93 — the single entry point for every authenticated route.
- Lines ~63-66: dispatch heuristic — `raw.startswith("rl_live_")` decides JWT-vs-API-key path (API keys have a fixed prefix; JWTs contain dots and don't).
- Lines ~72-77: after a **cryptographically valid** JWT decode, it still re-verifies the tenant and user exist in Postgres — "token replay after deletion": a JWT can be valid for up to 15 minutes after the user backing it was deleted; this closes that window.
- Lines ~82-87: API-key path distinguishes "key never existed" from "key was revoked" (`revoked_at is not None`) even though both return 401 — logically distinct failure modes, useful for audit logging even if the HTTP response doesn't differentiate.
Could they ask me to code this? **YES**, specifically the dispatch-by-prefix branch and the replay-after-deletion re-check — these are the two things that make this more than a boilerplate auth dependency.

**`get_tenant_context()`** — `security.py` lines ~120-133
404 (not 500) on a missing tenant — "the credential is structurally valid but its tenant has been deleted, which from the caller's perspective is 'your tenant is not there,' not 'the server is broken.'" This dependency exists because of a documented prior bug: `db.query(Tenant).first()` was silently correct only while exactly one tenant existed, and became a cross-tenant data leak the moment a second tenant was created. **Excellent "explain a bug this code prevents" answer.**

**`create_access_token()`** — `auth.py` lines ~46-55 — exact claim set actually in code: `sub`, `tenant_id`, `role`, `exp` (15 min), `type: "access"`. **No `iat` claim is set**, despite the project's own `security.md` documenting `iat` as required — a real doc/code mismatch, good "does your code match your spec" answer if asked to self-critique.

**`decode_access_token()`** — `auth.py` lines ~58-67 — the exact `type` check that prevents a refresh token being used as an access token:
```python
if payload.get("type") != "access":
    raise JWTError("not an access token")
```
Note: in this codebase, refresh tokens are **not JWTs at all** — they're opaque `secrets.token_urlsafe(48)` strings, hashed and stored in Postgres. So this check is defense-in-depth on the JWT-decode path itself, not something a real refresh token would ever reach in normal flow. Good trap question: "would a refresh token ever fail this specific check in production?" (Answer: no — it would fail JWT decoding entirely, long before reaching this line.)

**`rotate_refresh_token(db, raw_token)`** — `auth.py` lines ~96-125 — **the highest-value function in the whole auth surface.** Step by step:
1. **Hash lookup** (~102-105): `token_hash = SHA256(raw_token)`, query `RefreshToken` by hash.
2. **Not found** (~107-108): `ValueError("refresh token not found")` → surfaces as 401.
3. **Reuse detection** (~109-114): `if record.revoked_at is not None:` → this token was already used once before → call `_revoke_all_for_user(db, record.user_id)` → raise. Comment: "a legitimate client rotates exactly once. If reuse is detected, revoke all tokens for this user (session hijacking response)." **This is the OWASP refresh-token-rotation-with-reuse-detection pattern, implemented for real.**
4. **Expiry check** (~115-116).
5. **Revoke the presented token** (~118-120): `revoked_at = now()`, commit.
6. **Reissue** (~122-125): new access + refresh token pair.
Could they ask me to code this? **YES.** Practice writing steps 1-6 from memory, in order, without looking. The reuse-detection branch (step 3) is the part they're actually listening for.

**`_revoke_all_for_user()`** — `auth.py` lines ~139-145 — a single bulk SQLAlchemy `.update({...})` statement, not N per-row ORM mutations — one SQL statement, not a loop. Know why this matters (a full-account session wipe should be one atomic statement, not N round trips that could partially fail).

---

### 3.8 Rate Limiting — `apps/api/core/redis_client.py`

**`RateLimiter.is_allowed()`** — lines ~45-58 — sliding window over a Redis sorted set, four pipelined ops in order: `ZREMRANGEBYSCORE` (prune stale) → `ZCARD` (count) → `ZADD` (record this request) → `EXPIRE` (safety-net TTL). Return: `current_count < self._max`, where `current_count` is the cardinality **before** this request's own `ZADD` — so the limiter is conceptually "would allowing this request put me over," but note the `ZADD` executes unconditionally as part of the same pipeline batch regardless of what the boolean ends up being, meaning a rejected request still consumes a slot in the sorted set. Understand this subtlety — it's a legitimate "is there a bug here" discussion point, not necessarily a bug (the TTL bounds the set size either way), but worth being able to reason about out loud.
Could they ask me to code this? **YES** for the four-operation sequence and the sliding-window concept; be ready to discuss the always-ZADD nuance if pressed.

---

### 3.9 Novelty Feature Engines

**`ars_engine._compute_ars()`** — `apps/api/services/ars_engine.py` lines ~56-101 — pure.
```python
WEIGHT_CORRECTNESS, WEIGHT_SAFETY, WEIGHT_LATENCY, WEIGHT_COST = 0.4, 0.2, 0.2, 0.2
ars = WEIGHT_CORRECTNESS*correctness + WEIGHT_SAFETY*safety + WEIGHT_LATENCY*latency + WEIGHT_COST*cost
```
Each sub-score is `passed/total` for the scorer(s) gating that dimension (correctness = `ContainsMatchScorer AND LLMJudgeScorer` both passed). Comment: weights are "not configurable per-agent (yet) — a single fixed formula is what makes ARS comparable across agents at all." Know this weighting is a starting default, not empirically calibrated — say so if asked.
Could they ask me to code this? **YES** — a 4-term weighted sum, trivially reproducible, and the "why fixed weights" reasoning is the real test.

**`ars_engine.compute_error_budget()`** — lines ~116-155 — pure.
```python
breach_rate = breaches / window_size   # breach = ars < target_ars (default 0.9)
exhausted = breach_rate > error_budget_pct   # default 0.1 (10%)
```
This is what feeds `gate_engine.evaluate()`'s freeze logic. Could they ask me to code this? **YES.**

**`diff_engine._classify_diff()`** — `apps/api/services/diff_engine.py` lines ~90-132 — pure. 2×2 classification:
```python
mean_similarity = mean(per_case_similarity.values())
behavior_changed = mean_similarity < 0.90   # DEFAULT_SIMILARITY_THRESHOLD
# code_changed & !behavior_changed -> SAFE_REFACTOR
# code_changed & behavior_changed  -> EXPECTED_CHANGE
# !code_changed & behavior_changed -> SILENT_DRIFT   <- the headline scenario
# !code_changed & !behavior_changed -> NO_OP
```
Cosine similarity re-implemented locally (`np.dot(a,b)/(norm(a)*norm(b))`) rather than shared with agent code — deliberate: platform code and agent-under-test code must not share a library a test change could accidentally couple. `compute_diff()` (~168-259) takes two **eval_run** IDs, not version IDs — this is the clever part: comparing the same version's `content_hash` to itself across two time points is the only way `code_changed=False` is representable, which is required to ever reach `SILENT_DRIFT`. Be ready to explain this parameterization choice — it's a genuinely good "why did you design it this way" story.
Could they ask me to code this? **YES** — the classification function plus cosine similarity is ~20 lines, self-contained, and quotable.

**`mining/engine.py: _cluster_embeddings()` + `_identify_significant_clusters()`** — lines ~120-144 and ~147-202 — pure, the one real unsupervised-ML component.
```python
similarity = normalized @ normalized.T
distance = np.clip(1.0 - similarity, 0.0, 2.0)
labels = DBSCAN(eps=0.15, min_samples=3, metric="precomputed").fit_predict(distance)
```
Significance filter: cluster must have `size >= min_cluster_size (3)` AND `bad_count/size >= min_bad_outcome_rate (0.5)`. Comment explains DBSCAN over hand-rolled clustering was chosen deliberately — "hand-rolling a clustering algorithm would undercut the claim" that this is "the actual machine-learning component of the platform." **Honest caveat you must disclose if asked:** "production traces" per the README is actually just recorded `EvalCaseResult` history — RedLine has no separate live-traffic ingestion pipeline yet. The algorithm is real; the data source framing in the README oversells it slightly. Say this proactively if asked "is this really mining production data" — it shows self-awareness, not weakness.
Could they ask me to code this? **YES**, with the caveat that using `sklearn.cluster.DBSCAN` directly (as the real code does) is expected — don't try to hand-roll DBSCAN itself live.

**`load_engine._percentile()` + `_compute_load_stats()`** — `apps/api/services/load_engine.py` lines ~72-79 and ~82-129 — pure.
```python
def _percentile(sorted_values, pct):
    index = max(0, min(len(sorted_values)-1, int(round(pct/100*len(sorted_values)))-1))
    return sorted_values[index]
```
Nearest-rank, no interpolation. Plus: `error_rate = 1 - successful/total`, `cost_per_hour = total_cost / (duration_seconds/3600)`, `throughput = total / duration_seconds`.
**`_virtual_user()`** (~132-155) — concurrency mechanism: one `ThreadPoolExecutor` thread per virtual user, each owning its own `session_state` dict, looping `adapter.run_turn()` until `time.monotonic() >= stop_at`. Deliberately real-thread-based, not asyncio — "provides real concurrency without asyncio anywhere," directly defending architecture Rule 1 (eval engine stays synchronous) while still delivering genuine parallel load. Bonus point: this is explicitly called out as the payoff of making `LLMRateLimiter` multi-worker-safe — concurrent threads calling an agent that calls `get_limiter()` share ONE real budget instead of each thread getting an illusory allowance.
Could they ask me to code this? **YES** for `_percentile`/`_compute_load_stats` (clean, self-contained); **YES** for explaining (and roughly sketching) the `ThreadPoolExecutor`-per-virtual-user pattern, even if you don't reproduce every line.

---

### 3.10 Routers — `apps/api/routers/`

**`ci.py: create_ci_check()`** — full file, endpoint ~23-48 — **the endpoint embodying the whole product thesis.**
`POST /ci/check` creates an `EvalRun` (`triggered_by="ci"`, `git_pr_number` set), publishes `"eval.requested"`, returns `{eval_run_id, status, poll_url}` **immediately** — it does **NOT** compute or return a pass/fail verdict. The actual gate decision comes from the CLI polling `GET /eval-runs/{id}` (`eval_runs.py`) until `status == "completed"`, then reading `gate_result.passed` (computed by `gate_engine.evaluate()`). The API server is deliberately GitHub-agnostic — it never knows GitHub exists; the CLI's `ci-check` command talks to GitHub's Check Run API directly using the CI job's own token (a real platform constraint: GitHub only allows the CI job's own token to create/update a Check Run since Feb 2025).
Could they ask me to code this? **NO** for the full CLI-to-GitHub integration, but **YES** for explaining precisely why the API doesn't return pass/fail synchronously — this is a design-reasoning question, not a coding one.

**`eval_runs.py: get_eval_run()`** — lines ~57-88 — has a genuine bug worth knowing: it constructs a `JobStatusCache` and calls `cache.set(...)` (line ~72, comment says "cache completed runs -- gate_result is immutable once done") but **never reads from the cache in this function** — `gate_engine.evaluate()` is recomputed on every call regardless. Good self-critique material: "I have a cache-set with no corresponding cache-read here — that's dead code, here's how I'd fix it."

**`eval_suites.py: push_suite()`** — lines ~34-92 — YAML → DB upsert. `db.flush()` (not `commit`) after creating/finding the `EvalSuite` (line ~60) to get its PK before inserting cases **in the same transaction**; single `db.commit()` at the very end makes the whole suite push all-or-nothing. Know the `flush` vs `commit` distinction cold: `flush()` sends pending SQL to get generated PKs/constraints without ending the transaction; `commit()` ends it.

**`dashboard.py: _owned_agent()`** — lines ~56-65 — the tenant-ownership idiom repeated (independently, not shared — a minor DRY gap) across the codebase: 404, never 403, on a resource belonging to another tenant — "a 403 would confirm the resource exists, which leaks the existence of another tenant's agents to anyone probing UUIDs." Memorize this quote; it's your best answer to "how do you prevent tenant enumeration."

**`dashboard.py: agent_detail()`** — lines ~123-169 — has a real perf issue: calls `gate_engine.evaluate()` (which opens its **own** `SessionLocal()`) inside a loop over a request handler that already has an open session — nested sessions per iteration. Good "how would you fix this N+1-shaped problem" discussion (batch the aggregation query, or pass the existing session through instead of letting `evaluate()` open a new one).

---

### 3.11 CLI — `apps/cli/`

**`api_client.py: RedLineClient`** — lines ~1-32 — wraps `httpx.get`/`post` with a Bearer API-key header, raises `APIError` on `status_code >= 400`. Docstring: "All CLI commands use this — never calling the DB or any other service directly." **Verified**: grepping `apps/cli/` for `apps.api` imports or any SQLAlchemy/db/psycopg usage returns zero matches — architecture Rule 7 is genuinely honored in the current code, not just documented.

**`register_version.py: _compute_content_hash()`** — lines ~30-46 — branches by entrypoint type. HTTP entrypoint: hashes the **URL string itself** (`sha256(entrypoint.strip().encode())`) since RedLine can't see remote source — "the honest fallback." Local Python entrypoint: imports the module, hashes the **raw file bytes** (`sha256(open(module.__file__, "rb").read()).hexdigest()`) — matches coding-standards Rule 10 exactly (raw bytes, not `content.encode()`, no timestamps in the hash input).
Could they ask me to code this? **YES** for the local-file-bytes-hashing branch; **POSSIBLY** for the HTTP-fallback branch (simple, but the "why" needs to be stated, not just the code).

**`commands/run.py: run_cmd()`** — lines ~23-86 — `POST /eval-runs`, then polls `GET /eval-runs/{id}` every 3s until `status in ("completed", "failed")`. Note: no timeout/max-iterations on this poll loop — it could hang forever if a run never terminates. Cross-reference to worker crash scenarios in v3's debugging questions.

---

### 3.12 Benchmark Agents — `agents/`

**`rag_agent/agent.py: _retrieve()`** — lines ~123-133 — embedding cosine similarity (Gemini `embed_content`), `TOP_K = 3`, then filters to `RELEVANCE_THRESHOLD = 0.60` — comment: "calibrated 2026-06: noise floor ~0.55-0.56, real relevance ~0.67+" (empirically tuned, not arbitrary).

**`rag_agent/agent.py: run_turn()`** — lines ~136-199 — **the deterministic refusal is the whole point of this agent.** If `relevant_chunks` is empty after threshold filtering, returns a hardcoded "I don't know" message with **zero LLM cost** (`input_tokens = output_tokens = 0`) — no LLM call happens at all. Comment: "the specific RAG failure mode this benchmark agent exists to catch: admit missing context instead of confidently hallucinating an answer." This is a hard code branch, not a prompt instruction — a second, weaker line of defense (the prompt itself also says "say I don't know if context is insufficient") exists for the case where chunks *were* found but are still inadequate.
Could they ask me to code this? **YES** for the retrieve-then-threshold-then-branch structure — this is the cleanest "explain your RAG design" artifact in the repo.

**`stateful_support_agent/agent.py`** — `session_state` structure (~141-146, 204-209): `session_state["memory"]` (flat dict of extracted entities via `dict.setdefault()`) + `session_state["history"]` (list of turn dicts), both mutated **in place**. `_extract_memory()` (~109-138) is a *second*, separate LLM call per turn using `response_mime_type="application/json"`; on parse failure it silently falls back to `{}` with no logging — a real "what would you improve" answer (silent failure hides extraction bugs at eval time). `memory.update(new_memory)` (line ~207) means later corrections silently overwrite earlier values with no history — this is simultaneously the *feature* (the "correction memory" failure category this agent exists to probe) and a potential source of confusing eval failures — know both framings.

**`research_pipeline_agent/agent.py`** — pipeline: `_planner → _researcher (×2) → _verifier → _synthesizer`. Two real, quotable bugs:
1. `_verifier()` (~165-184): on JSON parse failure, **defaults to `(text, is_sufficient=True)`** — a verifier malfunction silently passes verification instead of failing safe. This is the literal "one agent's small error compounds across the chain" failure mode the README describes — the bug and the feature-under-test are the same code path.
2. `run_turn()` (~203-233): declares `total_input_tokens`/`total_output_tokens` locals that are **never incremented anywhere** (dead variables), and reports cost as a **flat estimate** (`5 calls × ~500 input + ~200 output tokens`) rather than summing the real `input_tokens`/`output_tokens` that `_llm()` actually returns per call. This directly undermines the "is total cost bounded" eval goal the agent's own docstring states. **This is your best single "find a real bug in this codebase" answer — it's concrete, self-contained, and you can point at the exact dead variables.**

---

## 4. Critical Logic Blocks — Quick Index

These are sub-blocks *inside* the functions above that interviewers tend to point at directly ("walk me through just this part") rather than ask you to explain the whole function. Cross-referenced to §3 — this is a fast-lookup table, not a re-explanation.

| Block | File : approx. lines | Why it matters | Rewrite it? |
|---|---|---|---|
| `SELECT ... FOR UPDATE SKIP LOCKED` claim query | `jobqueue.py : 82-103` | Prevents two workers claiming the same job; lock held only briefly, not across eval execution | YES |
| Refresh-token reuse detection branch | `auth.py : 109-114` | OWASP session-hijack response pattern — revoke-all on reuse | YES |
| JWT `type` claim check | `auth.py : 65-66` | Prevents refresh-token-as-access-token misuse (though refresh tokens here are opaque strings, not JWTs — know the nuance) | YES |
| Zero-total guard | `gate_engine.py : 62-63` | Missing results must never silently pass the gate | YES |
| Error-budget freeze | `gate_engine.py : 140-151` | Deliberately outside the pure function — a statement about history, not this run | POSSIBLY |
| Scorer loop, no short-circuit | `eval_engine.py : 98-105` | Full diagnostics over early-exit cost savings — a real tradeoff | YES |
| `emit_trace()` calls with real tenant_id + real exception | `eval_engine.py : 232-249` | Two documented, fixed prior bugs (random tenant_id, bare `Exception()`) | Explain, don't rewrite |
| Retry-decision branch (`ConnectTimeout` vs `ReadTimeout` vs status codes) | `http_adapter.py : 145-185` | Idempotency-risk-aware retry — the core distributed-systems lesson in this repo | YES |
| In-place `session_state` mutation | `http_adapter.py : 212-222` | `.clear()`/`.update()`, not reassignment — preserves the caller's dict reference | YES |
| `importlib` entrypoint resolution | `local_python.py : 23-34` | `rsplit(":", 1)` + `getattr` — the mechanism behind Rule 9 | YES |
| DBSCAN precomputed-distance clustering | `mining/engine.py : 120-144` | The one real unsupervised-ML artifact in the repo | YES (call `sklearn.DBSCAN`, don't hand-roll) |
| 2×2 diff classification | `diff_engine.py : 107-121` | Code-changed × behavior-changed quadrant logic | YES |
| Nearest-rank percentile | `load_engine.py : 72-79` | No interpolation — an approximation, not true percentile interpolation | YES |
| `_owned_agent()` 404-not-403 | `dashboard.py : 56-65` | Tenant-enumeration prevention | YES |
| `ci.py` fire-and-forget, no sync verdict | `ci.py : 23-48` | The entire product thesis hinges on this NOT being synchronous | Explain, don't rewrite |
| Dead `total_input_tokens`/`total_output_tokens` | `research_pipeline_agent/agent.py : 203-233` | Real bug — cost is estimated, not measured, contradicting the agent's own stated eval goal | Fix it as a demo |
| Verifier fails open on parse error | `research_pipeline_agent/agent.py : 183-184` | `(text, is_sufficient=True)` on JSON parse failure — silently passes instead of failing safe | Fix it as a demo |
