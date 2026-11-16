# RedLine — Repository Status

**Last updated:** 2026-08-02
**Repository:** `uh-bhinav/RedLine`
**Current phase:** Phase 4 (Research-Grade Novelty) — ✅ **complete, all 5 features shipped**. Phase 5 (Hardening, Deployment & Launch) — **5.1 (infra hardening), 5.2 (CI/CD), 5.5 (proof of value) complete 2026-08-02**; 5.3 (dashboard v2), 5.4 (public deployment), and OIDC deferred pending external accounts.

> Phase ordering was corrected on 2026-07-29 to match `AgentBench_Cloud_Foundational_Document-2.md`
> §13. See §0 of `docs/architecture-roadmap.md`.

---

## Current State

| Area | Status | Notes |
|------|--------|-------|
| Phase 1 — Core Eval Loop | ✅ Complete | |
| Phase 2 — Distributed Infrastructure | ✅ Complete | Redpanda, Redis, ClickHouse, k3d, KEDA, OTel |
| Phase 3 — Foundation Close-Out | ✅ **Complete (2026-07-29)** | Real tenancy, `HTTPAdapter`, Redis rate limiter + daily quota, installable CLI, OSS scaffolding |
| Phase 4 — Novelty features | ✅ **Complete 2026-07-29** | All 5 features shipped and verified |
| Phase 5.1 — Infra hardening | ✅ **Complete 2026-08-02** | Tempo tracing, dead-letter queue, PgBouncer (opt-in), ClickHouse least-privilege user, JWT rotation runbook. mTLS explicitly deferred to 5.4. See `docs/infra-hardening.md` |
| Phase 5.2 — CI/CD pipeline | ✅ **Complete 2026-08-02** | `.github/workflows/ci.yml`: unit + integration tests, build + Trivy + pip-audit, GHCR push (main), Helm deploy + health check (inert until a cluster exists) |
| Phase 5.3 — Dashboard v2 | ⛔ Not started | Deferred — multi-day TypeScript rewrite, out of scope for this pass |
| Phase 5.4 — Public deployment | ⛔ Not started | Deferred — needs an Oracle Cloud account the user hasn't set up yet |
| Phase 5.5 — Proof of value | ✅ **Complete 2026-08-02** | See `docs/proof-of-value.md`, `docs/explain-analyze-eval-runs-index.md` |
| Level 1 (RAG agent) gate verdict | ✅ Verified | Pass rate 0.67, gate FAIL (correct behaviour) |
| Level 3 (stateful-support-agent) gate verdict | ⚠️ Re-attempted, still blocked | Re-run 2026-08-02: blocked on a genuine Gemini free-tier daily quota (20 req/day for `gemini-3.5-flash`) — a different real limit than the earlier outage, surfaced honestly via `EvalRun.error` rather than forced past. See `docs/proof-of-value.md`. |
| Level 4 (research-pipeline-agent) gate verdict | ✅ Verified | Pass rate 0.50, gate FAIL (3 of 6 cases failed on real scorer findings, plus an ARS error-budget breach) |
| CI/GitHub Actions integration | ✅ Verified | Blocks PR merge on gate failure (PR #2); CI now installs via `pip install .` instead of a hand-written package list |
| k3d Kubernetes deployment | ✅ Deployed | KEDA autoscaling on consumer lag |
| Prometheus + Grafana monitoring | ✅ Deployed | `make monitoring-install` |
| React dashboard v1 | ⚠️ Placeholder, now authenticated | 546 LOC plain JS, 3 read-only pages. Auth added (paste-a-token, not a login flow — ADR-006). Full rewrite still deferred to Phase 5. |
| Public deployment | ⛔ None | Local only. Helm is the deployment interface (ADR-005) |
| Open-source readiness | ✅ Ready | README, LICENSE (Apache-2.0), CONTRIBUTING, CODE_OF_CONDUCT, issue/PR templates, installable `pyproject.toml` all present |
| Agent can be reached over HTTP | ✅ Verified | `HTTPAdapter` + reference agent + real eval run against it, end to end |
| Multi-tenant isolation | ✅ Verified | 11 integration tests, including a negative control that reproduces the old leak |
| Rate limiting shared across workers | ✅ Verified | Real Redis, real concurrency test, real outage-and-recovery demo |

---

## The Differentiator Gap

`_SCORERS` in `apps/api/services/eval_engine.py` is now
`[ContainsMatchScorer, CostScorer, LatencyScorer, SafetyScorer, LLMJudgeScorer]`.

| Foundational doc §5 feature | Built? |
|---|---|
| 5.1 Agent Reliability Score + SLO/error budget | ✅ **Done 2026-07-29** |
| 5.2 Behavioral Diff Engine | ✅ **Done 2026-07-29** |
| 5.3 Production Failure Mining | ❌ |
| 5.4 Agent Chaos Engineering | ✅ **Done 2026-07-29** |
| 5.5 Agent Load Testing | ✅ **Done 2026-07-29** |
| 5.3 Production Failure Mining | ✅ **Done 2026-07-29** |

**All five differentiators are real. Phase 4 is complete.** ARS is computed per run, persisted, and gates deployments —
including the error-budget freeze mechanic (a perfect-scoring run still fails the gate if recent
history has burned the agent's budget, verified with a negative control). The Behavioral Diff
Engine classifies any version comparison into one of four quadrants (no-op / safe refactor /
expected change / **silent drift**), with the alarm case — code unchanged, behavior changed —
verified live against real Gemini embeddings using a fixture agent whose output is deliberately
flipped between two runs of the same registered version. Chaos Engineering injects controlled
faults (timeout, connection reset, malformed response, plausible-wrong, latency injection) at the
RedLine↔agent boundary via `ChaosAdapter`, with `RecoveryScorer` checking the session survives —
the "session state genuinely untouched by a total-failure fault" claim proven concretely by
observing a fixture agent's own embedded turn counter, not just asserted in isolated unit tests.
Agent Load Testing fires real concurrent `ThreadPoolExecutor` threads at an agent version and
reports p50/p95/p99 latency, error rate, and **cost per hour at that concurrency** — verified with
real HTTP concurrency against the reference agent and 10,307 real samples confirmed in ClickHouse.
Production Failure Mining clusters an agent's entire eval history via real scikit-learn DBSCAN on
real Gemini embeddings, flags clusters correlated with bad outcomes, and turns them into candidate
regression cases awaiting human approval — verified by clustering four genuinely different
sentences expressing the same recurring failure while correctly excluding unrelated passing
responses. RedLine has now shipped all five differentiators the foundational document names as
what separates it from a Braintrust-shaped eval-and-observability clone.

---

## Infrastructure Health

| Service | Port | Status |
|---------|------|--------|
| PostgreSQL 16 | 5433 | ✅ Running |
| Redis 7 | 6379 | ✅ Running |
| Redpanda v26.1.11 | 19092 | ✅ Running |
| ClickHouse 26.3 | 8123 | ✅ Running |
| eval_service | 8001 | ✅ Running (Docker Compose) |
| agent_service | 8002 | ✅ Running (Docker Compose) |
| gate_service | 8003 | ✅ Running (Docker Compose) |
| nginx gateway | 8085 | ✅ Running (Docker Compose) |
| React dashboard v1 | 5173 | 🔄 Start manually (`npm run dev`) |
| k3d cluster | 8000 | ✅ Running (k3d mode) |

---

## Active Bugs

**None open.** This table previously listed Bug 2 and Bug 6 as active — both were confirmed fixed
during the Phase 4.5 cleanup pass (see `docs/todo.md` for the full verification detail); this table
was simply stale relative to `docs/todo.md`, corrected 2026-08-02 after re-verifying both fixes are
actually present in the current code (`docker-compose.yml`'s dedicated `k3d` Redpanda listener;
`grep -n "COPY .env" apps/*/Dockerfile` returns only the explanatory "deliberately NOT" comments,
no three-service `.env` files baked into an image layer).

**Closed 2026-07-29:**
- **Bug 1** (debug prints in `_load_chunks()`) — removed.
- **Bug 3** (RAG agent hardcoded `CHAT_MODEL`) — now uses `get_profile("standard")` +
  `get_limiter("standard")`. Two more instances of the same violation found and fixed in the same
  pass: `scorers/llm_judge.py`'s `JUDGE_MODEL` constant (which also had **zero rate limiting at
  all** — verified live against Gemini that it's now metered and the daily quota counter
  increments), and a hardcoded `--model` default in `apps/cli/commands/register_version.py`.
- **Bug 4** (not a bug) — verified `enable.auto.commit: False` + post-processing
  `commit_offset()`; at-least-once semantics correct as built.
- **Bug 5** (dashboard auth + fake tenancy) — real `TenantContext`, all `/dashboard` routes
  authenticated, `db.query(Tenant).first()` removed from every router. 11 integration tests,
  including a negative control.

**Bug 6 (closed 2026-07-29, Phase 4.5 cleanup):**
- All three service Dockerfiles previously did `COPY .env .env`, baking the Gemini key and JWT
  secret into every image layer, violating foundational doc §10.10. Removed from all three;
  verified both compose (`env_file: .env`) and Helm (Secret/ConfigMap via `_helpers.tpl`'s
  `commonEnv`) supply every variable without it, and that a rebuilt image genuinely has no `.env`
  file inside (`docker run --rm --entrypoint sh <image> -c 'test -f /app/.env && echo FOUND_BAD ||
  echo absent_good'` → `absent_good` for all three, per `docs/todo.md`).
- Separately, all three Dockerfiles were missing `COPY config ./config` — `model_profiles.py`
  couldn't resolve `config/model_profiles.yaml` inside any container, so every containerised
  service raised `FileNotFoundError` on its first `get_profile()` call. Fixed and verified in all
  three (rebuilt, confirmed `get_profile()`/`get_limiter()` resolve inside each container).

---

## Test Suite Status

| Suite | Count | Status |
|-------|-------|--------|
| Unit tests (`pytest -m unit`) | **210 passed** | ✅ Verified — was 39 actually running under the old markers despite an "58" claim; see below |
| Integration tests (`pytest -m integration`, non-LLM-cost files) | **60 passed** | ✅ Verified together, twice in a row for determinism |
| `test_llm_judge_scorer.py` | **3 passed** | ✅ Verified live against real Gemini |

**Test-marker integrity fixed 2026-07-29:** `test_scorers.py` (15 tests), `test_local_python_adapter.py`
(4 tests), and `test_jobqueue.py` had no `pytestmark`, so `pytest -m unit` silently excluded them —
only 39 of the claimed 58 tests ever actually ran under that command. `test_jobqueue.py` opens real
Postgres connections and was misfiled in `tests/unit/`; moved to `tests/integration/`.
`test_llm_judge_scorer.py` (real LLM calls, no marker) fixed the same way. `pytest -m unit` now
genuinely runs 107 (the original ~58 plus everything added this session).

New coverage added this session: `test_tenant_isolation.py` (11), `test_http_adapter.py` (23,
mocked) + `test_http_adapter_end_to_end.py` (4, real server + real eval engine),
`test_llm_rate_limiter.py` (18, unit) + `test_llm_rate_limiter_redis.py` (12, real Redis),
`test_packaging.py` (8).

---

## Seeded Data (Reference)

| Item | ID |
|------|----|
| Tenant | `c1caeaf6-d6ab-4f93-99d8-25907cfebd6d` |
| Admin user | `admin@redline.local` / `ChangeMe123!` |
| RAG agent | `b8003a26-f601-4c32-a4f3-7ac4fe502cad` |
| RAG version v1 | `a259d9c5-9a89-4cbf-9060-edea9d29b325` |
| Baseline suite | `b2d571f2-d350-48fd-b485-7fc4273dc743` |
| Level 3 agent | `2e216305-6049-41ca-baba-456eb526e47e` |
| Level 3 suite | `f4a2bbef-3b0a-4b7b-9c77-a4921c5745d2` |

---

## ⚠️ Environment Note (read before debugging a "password authentication failed" or ClickHouse error)

`.claude/settings.local.json` (personal, gitignored harness config) injects environment variables
into every shell command run through this tool, and **two of them shadow the repo's `.env` with
wrong values.** Since pydantic-settings prioritizes real environment variables over `.env` file
contents by design, both silently override the project config in any Bash-tool session. Neither was
touched — they're personal config, not project code — but if something fails despite `.env` looking
correct, check `env | grep -E "DATABASE_URL|CLICKHOUSE_PORT"` first.

1. **`DATABASE_URL`** has a different password than `.env` and caused ~15 minutes of confusing,
   intermittent Postgres auth failures on 2026-07-29 that had nothing to do with any code change.
   Independently, `.env`/`.env.example` were changed from `localhost` to `127.0.0.1` for
   `DATABASE_URL`'s host, since `localhost` can resolve to `::1` on a dual-stack Mac and Postgres's
   `pg_hba.conf` has separate rules per loopback address — that fix stands regardless of the
   harness-config issue.
2. **`CLICKHOUSE_PORT=8123`** (ClickHouse's HTTP port) instead of `.env`'s correct `9000` (the
   native protocol port `clickhouse_driver.Client` actually speaks). This has been silently breaking
   **every** `emit_trace()` and `emit_load_samples()` call all session, non-fatally by design (rule
   #4) — visible throughout this session's test output as
   `"[trace] write failed (non-fatal): ... Unexpected packet from server localhost:8123"`, which
   looked like routine, harmless ClickHouse flakiness until traced to its actual cause while
   verifying Phase 4.4's load-sample writes. The non-fatal design worked exactly as intended (no
   eval or load-test result was ever affected), but ClickHouse analytics have genuinely not been
   recording all session in any shell command run through this harness.

---

## Recent Changes

- **2026-07-29** — **Phase 4 Section 6 (Production Failure Mining) shipped — Phase 4 is now
  complete, all five novelty features built.** `mine_failures()` embeds every completed eval
  result's final assistant message across an agent's entire history (every suite, every version)
  and clusters via real **scikit-learn DBSCAN** on a precomputed cosine-distance matrix — chosen
  deliberately over a hand-rolled routine, since this is explicitly "the actual machine learning
  component of the platform." Significant clusters (large enough + correlated enough with bad
  outcomes) become `CandidateCase` rows with a generated `judge_rubric`, `pending` until a human
  approves or rejects; approval promotes one into a real `EvalCase` in an auto-created
  `mined-failures` suite. Found and fixed a real bug via the integration test: `mine_failures()`
  originally returned raw `FailureCluster` ORM objects (breaking the pure-result-type pattern every
  other Phase 4 engine follows), causing `DetachedInstanceError` once the session closed — fixed
  with a `MinedCluster` dataclass. Extracted `diff_engine.py`'s embedding helper into a shared
  `apps/api/services/embeddings.py` rather than writing a third copy for this feature, then
  re-verified `diff_engine`'s existing live tests still pass unchanged. Verified live: four
  genuinely different sentences expressing the same recurring failure were correctly clustered
  together by real embeddings, while three unrelated passing responses were correctly excluded;
  negative control on the bad-outcome-rate calculation caught and restored.
- **2026-07-29** — **Phase 4 Section 5 (Agent Load Testing) shipped.** `_compute_load_stats()`
  (pure — p50/p95/p99, error rate, cost/hour extrapolation, throughput), `run_load_test()` using
  real `ThreadPoolExecutor` concurrency (not asyncio — architectural rule #1 stays intact), new
  `load.requested` Redpanda topic + `load_worker.py`, `load_runs` Postgres table + `load_samples`
  ClickHouse table, `POST/GET /load-runs`, `agentbench load`. **Found and fixed a second real bug
  in existing infrastructure**: `RedpandaJobQueue.publish()` completely ignored its own `job_type`
  argument and always produced to `eval.requested` — never caught because every caller before this
  feature happened to pass exactly that value. Fixed with a small topic registry that now rejects
  an unregistered `job_type` loudly. Verified with real concurrent HTTP load against the reference
  agent (5 users produced far more than 5 requests in ~2s, confirming genuine concurrency, not
  sequential execution), 10,307 real ClickHouse samples confirmed by direct query, and a negative
  control on the percentile function. Also traced a second instance of the `.claude/settings.local.json`
  harness env-shadowing issue (`CLICKHOUSE_PORT=8123` vs `.env`'s correct `9000`), explaining every
  "[trace] write failed (non-fatal)" message seen all session — see the Environment Note above.
- **2026-07-29** — **Phase 4 Section 3 (Agent Chaos Engineering) shipped.** `ChaosAdapter`
  (5 fault modes across a total-failure family and a calls-through family), `RecoveryScorer`
  (deterministic core + optional `recovery_rubric`), `chaos:` block in suite YAML validated at
  push time. Corrected the "zero eval_engine.py changes" claim **before** writing code this time —
  worked through that `ChaosAdapter` must be built per-case, added a small honest
  `_build_case_adapter()` helper instead of discovering the gap via a failing test later. Documented
  explicitly, not left implicit: fault injection happens at the RedLine↔agent boundary, which is a
  real dependency for HTTP-deployed agents and a synthetic one for local Python agents, since
  reaching inside an agent's own tool-calling logic would require framework-specific instrumentation
  the black-box `AgentAdapter` design deliberately avoids. Verified concretely: the
  session-state-untouched claim for total-failure faults is proven by observing a real fixture
  agent's own embedded turn counter in the end-to-end test, not just asserted in isolated unit tests.
  Negative control: disabled the per-case chaos wrapping, watched half the end-to-end tests fail,
  restored, watched them pass.
- **2026-07-29** — **Phase 4 Section 2 (Behavioral Diff Engine) shipped.** `_classify_diff()`
  (pure, four quadrants), `compute_diff()`/`compute_diff_for_versions()`/`compute_diff_over_time()`
  in `diff_engine.py`, `behavior_diffs` table (migration 0006), `POST/GET /diff-runs`,
  `agentbench diff`, wired into the drift scheduler. Found a real design bug via the integration
  test (not a test-setup mistake): `agent_versions.UNIQUE(agent_id, content_hash)` makes
  `SILENT_DRIFT`/`NO_OP` structurally unreachable when comparing two different version IDs, since
  they're guaranteed to differ in hash. Fixed by splitting into a run-id-based primitive plus two
  purpose-specific wrappers — one for "was this version bump safe," one for "did this version drift
  on its own" (the real alarm, now what the scheduler calls). Verified the alarm case live against
  real Gemini embeddings with a fixture agent whose output is deliberately flipped between two runs
  of the same registered version, plus a negative control (hardcoded the change-detection flag to
  `False`, watched 5 tests fail, restored, watched them pass).
- **2026-07-29** — **Phase 4 Section 1 (ARS + SLO/error budget) shipped.** `SafetyScorer`
  (retrieval-groundedness, the missing ARS term), `_compute_ars()` and `compute_error_budget()` as
  pure functions, `slo_policies`/`ars_snapshots` tables (migration 0005), `GatePolicy.min_ars`, and
  the error-budget freeze wired into `gate_engine.evaluate()`. Verified end to end against real
  Postgres with a negative control proving the freeze mechanic actually fires. Found and fixed a
  real regression from the earlier Bug 3 fix (a stale `rag_agent.CHAT_MODEL` monkeypatch in
  `test_eval_end_to_end.py`), an `ars_snapshots` FK teardown gap in one integration fixture, and a
  genuine ungrounded-answer bug in the reference HTTP agent that `SafetyScorer` caught for real.
- **2026-07-29** — **Phase 3 complete.** All five sections (tenant scoping, `HTTPAdapter`, Redis
  rate limiter + daily quota, installable CLI, OSS scaffolding) shipped, each verified against real
  infrastructure (Postgres, Redis, Redpanda, ClickHouse, a live HTTP server, live Gemini) rather than
  mocks alone. 107 unit tests, 33+3 integration tests, all passing. Bugs 1, 3, 4, 5 closed; Bug 2
  carried forward; Bug 6 (Dockerfiles baking secrets) opened.
- **2026-07-29** — Phase plan corrected to match foundational document §13. Phase 3 reduced to a thin
  dependency-driven slice; Phase 4 is now the five novelty features; Tempo/async-v3/OIDC/registry
  deferred to Phase 5. ADR-005 (Helm as deployment interface, provider deferred) and ADR-006
  (frontend stack + deferred rewrite) added.
- **2026-07-24** — Phase 2 complete. Redpanda + Redis + ClickHouse + k3d + KEDA + OTel wired in.
- **2026-07-24** — `.claude/` folder created with audit/debug/refactor/test commands, hooks, rules, skills.
