# RedLine — Interview Code Guide (v3: Practice & Defense)

Part 3 of 3. See [INTERVIEW_CODE_GUIDE.md](INTERVIEW_CODE_GUIDE.md) for the map, [INTERVIEW_CODE_GUIDE_v2.md](INTERVIEW_CODE_GUIDE_v2.md) for the function-level deep dive. This file is for the week before, and the night before.

---

## 7. Design Decisions (Brief)

**Pure/impure split (gate_engine, ars_engine, diff_engine, load_engine, mining/engine)**
Why: unit tests for the decision logic run with plain data, no DB/Redis/network — `gate_engine.py` alone has 12 such tests. Alternative: one function that both queries and decides. Tradeoff: the split means two functions to maintain per feature instead of one, and the impure wrapper has to correctly marshal DB rows into primitives before calling the pure core — but every core algorithm becomes trivially testable and independently reasoned-about. This is the single most repeated architectural decision in the codebase — five separate features follow it.

**STABLE CONTRACT job queue (`JobQueue` Protocol, Postgres and Redpanda implementations)**
Why: lets the transport change (Postgres polling → Kafka event bus) without touching any router or the eval engine. Alternative: call Postgres or Kafka directly from callers and branch on an environment flag. Tradeoff: the Protocol buys transport-swappability but doesn't guarantee behavioral parity — a real bug (`job_type` silently ignored) shipped inside the contract's boundaries because the *signature* was honored while the *implementation* wasn't complete. A contract constrains the interface, not the correctness behind it.

**`LocalPythonAdapter` uses `importlib`, never `subprocess`**
Why: `session_state` needs to persist across turns by reference, in-process, with zero serialization overhead. Alternative: `subprocess.run()` per turn, passing state as JSON over stdin/stdout. Tradeoff: in-process execution means a crashing agent can take down the worker process; subprocess isolation would be safer but requires defining and versioning a wire protocol for arbitrary Python objects (conversation history, graph state) that don't serialize cleanly.

**Refresh tokens are opaque strings, not JWTs**
Why: opaque tokens can be revoked server-side by deleting/marking a DB row; a JWT refresh token would remain "valid" (per its own signature) until natural expiry even after "revocation" unless you maintain a denylist anyway — which defeats the point of using a stateless token in the first place. Alternative: make refresh tokens JWTs too, for symmetry with access tokens. Tradeoff: symmetry vs. genuine revocability — the codebase chose revocability, correctly, for the higher-stakes token.

**`ThreadPoolExecutor` for load testing, not asyncio**
Why: architecture Rule 1 forbids `asyncio` anywhere near the eval engine (mixing it with synchronous SQLAlchemy Sessions and synchronous Kafka calls is a documented concurrency trap). Load testing genuinely needs concurrency to simulate concurrent users. Alternative: a separate asyncio-based load-test service. Tradeoff: real OS threads have more overhead per concurrent unit than an event loop, but they deliver genuine parallelism without introducing a second concurrency model into a codebase that's deliberately, consistently synchronous everywhere else.

**DBSCAN for failure mining, not k-means**
Why: k-means requires you to pre-specify the number of clusters, which makes no sense for an unknown number of failure modes; DBSCAN discovers cluster count automatically and — critically — has a built-in noise label (-1) so outlier failures don't get force-fit into a nearest cluster. Alternative: k-means with a heuristic like the elbow method to pick k. Tradeoff: DBSCAN needs `eps`/`min_samples` tuned instead, and this codebase's own comments admit those are untuned starting defaults, not empirically calibrated — a real, disclosed limitation.

**Two-phase scorer pattern (deterministic check, then optional LLM-judge escalation) — `SafetyScorer`, `RecoveryScorer`**
Why: deterministic checks are free and fast; LLM calls cost money and have latency. Running the cheap check first and only escalating on ambiguous cases (or when the cheap check already failed) minimizes LLM spend. Alternative: always call the LLM judge for a holistic score. Tradeoff: the deterministic check can only catch what it's specifically coded to catch (empty-retrieval-without-honesty-signal, non-empty-post-fault turns) — it can't catch semantically wrong-but-well-formed answers the way an LLM judge could. Layering the two is a legitimate way to get most of the coverage at a fraction of the cost.

**CI check endpoint returns immediately, never a synchronous pass/fail (`ci.py`)**
Why: an eval run can take much longer than an HTTP request timeout budget allows, and GitHub Check Runs are meant to be updated asynchronously anyway (poll and update, not block-and-respond). Alternative: make the CI endpoint synchronous and just accept a long-held HTTP connection. Tradeoff: the async design pushes complexity onto the caller (the CLI has to poll, per architecture, and now owns the GitHub Check Run token/API relationship the server deliberately avoids) but keeps the server simple, GitHub-agnostic, and free of the timeout-tuning problem synchronous CI gating would create.

---

## 8. Rewrite Practice

Practice these from memory, with no code open, then diff against the source. Ordered roughly by how likely each is to actually come up.

| What to write | Difficulty | Approx. LOC | Interview probability |
|---|---|---|---|
| `_compute_gate_result()` (threshold comparison, `gate_engine.py`) | Easy | 25 | **Very high** |
| `_run_case()`'s turn-building + scorer loop (`eval_engine.py`) | Medium | 20 | **Very high** |
| `rotate_refresh_token()`'s 6-step flow (`auth.py`) | Medium | 25 | **High** |
| `LocalPythonAdapter._load_entrypoint()` (importlib mechanism) | Easy | 12 | **High** |
| `HTTPAdapter._post_with_retries()`'s retry-decision branch | Medium-Hard | 30 | **High** |
| `SELECT ... FOR UPDATE SKIP LOCKED` job-claim query | Medium | 15 | High |
| `_compute_ars()` (weighted sum) | Easy | 10 | High |
| `_classify_diff()` (2×2 quadrant + cosine similarity) | Medium | 20 | Medium-High |
| `_percentile()` + `_compute_load_stats()` | Easy-Medium | 25 | Medium-High |
| `require_api_key()`'s dual-dispatch branch (`security.py`) | Medium | 25 | Medium |
| `RateLimiter.is_allowed()` (sliding window, 4-op Redis pipeline) | Medium | 15 | Medium |
| `_check_groundedness()` (`safety.py`) | Medium | 20 | Medium |
| `_owned_agent()` tenant-ownership guard | Easy | 10 | Medium |
| `_cluster_embeddings()` + significance filter (`mining/engine.py`) | Medium (assumes `sklearn`) | 25 | Medium |
| `build_adapter()`'s URL-scheme dispatch | Easy | 15 | Low-Medium |
| RAG agent's `_retrieve()` + threshold-refusal branch | Medium | 25 | Medium |
| `_compute_content_hash()`'s two branches (`register_version.py`) | Easy-Medium | 15 | Low |

Do the top 6 cold, out loud, narrating design decisions as you write — that's the actual interview simulation, not just producing correct code silently.

---

## 9. Resume Defense

Every question below references real code in this repository. Use v2 to answer them if you get stuck — then close v2 and try again.

### 30 Project-Specific Explanation Questions

1. Walk me through what happens, end to end, from a CI pipeline calling `agentbench ci-check` to a pull request being blocked. Name every file involved.
2. Why does `POST /ci/check` (`ci.py`) not return pass/fail directly? What would break if it tried to?
3. What is the STABLE CONTRACT, and what two methods does it freeze the signature of? Where are both implementations?
4. Walk me through `_compute_gate_result()`'s zero-total guard. What happens if a suite has zero cases and why?
5. What's the difference between `gate_engine.py`'s pure function and its wrapper? Why can't the error-budget check live in the pure function?
6. Explain the refresh-token rotation flow in `auth.py`, specifically what happens when the same refresh token is presented twice.
7. Why are refresh tokens opaque strings while access tokens are JWTs? What would break if both were JWTs?
8. What does `LocalPythonAdapter` do with `importlib` that a `subprocess`-based approach couldn't do as cheaply?
9. Walk through `HTTPAdapter`'s retry logic. Why is a `ReadTimeout` never retried while a `ConnectTimeout` is?
10. What is `session_state` and how does it survive across turns differently in `LocalPythonAdapter` vs `HTTPAdapter`?
11. Contrast `eval_worker.py` and `eval_worker_v2.py`. What problem does the second one solve that the first can't?
12. What is `SKIP LOCKED` doing in `PostgresJobQueue.claim_next_job()`, and why is it needed even with exactly one worker process?
13. Why does `RedpandaJobQueue.publish()` partition by `tenant_id`?
14. What's the ARS formula, and why are the weights fixed rather than per-agent configurable?
15. Explain the SLO/error-budget mechanism. How does an exhausted budget affect a passing eval run?
16. Walk through the Behavioral Diff Engine's four-quadrant classification. What does `SILENT_DRIFT` actually mean and why is it the headline case?
17. Why does `compute_diff()` take two eval_run IDs instead of two version IDs?
18. What algorithm does Production Failure Mining use, and why that one over k-means?
19. Be honest: does failure mining actually mine live production traffic? What does it actually mine?
20. What five fault modes does `ChaosAdapter` support, and which ones skip calling the real agent entirely?
21. How does `RecoveryScorer` detect which turns were chaos-affected without widening the `AgentTurnResult` contract?
22. Why does `SafetyScorer` explicitly decline to build a generic prompt-injection detector? What does it do instead?
23. Explain how load testing achieves real concurrency without violating the "eval engine is synchronous" rule.
24. Why does the RAG agent sometimes make zero LLM calls for a turn? Walk through that exact branch.
25. What's stored in `stateful_support_agent`'s `session_state["memory"]`, and what happens when a user corrects something they said earlier?
26. Walk through the research pipeline agent's four stages. Where can one agent's error silently propagate to the next?
27. Explain why `apps/cli/` is architecturally forbidden from importing anything from `apps/api/models` or `apps/api/core/db`.
28. How does `register_version.py` compute a content hash differently for an HTTP agent vs. a local Python agent?
29. What does `_owned_agent()` in `dashboard.py` return on a cross-tenant access attempt, and why not the more "correct"-sounding status code?
30. Walk through `RateLimiter.is_allowed()`'s four Redis operations, in order, and explain the sliding window.

### 20 Code-Writing Questions

1. Write `_compute_gate_result()` from scratch given the same parameter list.
2. Write a `SELECT ... FOR UPDATE SKIP LOCKED` query to claim one pending job atomically.
3. Write the ARS weighted-sum formula given four sub-scores and their weights.
4. Write `_percentile()` using nearest-rank (no interpolation).
5. Write the retry-decision logic for an HTTP adapter: which exceptions/status codes retry, which don't, and why.
6. Write `LocalPythonAdapter._load_entrypoint()` given a string like `"agents.rag_agent.agent:run_turn"`.
7. Write the cosine-similarity function used in `diff_engine.py`.
8. Write the 2×2 classification logic for `code_changed` × `behavior_changed`.
9. Write a refresh-token rotation function including reuse detection and revoke-all-on-reuse.
10. Write a JWT decode function that rejects a token whose `type` claim isn't `"access"`.
11. Write the sliding-window rate limiter's four-operation Redis pipeline.
12. Write `_check_groundedness()`'s core loop: for each assistant turn with an empty retrieval result, check for an honesty-signal phrase.
13. Write a scorer that sums `cost_usd` across assistant turns and compares against a configured max.
14. Write `_owned_agent()`: load an `Agent` by ID, 404 if missing or tenant mismatch.
15. Write the eval-case scorer loop: run every scorer, AND their `passed` flags, don't short-circuit.
16. Write a `ThreadPoolExecutor`-based virtual-user loop that calls an adapter repeatedly until a stop time.
17. Write the content-hash function for a local file: raw bytes, SHA256, no timestamp in the input.
18. Write `build_adapter()`'s URL-scheme dispatch between an HTTP adapter and a local Python adapter.
19. Write a bulk "revoke all refresh tokens for this user" SQLAlchemy statement as a single UPDATE, not a loop.
20. Write the DBSCAN-based clustering call given a precomputed cosine-distance matrix (you may call `sklearn.cluster.DBSCAN` directly).

### 15 Debugging Questions

1. `get_eval_run()` in `eval_runs.py` writes to a `JobStatusCache` but the endpoint's response time doesn't improve on repeated calls. What's wrong? *(Answer: the cache is written but never read — `gate_engine.evaluate()` is recomputed every call.)*
2. A load-tested agent's actual cost-per-hour keeps looking suspiciously round and stable no matter what the agent does, when tested via `research_pipeline_agent`. What would you check? *(Answer: `total_input_tokens`/`total_output_tokens` are declared but never incremented — cost is a flat 5-call estimate, not measured.)*
3. The research pipeline agent occasionally "verifies" clearly incomplete answers as sufficient. Where would you look? *(Answer: `_verifier()` defaults to `is_sufficient=True` on JSON parse failure — fails open instead of closed.)*
4. `dashboard.py`'s agent-detail page gets slower the more completed runs an agent has. Why, specifically? *(Answer: `gate_engine.evaluate()` opens its own `SessionLocal()` inside a loop already running inside a request handler with its own open session — nested-session amplification per iteration.)*
5. A tenant reports they can tell (from response codes) whether another tenant's agent ID exists, even though they can't read its data. What pattern is missing, and where should it be applied? *(Answer: some endpoint is returning 403 instead of 404 on cross-tenant access — should follow `_owned_agent()`'s 404-only discipline.)*
6. Two worker processes occasionally both pick up what looks like the same job under high load with the Postgres-backed queue. What would you check in `claim_next_job()`? *(Answer: confirm `with_for_update(skip_locked=True)` is actually present and that the claim's SELECT+UPDATE+commit is one atomic unit, not split across separate transactions.)*
7. After a broker restart, `eval_worker_v2.py` seems to process a handful of jobs twice. Where do you look first? *(Answer: `DistributedLock` acquisition around each job — if the lock TTL is shorter than typical job runtime, redelivery + a since-expired lock could allow a genuine double-run; also check the offset-commit-after-processing invariant hasn't been reordered.)*
8. A refresh token that should have been rejected as reused instead issued a new token pair. What's the one comparison you'd check first? *(Answer: `record.revoked_at is not None` — confirm the presented token's DB row is actually being checked for prior revocation before being trusted.)*
9. An agent under eval is somehow retried twice for the same HTTP request after a slow response, and a duplicate side effect (e.g. a duplicate ticket) results. What retry-classification mistake would cause this? *(Answer: a `ReadTimeout` being treated as retryable when it should raise immediately — the response may have already been processed.)*
10. `SafetyScorer` is flagging an agent as ungrounded even though the agent used a tool that legitimately returned zero results (e.g., "how many items are in this empty cart"). What would you check? *(Answer: whether that tool's name incorrectly matches `_RETRIEVAL_TOOL_NAME_MARKERS` — the groundedness check should only apply to retrieval-shaped tools, not all tools with empty results.)*
11. A behavioral-diff run between two versions of the *same* code never produces `SILENT_DRIFT`, even when you know the underlying model changed. What input might be wrong? *(Answer: `compute_diff()` needs two eval_run IDs of the same version/content_hash across time — if version IDs were passed instead, or if `code_changed` is being computed incorrectly, the quadrant logic can't reach `SILENT_DRIFT`.)*
12. A CI pipeline's `agentbench ci-check` call hangs indefinitely on a stuck run. Where's the missing safeguard? *(Answer: `run_cmd()`'s poll loop in `apps/cli/commands/run.py` has no timeout/max-iterations — it polls forever if the run never reaches `completed`/`failed`.)*
13. A new agent type's `session_state` isn't persisting across turns when run through `HTTPAdapter`, even though it works fine locally. What would you check? *(Answer: `_apply_session_state()`'s in-place `.clear()`/`.update()` — if this was changed to reassignment (`session_state = new_state`), the eval engine's held reference would silently stop seeing updates.)*
14. Rate limiting seems to under-count requests slightly under heavy concurrent load. What part of `RateLimiter.is_allowed()`'s Redis pipeline would you inspect? *(Answer: whether the four operations are genuinely atomic — a raw pipeline batches commands but a true Lua-script `EVAL` would be needed for full atomicity under race conditions; also check the always-executes `ZADD` behavior.)*
15. `GatePolicy`'s default pass-rate threshold and `gate_engine.py`'s in-code default disagree after someone changes one but not the other. Where are both defined? *(Answer: `GatePolicy.min_pass_rate`'s `server_default="0.9"` in `models/gate.py`, and `DEFAULT_MIN_PASS_RATE = 0.9` in `gate_engine.py` — two independent sources of truth for the same number.)*

---

## 10. 80/20 Study Plan

### Top 20% of files → 80% of interview value

| Rank | File | Time | Why it's in the 20% |
|---|---|---|---|
| 1 | `apps/api/services/gate_engine.py` | 25 min | The single most likely live-coding ask; pure/impure split is the repo's core discipline |
| 2 | `apps/api/services/eval_engine.py` | 45 min | The heart of the product; documented real bug fixes |
| 3 | `apps/api/core/auth.py` | 30 min | Highest-density security logic; refresh-rotation is a near-certain question |
| 4 | `apps/api/core/jobqueue.py` + `redpanda_queue.py` | 40 min | The STABLE CONTRACT — best systems-design story in the repo |
| 5 | `apps/api/services/adapters/base.py`, `local_python.py`, `http_adapter.py` | 30 min | The Protocol everything else builds on; retry-safety reasoning |
| 6 | `apps/api/workers/eval_worker.py` + `eval_worker_v2.py` | 25 min | Polling vs. event-driven — classic contrast question |
| 7 | `apps/api/core/security.py` | 25 min | Dual-credential dispatch + tenant-replay bug fix |
| 8 | `apps/api/routers/ci.py` | 10 min | Embodies the whole product thesis in 48 lines |
| 9 | `apps/api/services/ars_engine.py` + `diff_engine.py` | 40 min | Two of the five novelty features, both clean and quotable |
| 10 | `agents/rag_agent/agent.py` + `research_pipeline_agent/agent.py` | 30 min | Best AI/ML-flavored questions; one has a real, findable bug |

**Total: ~5 hours** for the top 20%. That covers the large majority of what a 20+ LPA SWE/AI-ML interviewer will actually probe.

### Suggested reading order
Follow v1 §1's Project Entry Map exactly — it's already dependency-ordered (data model → core loop → gate → scorers → adapters → queue → workers → auth → routers → novelty features → CLI → agents).

### Suggested rewrite order
Follow v3 §8's table top to bottom — it's already ordered by interview probability. Do the top 6 before anything else.

### Final revision checklist (night before)

```
□ Write _compute_gate_result() cold, in under 5 minutes
□ Narrate rotate_refresh_token()'s 6 steps out loud, no notes
□ Explain the STABLE CONTRACT in 60 seconds: what it is, why it exists, what bug it didn't prevent
□ Explain why ci.py doesn't return pass/fail synchronously
□ Name the 5 novelty features and the one real algorithm behind each (weighted sum / cosine similarity / DBSCAN / percentile+threads / fault-injection decorator)
□ Name 3 real bugs/gaps you can point to in this exact codebase (dead cache write, dead cost variables, verifier fails open) — have these ready for "tell me about a bug"
□ Re-read v1 §6 Interview Hotspots once, top to bottom
□ Sleep
```
