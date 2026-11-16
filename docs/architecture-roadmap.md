# RedLine — Architecture Roadmap

**Repository:** `uh-bhinav/RedLine`
**Document type:** Living architecture evolution document
**Last updated:** 2026-07-29
**Companion documents:** `AgentBench_Cloud_Foundational_Document-2.md` (the thesis), `docs/todo.md` (the work queue), `checkpoint.md` (what was built and why)

---

## 0. Roadmap Correction (2026-07-29)

This document was rewritten because the phase plan had drifted from the foundational document.

**The drift:** `AgentBench_Cloud_Foundational_Document-2.md` §13 defines Phase 3 as *the five novelty
features* (ARS, Behavioral Diff, Failure Mining, Chaos, Load Testing) and places multi-tenancy,
auth/RBAC, and observability inside Phase 2. The previous version of this roadmap defined Phase 3
as multi-tenancy enforcement, Tempo, async workers, OIDC, quota tracking and drift v2 — of which
four items are Phase 2 leftovers and none are novelty features.

**The consequence, stated plainly:** with zero of the five differentiators built, RedLine today is a
very well-engineered Braintrust clone. `_SCORERS` in `eval_engine.py` is
`[ContainsMatch, Cost, Latency, LLMJudge]`. There is no reliability score, no behavioural diff, no
fault injection, no load runner, no failure clustering. §4.2 of the foundational document names the
validated niche as *"continuous reliability validation + enforced deployment safety + closed-loop
production learning."* Only the middle third exists.

**The correction:** Phase 3 is now a deliberately **thin** infrastructure slice — only the items the
novelty features have a hard dependency on. Everything else that was in the old Phase 3 moves to
Phase 5. Phase 4 is the novelty work. Phase 5 is hardening, deployment and launch.

Nothing already built is being discarded. The Phase 2 infrastructure is the foundation the novelty
features run on; the correction is about **what gets built next**, not about what was built.

---

## Architecture Evolution Overview

```
Phase 1          Phase 2          Phase 3           Phase 4            Phase 5
(Complete)       (Complete)       (Thin slice)      (Differentiator)   (Launch)
──────────────────────────────────────────────────────────────────────────────────
Monolith     →   Microservices →  Foundation    →   Research-grade  →  Hardening
Postgres        + Redpanda        close-out         novelty            + deploy
job queue       + Redis           ─────────         ──────────────     ─────────
                + ClickHouse      Real tenancy      ARS + SLO          Platform CI/CD
                + k3d/KEDA        HTTPAdapter       Behavioral Diff    Dashboard v2
                + OTel            Redis limiter     Chaos Engineering  Public deploy
                + Drift v0        Packaging         Load Testing       Docs + launch
                                  OSS scaffolding   Failure Mining
```

The rule for Phase 3: **an item belongs in Phase 3 only if a Phase 4 novelty feature cannot be
built correctly without it.** Anything else waits for Phase 5.

---

## Phase 1 — Core Eval Loop (✅ Complete)

**Goal:** Prove the eval pipeline end-to-end on a single machine.

**What was built:**
- FastAPI monolith with all routers included
- PostgreSQL as the only datastore
- `PostgresJobQueue` with SKIP LOCKED (STABLE CONTRACT v1)
- `LocalPythonAdapter` via importlib (STABLE CONTRACT v2)
- `run_eval()` → scorers → `_compute_gate_result()` pipeline
- Level 1 RAG agent (TrailLight Gear, 3 eval cases)
- JWT + API key auth with RBAC
- React dashboard (3 pages)
- GitHub Actions CI with branch protection gate
- 37 unit tests

```
                    ┌──────────────────┐
                    │ FastAPI Monolith │
                    │ (apps/api/main)  │
HTTP ───────────────►  /agents         │
                    │  /eval-runs      │
                    │  /ci /auth       │
                    │  /dashboard      │
                    └────────┬─────────┘
                             │
                    ┌────────▼────────┐
                    │   PostgreSQL    │
                    │   port 5433     │
                    │  jobs table     │◄──── SKIP LOCKED
                    └────────┬────────┘
                             ▲
                    ┌────────┴────────┐
                    │  eval_worker.py │
                    └─────────────────┘
```

---

## Phase 2 — Real Distributed Infrastructure (✅ Complete)

**Goal:** Turn the monolith into a distributed system with production-realistic infrastructure.

| Addition | Purpose | ADR |
|---|---|---|
| Redpanda v26.1.11 | Event bus, replaces Postgres job polling | ADR-001 |
| Redis 7 | Rate limiting, distributed locks, job status cache | — |
| ClickHouse 26.3 | Append-heavy trace/event analytics | — |
| Service decomposition | eval_service, agent_service, gate_service | — |
| nginx gateway | Route by URL prefix to correct service | — |
| k3d + Helm | Local Kubernetes deployment | ADR-003 |
| KEDA | Consumer-lag-based worker autoscaling | ADR-003 |
| OpenTelemetry | Distributed tracing (console exporter) | — |
| Prometheus + Grafana | Metrics and dashboards | — |
| APScheduler drift cron | Model drift detection on schedule | — |
| Model profiles | Provider indirection, no hardcoded model names | ADR-004 (implicit) |
| Level 3 + Level 4 agents | stateful-support-agent, research-pipeline-agent | — |

```
                         ┌──────────────────────────────────┐
                         │  nginx gateway (port 8085/8000)  │
                         └──────┬──────────┬──────────┬─────┘
                                │          │          │
               ┌────────────────▼──┐  ┌────▼──────┐  ┌▼──────────────┐
               │  eval_service     │  │agent_svc  │  │gate_service   │
               │  :8001            │  │:8002      │  │:8003          │
               │  /eval-runs       │  │/agents    │  │/dashboard     │
               │  /ci /auth        │  │/eval-suites│ └───────────────┘
               └────────┬──────────┘  └─────┬─────┘
                        │                   │
               ┌────────▼───────────────────▼────────────────┐
               │              PostgreSQL (5433)              │
               └─────────────────────────────────────────────┘
                        │                   │
               ┌────────▼────────┐  ┌───────▼────────┐
               │  Redpanda 19092 │  │  Redis 6379    │
               │  eval.requested │  │  locks, limits │
               └────────┬────────┘  └────────────────┘
                        │
               ┌────────▼────────┐  ┌────────────────┐
               │  eval_worker_v2 │  │  ClickHouse    │
               │  consumer group │  │  traces table  │
               └────────┬────────┘  └────────────────┘
                        │
               ┌────────▼────────┐
               │  k3d + KEDA     │
               │  scale on lag   │
               └─────────────────┘
```

**Phase 2 gaps carried forward:** multi-tenancy was specified in the foundational document as
Phase 2 (§10.1) but was only partially delivered — `tenant_id` exists on every row and the
mutating routers filter by it, but `dashboard.py` and `eval_runs.py` still resolve the tenant with
`db.query(Tenant).first()` and the `/dashboard` routes have no auth at all. That debt is repaid in
Phase 3.1.

---

## Phase 3 — Foundation Close-Out (⏳ Current)

**Goal:** Close only the gaps that Phase 4 has a hard dependency on, plus make the repository
something a stranger can actually install. Nothing speculative.

Each item below states **which Phase 4 feature requires it**. If an item cannot answer that
question, it is not in Phase 3.

### 3.1 Real Tenant Scoping + Dashboard Auth

**Required by:** all of Phase 4. ARS scores, behavioural diffs, chaos results, load runs and mined
failure clusters are all new per-tenant data surfaces. Building five features on
`db.query(Tenant).first()` means rewriting five features later.

**Current defect:**
- `apps/api/routers/dashboard.py:30` and `:89` — `tenant = db.query(Tenant).first()`
- `apps/api/routers/eval_runs.py:28` — same
- `apps/api/routers/dashboard.py` docstring: *"No auth required on these — the dashboard is a
  read-only internal tool."* Correct on a laptop. A cross-tenant data leak the moment a second
  tenant exists on a public deployment.

**Change:**
- Add a `get_tenant_context(auth = Depends(require_auth), db = Depends(get_db))` dependency that
  resolves the tenant from the authenticated `AuthContext` and 404s on a missing/foreign tenant.
- Every router takes `tenant` from that dependency. `db.query(Tenant).first()` is deleted from the
  codebase and never reintroduced.
- All `/dashboard` routes require auth (Viewer role is sufficient — they are read-only).
- Integration test that proves tenant A cannot read tenant B's agents, runs, or case results.

**Files:** `apps/api/core/auth.py`, `apps/api/routers/dashboard.py`, `apps/api/routers/eval_runs.py`,
`apps/api/tests/integration/test_tenant_isolation.py` (new)

### 3.2 HTTPAdapter for External Agents

**Required by:** 4.3 Chaos Engineering and 4.4 Load Testing, plus every open-source user.

Chaos engineering injects faults *on the boundary between RedLine and the agent's dependencies* —
that boundary is far cleaner over HTTP than through in-process `importlib`. Load testing fires N
concurrent sessions at an agent; with `LocalPythonAdapter` those all execute inside the worker
process, which measures RedLine's concurrency, not the agent's.

**It is also the single biggest adoption blocker.** Today an outside user's agent must be a Python
function importable from inside this repository. §8.1 of the foundational document promises
*"any agent that can be called via HTTP or Python function."* Without `HTTPAdapter` the
framework-agnostic claim in the README would be false.

**Change:**
- `apps/api/services/adapters/http_adapter.py` implementing the `AgentAdapter` Protocol.
- `run_turn()` POSTs `{"session_state": ..., "user_message": ...}` and parses `AgentTurnResult`.
- Adapter selection by `agent_version.entrypoint` scheme: `module:function` → `LocalPythonAdapter`,
  `http(s)://…` → `HTTPAdapter`.
- Timeouts, bounded retries on connection errors, and a documented agent-side contract.
- **Zero changes to `eval_engine.py`** — this is the STABLE CONTRACT paying off.

**Files:** `apps/api/services/adapters/http_adapter.py` (new),
`apps/api/services/adapters/__init__.py` (selection helper), `apps/api/tests/unit/test_http_adapter.py` (new)

### 3.3 Redis-Backed LLM Rate Limiter + Daily Quota

**Required by:** 4.4 Load Testing (directly) and 4.2 Behavioral Diff (which runs a full suite twice).

The current limiter is an in-process `deque`. KEDA already scales `eval-worker` past one replica,
which makes the per-process window **arithmetically wrong** — N pods each independently permit the
full RPM. Load testing at concurrency makes this failure certain rather than likely.

The daily quota counter is not a nice-to-have: Level 3 and Level 4 gate verdicts are *currently
blocked* on Gemini free-tier daily exhaustion, and Phase 4 multiplies LLM call volume.

**Change:**
- Redis sorted-set sliding window, one key per model profile:
  `ratelimit:llm:{provider}:{model}`. `ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` in a pipeline.
- Daily counter `quota:llm:{provider}:{model}:{YYYY-MM-DD}` with 24h TTL, checked inside
  `acquire()` before the per-minute window.
- `acquire()` signature unchanged — STABLE CONTRACT.
- Graceful degradation: if Redis is unreachable, fall back to the in-process window and log loudly.

**Files:** `apps/api/core/llm_rate_limiter.py`, `apps/api/tests/unit/test_llm_rate_limiter.py` (new)

### 3.4 Installable `agentbench` CLI

**Required by:** 4.2/4.3/4.4 all ship as CLI verbs (`agentbench diff`, `agentbench chaos`,
`agentbench load`). §7 of the foundational document lists the CLI as deliverable #1 and §5.5
literally specifies `agentbench load --users 10000`.

**Current defect:** no `pyproject.toml`. The CLI runs as `python -m apps.cli.main` from inside this
repository, with dependencies at `apps/api/requirements.txt`. A stranger cannot `pip install
agentbench`, and the CI workflow works around it with a hand-written `pip install` line listing
seven packages.

**Change:**
- `pyproject.toml` with an `agentbench = "apps.cli.main:app"` console script.
- Dependency split so the CLI installs **without** `psycopg2`, `confluent-kafka`, or
  `clickhouse-driver`: base = CLI deps, `[project.optional-dependencies] api = [...]`.
  This is enforced by architectural rule #6 (the CLI never imports from `apps.api`) — the packaging
  should make violating that rule a build failure, not a convention.
- Simplify the GitHub Actions install step to `pip install -e .`.

**Files:** `pyproject.toml` (new), `apps/api/requirements.txt`, `.github/workflows/agentbench-check.yml`

### 3.5 Open-Source Scaffolding + Repo Hygiene

**Required by:** the stated goal ("allowed for open source contributions"). §7 lists
*"Public docs / README good enough for outside contributors"* as a deliverable.

**Current defect:** there is no `README.md`, no `LICENSE`, no `CONTRIBUTING.md`, no
`CODE_OF_CONDUCT.md`. `git ls-files` confirms it. The repository also carries litter: `run.log`
(57KB), `CI_TEST.md`, `CI_TEST1.md`, multiple `.DS_Store` files.

**Change:**
- `README.md` — problem, positioning against LangSmith/Braintrust/Arize, architecture diagram,
  60-second quickstart, the gate-blocking-a-PR proof.
- `LICENSE` — Apache-2.0 (patent grant matters for a platform others build on; MIT does not have one).
- `CONTRIBUTING.md` — dev setup, `pytest -m unit`, the 10 architectural rules, ADR process.
- `CODE_OF_CONDUCT.md`, issue and PR templates.
- Delete litter; add `run.log` and `*.log` to `.gitignore`.
- Close out Bug 1 (debug prints in `rag_agent._load_chunks()`) and Bug 3 (`rag_agent` hardcoded
  `CHAT_MODEL` → `get_profile("standard")`) — both are things a first-time reader would see.

**Explicitly deferred to Phase 5:** Grafana Tempo, async worker v3, Google OIDC, DLQ, suite
registry/ecosystem. None of them block a Phase 4 feature.

---

## Phase 4 — Research-Grade Novelty (✅ Complete 2026-07-29)

**Goal:** Build the five features from foundational document §5. This is what makes RedLine
different from Braintrust/Arize/LangSmith rather than a clone of them.

**All five shipped:** Agent Reliability Score + error budget (4.1), Behavioral Diff Engine (4.2),
Chaos Engineering (4.3), Load Testing (4.4), Production Failure Mining (4.5). Every one was verified
against real infrastructure (real Postgres, real Redis, real Redpanda, real ClickHouse, real Gemini
embeddings, real HTTP concurrency) rather than asserted from code review alone, and three of the five
surfaced genuine, previously-latent bugs in existing infrastructure that this work was the first to
actually exercise (the `content_hash` uniqueness constraint making certain diff classifications
structurally unreachable; `RedpandaJobQueue.publish()` silently ignoring its own `job_type`
argument; `mine_failures()` returning session-bound ORM objects). See each section below for the
specifics and the negative controls that proved each fix actually mattered.

Ordering within Phase 4 was by dependency and by how much each one differentiates.

### 4.1 Agent Reliability Score (ARS) + SLO / Error Budget — ✅ Done 2026-07-29

**Foundational document §5.1.**

```
ARS = 0.4·correctness + 0.2·safety + 0.2·latency + 0.2·cost
```

**Why first:** it is the composite number every other Phase 4 feature reports into, and it is the
number the deployment gate should read. It also has the least new infrastructure.

**As built:**
- `_compute_ars()` is a **pure function** — same discipline as `_compute_gate_result()`. Numbers in,
  `ARSResult` out. No DB, no I/O. Each sub-score is `passed/total` for the scorer(s) measuring that
  dimension (correctness = ContainsMatch AND LLMJudge; safety = SafetyScorer; latency =
  LatencyScorer; cost = CostScorer), read from each case's already-stored `scorer_results`.
- New scorer: `SafetyScorer` — an always-on, deterministic retrieval-groundedness check (a
  retrieval-shaped tool call returning empty must be paired with an honesty phrase, or it's scored
  as a hallucination) plus an optional `safety_rubric` LLM-judge escape hatch, parallel to
  `judge_rubric`. Prompt-injection detection was deliberately **not** attempted as a generic
  heuristic here — a keyword guess would give false confidence in either direction; that is
  honestly Phase 4.3's job, where `ChaosAdapter` injects real, controlled faults instead of guessing
  from transcript text.
- New tables: `slo_policies` (agent_id, target_ars, error_budget_pct, window_days),
  `ars_snapshots` (agent_version_id, eval_run_id, ars, correctness, safety, latency, cost) —
  migration `0005`.
- `compute_error_budget()` is also pure: breach rate over a window of recent ARS scores vs an
  allowed budget. `gate_engine.evaluate()` calls it and **freezes the gate regardless of the
  current run's own score** if the budget is exhausted — this is deliberately outside the pure
  function, since it is a statement about history, not this run's numbers. Verified with a negative
  control: a run scoring a perfect ARS of 1.0 still fails the gate when history has burned the
  budget; disabling the check makes the test fail; restoring it makes the test pass again.
- `GatePolicy` gained `min_ars`; `_compute_gate_result()` gained an ARS threshold check and stayed
  pure (every pre-existing gate test passes unchanged, since `ars`/`min_ars` default to `None`).
- ARS is computed and persisted **once**, inside `eval_engine.run_eval()` at completion (non-fatal,
  like `emit_trace()`) — not inside `gate_engine.evaluate()`, which is a read path called on every
  dashboard load and must not also be a write path.

**Files:** `apps/api/services/ars_engine.py`, `apps/api/services/scorers/safety.py`,
`apps/api/models/ars.py`, migration `0005`, `apps/api/services/gate_engine.py`,
`apps/api/services/eval_engine.py`, `apps/api/schemas/eval_suite_yaml.py` (`safety_rubric` field)

**Tests:** `test_ars_engine.py` (18, pure), `test_gate_engine.py`/`test_scorers.py` extensions (15,
pure), `test_ars_end_to_end.py` (7, real Postgres + real eval engine, zero LLM cost).

### 4.2 Behavioral Diff Engine — ✅ Done 2026-07-29

**Foundational document §5.2.** *"A prompt edit that looks like one word can flip refund: approved
to refund: denied."*

**As built — and a real correction along the way:**
- Embed the final assistant message per shared `case_key` between two eval runs (the profile's
  `embedding_model`); compute per-case cosine similarity; classify via pure `_classify_diff()` into
  four quadrants: code changed + behaviour same (`SAFE_REFACTOR`), code changed + behaviour changed
  (`EXPECTED_CHANGE`), code same + behaviour changed (**`SILENT_DRIFT` — the alarm**), code same +
  behaviour same (`NO_OP`).
- **The original design used `agent_versions.content_hash` as the code axis by comparing two
  version IDs directly — this turned out to be broken.** `agent_versions` has
  `UNIQUE(agent_id, content_hash)`, so any two distinct registered versions are *guaranteed* to
  have different hashes. That makes `code_changed` `True` on every cross-version comparison,
  which makes `SILENT_DRIFT` and `NO_OP` **structurally unreachable** — not rare, impossible. Caught
  by the integration test hitting the unique constraint directly while trying to construct a
  same-hash test fixture.
- **Fix:** one real primitive, `compute_diff(eval_run_a_id, eval_run_b_id)`, taking run IDs instead
  of version IDs — this is what makes comparing a version *against its own history* possible. Two
  purpose-built wrappers sit on top: `compute_diff_for_versions()` (two different versions — always
  `code_changed=True`, answers "was this version bump safe") and `compute_diff_over_time()` (one
  version's two most recent completed runs against itself — always `code_changed=False`, answers
  "did this version drift on its own," and is the only construction that can ever show
  `SILENT_DRIFT`). The scheduler hook now calls `compute_diff_over_time()`, not a comparison against
  the previous registered version.
- This subsumes the "behavior drift" item from the old Phase 3 §6 — invoked by `drift/runner.py` on
  a schedule and by `agentbench diff` on demand (same underlying machinery either way).
- Table `behavior_diffs` (migration `0006`), append-only like `drift_snapshots` — each diff
  computation is its own historical record, never upserted.
- `POST/GET /diff-runs` (owned by `eval_service` — diffing reads eval data and calls an embedding
  model, which is eval-logic territory, not registry or gate-policy territory).
  `agentbench diff <version-a> <version-b> [--suite]`, exiting nonzero on `SILENT_DRIFT` so a CI
  pipeline can gate on it.
- **Verified live, not just unit-tested**: a third fixture agent
  (`tests/unit/fixtures/dummy_agent_drifting.py`) whose output is controlled by a module-level flag
  flipped between two eval runs of the *same* registered version — simulating "the provider changed
  the model underneath an unchanged agent" honestly. Real Gemini embedding calls on the two
  genuinely different resulting sentences correctly classified `SILENT_DRIFT`. Negative control:
  hardcoded the change-detection flag to `False`, watched 5 tests fail across the unit and
  integration suites, restored, watched them pass again.

**Files:** `apps/api/services/diff_engine.py`, `apps/api/models/diff.py`,
`apps/api/schemas/diff.py`, `apps/api/routers/diff.py`, `apps/api/services/drift/runner.py`,
`apps/cli/commands/diff.py`, migration `0006`

**Tests:** `test_diff_engine.py` (17, pure), `test_diff_engine_end_to_end.py` (7, real Postgres +
real eval engine + real Gemini embeddings, zero `generate_content` cost).

### 4.3 Agent Chaos Engineering — ✅ Done 2026-07-29

**Foundational document §5.4.**

**As built, including a claim corrected before code was written rather than after:**
a `ChaosAdapter` that **wraps** any `AgentAdapter` and implements the same Protocol —
fault injection as a decorator over the STABLE CONTRACT. The original plan (directly above, before
this update) said this meant `eval_engine.py` "does not change at all." Working through the
construction *before* writing code: `ChaosAdapter` must be built **per case** — only some cases in
a suite configure chaos — while `build_adapter()` builds one adapter per **run**. That is an honest,
small change: a `_build_case_adapter()` helper and a one-line call-site edit in the per-case loop.
What genuinely doesn't change is the STABLE CONTRACT itself — `_run_case()` and every scorer never
know whether the adapter they were handed is wrapped. (This is the same class of correction made to
HTTPAdapter's "zero changes" claim in Phase 3.2 and the Behavioral Diff Engine's content_hash design
in Phase 4.2 — the difference here is catching it during design instead of after a test failure.)

**The honest scope, stated up front:** RedLine's `AgentAdapter` is a deliberate black box (Section
8.1's framework-agnostic architecture) — the eval engine has never seen inside an agent's own
tool-calling logic, and reaching in would require framework-specific instrumentation. So
`ChaosAdapter` injects faults at the one boundary RedLine actually controls: the whole `run_turn()`
call. For an `HTTPAdapter`-wrapped deployed agent, that boundary is a **real** dependency (the
network) — for a `LocalPythonAdapter`-wrapped local agent there is no real network to fail, so a
fault there is **synthetic**. It still exercises the eval engine's and `RecoveryScorer`'s handling
honestly, but it is not simulating real infrastructure failure for that agent. Documented explicitly
in `chaos_adapter.py` rather than left as an implicit limitation someone discovers later.

- Fault modes split into two families: **total-failure** (`timeout`, `connection_reset` — the real
  adapter is never called, `session_state` is left byte-for-byte untouched) and **calls-through**
  (`malformed_response`, `plausible_wrong`, `latency_injection` — the agent runs for real; only what
  the eval engine sees afterward is altered).
- Every faulted turn carries a reserved marker tool call (`__chaos_fault__`) rather than requiring
  scorers to text-sniff for chaos — and rather than widening the `AgentTurnResult`/`ToolCall`
  STABLE CONTRACT models just to add a boolean flag.
- Chaos scenarios declared in the suite YAML (`chaos: {mode: timeout, target_turn_indices: [0]}` or
  `probability: 0.3`), validated at suite-push time via `ChaosConfigYAML` — a typo in `mode` fails
  loudly then, not silently deep inside an eval run.
- `RecoveryScorer`: a narrow, deterministic core (does the session keep producing non-empty
  responses after the last injected fault, i.e. did it survive at all) plus an optional
  `recovery_rubric` LLM-judge escape hatch for the genuinely nuanced "graceful acknowledgment vs.
  confidently hallucinated continuation" judgment — deliberately **not** attempted as a keyword
  heuristic, for the same reason `SafetyScorer` declined to guess at prompt injection: false
  confidence in either direction.
- **Verified concretely, not just asserted**: the session-state-untouched claim is proven in the
  end-to-end integration test by observing the real agent's own embedded turn counter, not merely
  checked in `ChaosAdapter`'s isolated unit tests. Negative control: disabled the per-case wrapping
  call site, watched half the end-to-end tests fail, restored, watched them pass.

**Files:** `apps/api/services/adapters/chaos_adapter.py`, `apps/api/services/scorers/recovery.py`,
`apps/api/schemas/eval_suite_yaml.py`, `apps/api/services/eval_engine.py`

**Tests:** `test_chaos_adapter.py` (17, pure), `test_scorers.py` `RecoveryScorer` extensions (6,
pure), `test_chaos_end_to_end.py` (6, real Postgres + real eval engine, zero LLM cost).

### 4.4 Agent Load Testing — ✅ Done 2026-07-29

**Foundational document §5.5.** *"Cost is often the metric that kills an agent in production."*

**As built, including a second real bug found in existing infrastructure:**
- New topic `load.requested` consumed by `load_worker.py` — the foundational document's §9.3
  "separate worker pools by resource profile" claim actually exercised, since a load runner's
  profile (many concurrent outbound requests for the run's duration) differs completely from an
  eval runner's (one case at a time). Reuses `RedpandaEvalWorker` with a new `topics` constructor
  parameter rather than a duplicated consumer class — its consume/commit/status logic was already
  topic-agnostic.
- **Found while wiring this up**: `RedpandaJobQueue.publish(tenant_id, job_type, payload)` always
  produced to `topic_eval_requested`, **completely ignoring the `job_type` argument**. Every call
  site before load testing happened to pass `job_type="eval.requested"` — the one value that
  coincidentally matched the hardcoded topic — so this was never caught. `job_type` values were
  already topic-shaped strings (`"eval.requested"` literally *is* the topic name), meaning the
  parameter was clearly meant to select the topic and simply never did. Fixed with a small
  `_KNOWN_TOPICS` registry + `_resolve_topic()` that rejects an unregistered `job_type` loudly
  rather than silently producing to an arbitrary string. (This is the same shape of latent gap as
  Phase 4.2's `content_hash` uniqueness constraint — a design choice nobody had reason to exercise
  until the third feature actually needed it.)
- `_compute_load_stats()` (pure: p50/p95/p99 via nearest-rank percentile, error rate, **cost per
  hour extrapolated from the actual measured window** — the number no competitor surfaces,
  throughput) + `run_load_test()` (DB-backed orchestrator).
- Concurrency via `ThreadPoolExecutor`, not asyncio — real OS-thread concurrency without touching
  architectural rule #1. Each virtual-user thread owns its own `session_state`; the shared adapter
  instance is safe under concurrency by construction (`HTTPAdapter`'s `httpx.Client` is thread-safe;
  `LocalPythonAdapter` is a bare function reference).
- Samples land in ClickHouse (`load_samples`, batched insert — a run can produce thousands of rows,
  unlike an eval run's ~20 trace events), the aggregate lives on the Postgres `load_runs` row.
- Async job-queue pattern (`POST /load-runs` creates + publishes + returns immediately, CLI polls),
  matching `/eval-runs` — **not** synchronous like `/diff-runs`, because a load test can run for
  minutes, genuinely too long to block a request on.
- `agentbench load <version-id> --users N --duration Ns`.
- Helm `load-worker/` deployment + `ScaledObject` (`minReplicaCount: 0` — unlike eval-worker, no
  reason to hold a pod when no load test is queued). **Not verified against a live k3d cluster this
  session** — stated plainly rather than left as an implicit gap.

**Verified for real:** genuine `ThreadPoolExecutor` concurrency against the real reference HTTP
agent (5 concurrent users produced far more than 5 requests in ~2s, positively confirming the
concurrency is real, not sequential); 10,307 real samples confirmed landed in ClickHouse by direct
query; the `job_type`→topic fix verified against real Redpanda (published to `load.requested`,
consumed only by a worker subscribed to that topic, `eval.requested` confirmed still routing
correctly afterward); negative control on `_percentile()` (stubbed to always return the minimum,
watched 2 tests fail, restored).

**Files:** `apps/api/workers/load_worker.py`, `apps/api/services/load_engine.py`,
`apps/api/models/load.py`, `apps/api/routers/load_runs.py`, `apps/api/schemas/load_run.py`,
`apps/cli/commands/load.py`, `helm/redline/templates/load-worker/`, migration `0007`,
`apps/api/core/redpanda_queue.py` (topic routing fix), `apps/api/core/clickhouse_client.py`
(`load_samples` table + `emit_load_samples()`)

**Tests:** `test_load_engine.py` (15, pure), `test_load_engine_end_to_end.py` (5, real Postgres +
real Redpanda + real ThreadPoolExecutor concurrency + real HTTP + real ClickHouse writes).

### 4.5 Production Failure Mining — ✅ Done 2026-07-29

**Foundational document §5.3.** *"This is the actual machine-learning component of the platform."*
**The fifth and final Phase 4 differentiator — all five novelty features are now built.**

**Why last:** it needs a corpus of traces, which the four features above generate.

**The honest scope, stated up front:** "production traces" implies a live traffic feed this phase
does not build — RedLine has no separate production-ingestion pipeline yet. Every recorded agent
interaction the platform has is an `EvalCaseResult` from an eval run, so that is the corpus mined:
every suite, every version, an agent's entire eval history, not just one suite's cases. A genuine
production-traffic ingestion endpoint is later work; this mines what already exists, honestly.

**As built:**
- `mine_failures()` embeds every completed eval result's final assistant message and clusters via
  **scikit-learn's DBSCAN** on a precomputed cosine-distance matrix — chosen deliberately over a
  hand-rolled routine (a feature whose entire point is "the actual ML component" shouldn't hand-roll
  its own clustering math) and over k-means (DBSCAN's noise label for outliers matters when the
  number of failure modes isn't known in advance).
- Bad-outcome correlation uses the case result's own `passed` field — the same signal the gate
  engine already uses for pass_rate — filtered through pure `_identify_significant_clusters()`
  (minimum cluster size + minimum bad-outcome rate, both stated as uncalibrated starting defaults,
  same honesty as `diff_engine`'s similarity threshold).
- Each significant cluster becomes one `CandidateCase` (a `judge_rubric` naming the pattern, `turns`
  copied from the representative case), status `pending` — never auto-trusted into a real suite.
  `POST /mining/{agent_id}/run` + `GET/POST .../candidates` expose the review workflow; approving
  promotes a candidate into a genuine `EvalCase` in an auto-created `mined-failures` suite — the
  actual closed loop the foundational document names.
- Tables `failure_clusters` (append-only) and `candidate_cases`, migration `0008`.
  `agentbench mine` / `candidates-list/-approve/-reject`.

**A real bug caught by the integration test, not by inspection:** `mine_failures()` originally
returned raw `FailureCluster` ORM objects, breaking the pattern every other Phase 4 engine follows
(pure dataclass/Pydantic results). Since the function's own `finally: db.close()` runs before the
value reaches the caller, any attribute access after return raised `DetachedInstanceError` — caught
by the integration test accessing a returned cluster's fields, not by re-reading the code. Fixed
with a `MinedCluster` dataclass capturing plain values before the session closes.

**A small refactor done along the way, not scope creep:** `diff_engine.py`'s embedding-call helper
was about to become a third copy of the same logic. Extracted to `apps/api/services/embeddings.py`,
used by both features; re-verified `diff_engine`'s existing live-embedding tests still pass
unchanged afterward.

**Verified for real:** four genuinely different sentences (not identical strings) expressing the
same recurring refund-refusal failure were correctly clustered together by real Gemini embeddings +
real DBSCAN, while three unrelated passing responses were correctly excluded. Negative control:
hardcoded the bad-outcome rate to always report 100%, watched 3 tests fail, restored.

**Files:** `apps/api/services/mining/engine.py`, `apps/api/services/embeddings.py` (new, shared),
`apps/api/models/mining.py`, `apps/api/routers/mining.py`, `apps/api/schemas/mining.py`,
`apps/cli/commands/mine.py`, migration `0008`

**Tests:** `test_mining_engine.py` (16, pure), `test_mining_engine_end_to_end.py` (5, real Postgres +
real Gemini embeddings + real clustering + the approve workflow).

---

## Phase 5 — Hardening, Deployment & Launch (🔮 After Phase 4)

**Goal:** A stranger can clone it, deploy it, and use it on their own agent.

### 5.1 Deferred Phase 3 Infrastructure

| Item | Why it waited |
|---|---|
| Grafana Tempo (replace `ConsoleSpanExporter` with OTLP → `tempo:4317`) | Nice observability; blocks no feature |
| Async workers v3 (`eval_worker_v3.py` alongside v2, never replacing it) | Large migration; rule #2 says ask why sync is insufficient first — load testing (4.4) will produce the actual answer |
| Google OIDC (`POST /auth/google/callback`) | Needed by the dashboard rewrite (5.3), not before |
| Dead-letter queue for repeatedly-failing eval jobs | Operational hardening |
| Suite registry / `agentbench pull <suite>` | Ecosystem play; needs users first |
| PgBouncer, mTLS, ClickHouse least-privilege user | Real-deployment hardening |

### 5.2 Platform CI/CD

**Foundational document §10.8.** A platform that gates other people's deployments currently deploys
itself by hand. The pipeline: push → unit + integration tests → build image → **Trivy scan** →
push to GHCR with an immutable version tag → `helm upgrade` → health check → automated rollback on
failure. Plus `pip-audit` for dependency CVEs.

### 5.3 Dashboard v2 — One High-Quality Rewrite

**Decision: deferred deliberately until the Phase 4 APIs are stable** (ADR-006). Rewriting UI while
the underlying data shapes still churn is wasted work.

**Stack:** Vite + React + **TypeScript** + TanStack Query + Tailwind + shadcn/ui + Recharts.

**Why TypeScript specifically:** FastAPI already emits an OpenAPI schema from the Pydantic response
models. Generating the client types from that schema in CI (`openapi-typescript`) means a backend
response-model change **breaks the frontend build** instead of failing silently at runtime. That is
a real engineering property, not a preference.

**Why not Next.js:** the backend is FastAPI, there is no SSR requirement and no public SEO surface
behind auth. A static SPA bundle served by the nginx gateway that already exists deploys as part of
the existing Helm chart. Next.js would mean running a Node server in the cluster for no benefit.

**Pages:** login/OIDC, agents, run detail, **ARS trend**, **behavioural diff viewer**, **chaos
results**, **load test report**, **failure clusters**, drift alerts, ClickHouse-backed trace viewer.
The current 546-line JS app cannot display any of the bolded ones, which is most of the product.

### 5.4 Public Deployment

**Decision (ADR-005): Helm is the product's deployment interface, and the cloud provider is
deliberately not chosen yet.**

The same Helm chart must deploy unchanged to k3d locally and to a real cluster publicly. Provider
selection happens after Phase 4, when the resource profile of the load runner and trace worker is
actually known rather than guessed.

- **Primary intent:** Oracle Cloud always-free ARM VM (4 core / 24 GB) running k3s. Real Kubernetes,
  genuinely $0, chart deploys unchanged.
- **Fallback:** managed Kubernetes (GKE/EKS) if the Oracle free tier proves limiting or unreliable.
- **Non-goal:** any deployment path that requires application changes. If a target needs
  `docker-compose`-shaped or PaaS-shaped rework, that target is rejected.

### 5.5 Proof of Value

**Foundational document §12, §14.** This is the most convincing artefact in the whole project:
run the three benchmark agents through manual ad-hoc testing *and* through RedLine, and document
the gap with real numbers ("manual testing found N failures; RedLine found M, and blocked the
deploy"). Plus the `EXPLAIN ANALYZE` index before/after from §10.6 and the k6 p95 number from §12.

### 5.6 Launch

Docs site, open-source announcement, the recorded gate-blocking-a-PR demo.

---

## STABLE CONTRACTs — Never Break These Across Phases

Phase N+1 adds new implementations but never changes the calling code.

| Contract | Interface | Current Implementation | Additions |
|---|---|---|---|
| JobQueue | `publish(tenant_id, job_type, payload)` + `get_status(job_id)` | `RedpandaJobQueue` | No change |
| AgentAdapter | `run_turn(session_state, user_message) -> AgentTurnResult` | `LocalPythonAdapter` | `HTTPAdapter` (3.2), `ChaosAdapter` (4.3, wraps either) |
| LLMRateLimiter | `acquire()` | In-process deque | Redis sorted set (3.3) |
| Gate purity | `_compute_gate_result(numbers) -> GateResult` | Pure function | Gains ARS threshold (4.1), stays pure |
| ARS purity | `_compute_ars(numbers) -> ARSResult` | — | New in 4.1, pure by construction |

`ChaosAdapter` is worth calling out: it satisfies the `AgentAdapter` Protocol *and* wraps another
`AgentAdapter`. Chaos engineering therefore requires zero changes to `eval_engine.py`. That is the
return on having declared the adapter contract stable in Phase 1.

---

## Technology Version Lock

Tested and stable. Do not upgrade without a migration plan.

| Package | Version | Notes |
|---------|---------|-------|
| FastAPI | 0.115.6 | starlette 0.41.x — do NOT add prometheus-fastapi-instrumentator |
| SQLAlchemy | 2.0.x | Synchronous ORM — do NOT mix AsyncSession before Phase 5.1 |
| confluent-kafka | 2.14.2 | librdkafka-backed — compatible with Redpanda |
| prometheus-client | 0.21.1 | Direct metrics only |
| OpenTelemetry SDK | 1.34.1 | Console exporter now, OTLP → Tempo in Phase 5.1 |
| APScheduler | 3.11.1 | BlockingScheduler — BackgroundScheduler drops missed jobs |
| python-jose | 3.3.0 | JWT — HS256 only |
| passlib[bcrypt] | 1.7.4 | bcrypt only |
| Redpanda | v26.1.11 | External Kafka port 19092 |
| ClickHouse | 26.3 | MergeTree for traces; `load_samples` in Phase 4.4 |
| Redis | 7 | Sorted sets for rate limiting (Phase 3.3) |
| PostgreSQL | 16 | Port 5433 (not 5432) |
