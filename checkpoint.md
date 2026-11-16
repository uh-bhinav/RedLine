# RedLine — AgentBench Cloud
## Phase 1 and Phase 2 Checkpoint Document

**Repository:** `uh-bhinav/RedLine`  
**Date:** 2026-07-24  
**Purpose:** Complete engineering history, architecture reference, decision log, and recovery guide for Phase 1 and Phase 2.

---

## Table of Contents

1. [Project Philosophy and Origin](#1-project-philosophy-and-origin)
2. [Technology Stack](#2-technology-stack)
3. [Repository Structure](#3-repository-structure)
4. [Phase 1 — Core Eval Loop](#4-phase-1--core-eval-loop)
5. [Phase 2 — Real Distributed Engineering](#5-phase-2--real-distributed-engineering)
6. [Architecture Decision Records](#6-architecture-decision-records)
7. [Running the Full Stack](#7-running-the-full-stack)
8. [Seeded Data Reference](#8-seeded-data-reference)
9. [Known Open Items](#9-known-open-items)
10. [Where We Stand and What Comes Next](#10-where-we-stand-and-what-comes-next)

---

## 1. Project Philosophy and Origin

RedLine is an **agent reliability engineering platform** — the system you run your AI agents through before you trust them with real users. The name "AgentBench Cloud" is used in the foundational document. "RedLine" is the working project name.

The foundational insight driving the project: as LLM-powered agents move from demos to production, the industry lacks infrastructure for measuring, gating, and monitoring their reliability. RedLine fills that gap. It provides:

- An **eval engine** that runs scripted conversations against agents and scores them
- A **gate engine** that blocks bad agent versions from deployment
- A **CI integration** that hooks directly into GitHub pull request checks
- An **observability stack** for measuring drift, latency, cost, and behavior changes over time

The project is structured as a multi-phase build. Phase 1 proves the core loop on a monolith. Phase 2 turns it into real distributed infrastructure. Phase 3 (not yet started) makes it production-ready with multi-tenancy and full async.

Every decision made during development is held to a single standard from the foundational document: **would a principal engineer at a serious ML infrastructure company approve this?** This standard was invoked explicitly multiple times during Phase 1 and Phase 2 to reject shortcuts.

---

## 2. Technology Stack

| Layer | Technology | Version | Reason |
|---|---|---|---|
| Language | Python | 3.10 | LLM SDK compatibility, standard ML ecosystem |
| API framework | FastAPI | 0.115.6 | Async-compatible, native Pydantic, auto OpenAPI |
| ORM | SQLAlchemy | 2.0 | Synchronous mode (matches eval engine design) |
| DB migrations | Alembic | Latest | Standard SQLAlchemy migration tool |
| Primary DB | PostgreSQL | 16 | Relational metadata, SKIP LOCKED for job queue |
| Event bus | Redpanda | v26.1.11 | Kafka-compatible, no ZooKeeper, single binary |
| Cache / locks | Redis | 7 | Rate limiting, distributed locks, job status cache |
| Analytics DB | ClickHouse | 26.3 | Append-heavy trace/event data at scale |
| Container orchestration | Docker Compose + k3d | Latest | Infra on Compose, apps on k3d |
| Kubernetes packaging | Helm | 4.2.2 | Standard k8s packaging |
| Autoscaling | KEDA | Latest | Consumer-lag-based worker scaling |
| Kafka client | confluent-kafka | 2.14.2 | librdkafka-backed, synchronous, production-proven |
| LLM provider | Google Gemini | gemini-2.5-flash / gemini-2.0-flash | Available free tier, good capability |
| Embeddings | Google Gemini | gemini-embedding-001 | Same provider, no extra API key |
| Metrics | prometheus-client | 0.21.1 | Direct control, no version conflicts |
| Tracing | OpenTelemetry SDK | 1.34.1 | Standard tracing interface |
| Scheduling | APScheduler | 3.11.1 | BlockingScheduler for drift detection cron |
| CLI | Typer | 0.9.4 | Click-compatible, clean API |
| Auth tokens | python-jose | 3.3.0 | JWT issuance and verification |
| Password hashing | passlib[bcrypt] | 1.7.4 | Bcrypt, industry standard |

---

## 3. Repository Structure

```
RedLine/
├── agents/
│   ├── rag_agent/                    # Level 1 benchmark agent
│   │   ├── agent.py                  # run_turn() entrypoint
│   │   └── knowledge_base/docs/      # 3 markdown docs (12 chunks)
│   │       ├── refund_policy.md
│   │       ├── shipping_policy.md
│   │       └── product_faq.md
│   ├── stateful_support_agent/       # Level 3 benchmark agent
│   │   └── agent.py
│   └── research_pipeline_agent/      # Level 4 benchmark agent
│       └── agent.py
├── apps/
│   ├── api/                          # Shared library (models, core, services)
│   │   ├── core/
│   │   │   ├── auth.py               # JWT issuance + refresh rotation
│   │   │   ├── clickhouse_client.py  # ClickHouse connection + DDL + emit_trace()
│   │   │   ├── config.py             # Settings (pydantic-settings, .env)
│   │   │   ├── db.py                 # SQLAlchemy engine, Base, get_db
│   │   │   ├── jobqueue.py           # PostgresJobQueue (Phase 1 STABLE CONTRACT)
│   │   │   ├── llm_rate_limiter.py   # Provider-aware in-process rate limiter
│   │   │   ├── model_profiles.py     # Loads config/model_profiles.yaml
│   │   │   ├── redpanda_queue.py     # RedpandaJobQueue + RedpandaEvalWorker
│   │   │   ├── redis_client.py       # RateLimiter, DistributedLock, JobStatusCache
│   │   │   ├── security.py           # require_api_key, require_role, AuthContext
│   │   │   └── telemetry.py          # Prometheus metrics + OTel setup
│   │   ├── migrations/
│   │   │   └── versions/
│   │   │       ├── 0001_initial_schema.py
│   │   │       ├── 0002_add_entrypoint_col.py
│   │   │       ├── 0003_add_refresh_tokens.py
│   │   │       └── 0004_add_drift_tables.py
│   │   ├── models/
│   │   │   ├── agent.py              # Agent, AgentVersion
│   │   │   ├── api_key.py            # ApiKey
│   │   │   ├── drift.py              # DriftSnapshot, DriftAlert
│   │   │   ├── eval.py               # EvalSuite, EvalCase, EvalRun, EvalCaseResult
│   │   │   ├── gate.py               # GatePolicy
│   │   │   ├── job.py                # Job
│   │   │   ├── refresh_token.py      # RefreshToken
│   │   │   ├── tenant.py             # Tenant
│   │   │   └── user.py               # User
│   │   ├── routers/
│   │   │   ├── agents.py             # POST /agents, POST /agents/{id}/versions
│   │   │   ├── auth.py               # POST /auth/login, /auth/refresh, /auth/logout
│   │   │   ├── ci.py                 # POST /ci/check
│   │   │   ├── dashboard.py          # GET /dashboard/agents, /agents/{id}, /runs/{id}
│   │   │   ├── eval_runs.py          # POST /eval-runs, GET /eval-runs/{id}
│   │   │   └── eval_suites.py        # POST /eval-suites
│   │   ├── schemas/
│   │   │   ├── dashboard.py          # Dashboard response schemas
│   │   │   ├── eval_run.py           # EvalRunCreate, EvalRunResponse
│   │   │   └── eval_suite_yaml.py    # EvalSuiteYAML, EvalCaseDef
│   │   ├── scripts/
│   │   │   ├── create_api_key.py     # Generate + store API key
│   │   │   ├── init_clickhouse.py    # Create CH database + traces table
│   │   │   ├── init_topics.py        # Create Redpanda topics
│   │   │   ├── register_agent_version.py
│   │   │   ├── push_suite.py
│   │   │   └── seed.py               # Tenant, user, agent, API key
│   │   ├── services/
│   │   │   ├── adapters/
│   │   │   │   ├── base.py           # AgentAdapter Protocol, AgentTurnResult
│   │   │   │   └── local_python.py   # LocalPythonAdapter (importlib)
│   │   │   ├── drift/
│   │   │   │   ├── detector.py       # detect_model_drift() pure function
│   │   │   │   └── runner.py         # run_drift_check() DB-backed orchestrator
│   │   │   ├── eval_engine.py        # run_eval() — the core eval loop
│   │   │   ├── gate_engine.py        # _compute_gate_result() + evaluate()
│   │   │   └── scorers/
│   │   │       ├── base.py           # ScorerResult, Turn
│   │   │       ├── contains_match.py # ContainsMatchScorer
│   │   │       ├── cost.py           # CostScorer
│   │   │       ├── latency.py        # LatencyScorer
│   │   │       └── llm_judge.py      # LLMJudgeScorer
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_auth.py          # 10 tests
│   │   │   │   ├── test_content_hash.py  # 6 tests
│   │   │   │   ├── test_drift_detector.py # 11 tests
│   │   │   │   ├── test_gate_engine.py   # 12 tests
│   │   │   │   ├── test_local_python_adapter.py # 4 tests
│   │   │   │   └── test_scorers.py       # 15 tests
│   │   │   └── integration/
│   │   │       ├── test_eval_end_to_end.py
│   │   │       ├── test_worker_restart.py
│   │   │       └── test_jobqueue.py
│   │   ├── workers/
│   │   │   ├── drift_scheduler.py    # APScheduler, fires run_drift_check()
│   │   │   ├── eval_worker.py        # Phase 1 Postgres-based worker
│   │   │   └── eval_worker_v2.py     # Phase 2 Redpanda consumer worker
│   │   └── main.py                   # Monolith app (dev mode)
│   ├── eval_service/                 # Port 8001 — eval runs, CI
│   │   ├── main.py
│   │   └── Dockerfile
│   ├── agent_service/                # Port 8002 — agent registry, suites
│   │   ├── main.py
│   │   └── Dockerfile
│   ├── gate_service/                 # Port 8003 — gate policies, dashboard
│   │   ├── main.py
│   │   └── Dockerfile
│   └── cli/
│       ├── api_client.py             # httpx wrapper over RedLine API
│       ├── config.py                 # ~/.agentbench/config.toml
│       ├── main.py                   # Typer app, 6 commands
│       └── commands/
│           ├── ci_check.py           # agentbench ci-check (GitHub Actions only)
│           ├── github_api.py         # GitHub Check Run REST calls
│           ├── init.py               # agentbench init
│           ├── login.py              # agentbench login
│           ├── push_suite.py         # agentbench push-suite
│           ├── register_version.py   # agentbench register-version
│           └── run.py                # agentbench run
├── config/
│   └── model_profiles.yaml           # Provider/model/RPM profiles
├── docs/
│   ├── adr/
│   │   ├── ADR-001-kafka-client.md
│   │   ├── ADR-002-postgres-password.md
│   │   └── ADR-003-keda-autoscaling.md
│   └── ci-demo.md                    # GitHub CI demonstration record
├── eval-suites/
│   ├── rag-agent/
│   │   └── baseline.yaml             # 3 cases
│   ├── stateful-support-agent/
│   │   └── baseline.yaml             # 7 cases
│   └── research-pipeline-agent/
│       └── baseline.yaml             # 6 cases
├── helm/
│   └── redline/                      # Helm chart for k3d deployment
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── base/                 # namespace, configmap, secret, servicemonitor
│           ├── eval-service/         # deployment, service, hpa
│           ├── agent-service/        # deployment, service
│           ├── gate-service/         # deployment, service
│           ├── worker/               # deployment, scaledobject (KEDA)
│           └── gateway/              # deployment, service, ingress
├── infra/
│   ├── clickhouse-config.xml         # Memory caps for local M2 dev
│   ├── gateway.nginx.conf            # nginx reverse proxy config
│   └── redpanda-console-config.yml   # Redpanda Console broker config
├── apps/dashboard/                   # React frontend, port 5173
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── pages/
│   │       ├── AgentsList.jsx        # Page 1: agent table
│   │       ├── AgentDetail.jsx       # Page 2: version history + run list
│   │       └── RunDetail.jsx         # Page 3: gate banner + per-case results
│   └── vite.config.js
├── .github/workflows/
│   └── agentbench-check.yml          # GitHub Actions CI workflow
├── docker-compose.yml                # All infra + app services
├── Makefile                          # k3d deployment targets
├── pytest.ini                        # unit / integration markers
└── alembic.ini
```

---

## 4. Phase 1 — Core Eval Loop

Phase 1 goal: prove the core eval loop end-to-end on a single machine. Register an agent → push a suite → run eval → score → gate decision → block PR merge.

### 4.1 Database Schema (Migration 0001)

Ten tables in Postgres:

**`tenants`** — Top-level isolation unit. Every other row belongs to a tenant. Phase 1 seeds one tenant. Multi-tenancy enforcement is Phase 3.

**`users`** — Authenticated humans. Has `email`, `hashed_password`, `role` (admin/developer/viewer), `tenant_id`. Passwords are bcrypt-hashed via passlib.

**`api_keys`** — Long-lived machine credentials for CI and CLI. Stored as SHA256 hash (never the raw key). Has `role` for RBAC. Raw key shown once at creation, never again.

**`agents`** — Named agents belonging to a tenant. One row per agent (e.g. "rag-agent").

**`agent_versions`** — Immutable snapshots of an agent at a point in time. Has `version_label`, `model_name`, `content_hash` (SHA256 of the source file), `entrypoint` (importable Python path like `agents.rag_agent.agent:run_turn`).

**`eval_suites`** — Named collections of test cases for a specific agent.

**`eval_cases`** — Individual test cases. Has `case_key`, `turns` (JSON array of role/content pairs), `expectations` (JSON: contains, must_not_contain, judge_rubric, max_cost_usd, max_latency_ms).

**`eval_runs`** — One execution of a suite against an agent version. Tracks `status` (pending → running → completed/failed), `started_at`, `completed_at`, `triggered_by` (manual/ci).

**`eval_case_results`** — One row per case per run. Has `passed`, `metrics` (cost_usd, latency_ms), `transcript` (full conversation JSON), `scorer_results` (per-scorer pass/fail + detail JSON).

**`gate_policies`** — Threshold config per agent. `min_pass_rate` (default 0.90), `max_avg_cost_usd`, `max_avg_latency_ms`.

**`jobs`** — Job queue table. Used in Phase 1 for Postgres-based job dispatch. Retained in Phase 2 as audit trail.

### 4.2 The Eval Engine (`apps/api/services/eval_engine.py`)

The most important function in the codebase: `run_eval(eval_run_id)`.

**Flow:**
1. Load `EvalRun`, `AgentVersion`, `EvalCase` rows from Postgres
2. Set `eval_run.status = "running"`
3. Instantiate `LocalPythonAdapter(entrypoint)`
4. For each case:
   - Drive all turns through `adapter.run_turn(session_state, user_message)`
   - Run all scorers against the transcript
   - Write `EvalCaseResult` to Postgres
5. Set `eval_run.status = "completed"`
6. Emit ClickHouse trace events at each stage (Phase 2 addition)
7. Emit Prometheus metrics at completion (Phase 2 addition)

**Phase 2 additions:** OTel span wraps the entire run. Per-case spans capture `case_key` and `case_index`. `EVAL_RUNS_TOTAL`, `EVAL_CASE_RESULTS_TOTAL`, `EVAL_RUN_DURATION_SECONDS`, `EVAL_CASE_COST_USD` counters and histograms are updated.

### 4.3 The Adapter Layer

**`AgentAdapter` Protocol** (`services/adapters/base.py`): defines `run_turn(session_state, user_message) -> AgentTurnResult`. This is the contract every agent must satisfy.

**`LocalPythonAdapter`** (`services/adapters/local_python.py`): uses `importlib` to import the agent's module from its `entrypoint` string, then calls `run_turn`. This is how the eval engine invokes arbitrary agents without knowing anything about their internals.

**Why importlib instead of subprocess:** The decision was to run agents in-process rather than in subprocesses. Reason: lower latency, simpler state passing, and the `session_state` dict can be passed by reference across turns without serialization. Subprocess isolation is Phase 4 when untrusted third-party agents are supported.

### 4.4 The Gate Engine (`apps/api/services/gate_engine.py`)

**`_compute_gate_result(passed_count, total, avg_cost_usd, avg_latency_ms, min_pass_rate, max_avg_cost_usd, max_avg_latency_ms) -> GateResult`**

Pure function — no database, no side effects. Compares three thresholds:
- `pass_rate < min_pass_rate` → fail
- `avg_cost_usd > max_avg_cost_usd` (if configured) → fail
- `avg_latency_ms > max_avg_latency_ms` (if configured) → fail

The `evaluate(eval_run_id)` DB-backed wrapper loads case results and policy, then calls `_compute_gate_result`.

**Why the pure function separation:** Phase 2's Section 15 requirement was explicit unit tests for gate threshold logic without a DB. The `_compute_gate_result` extraction was the Phase 2 refactor that made this possible. 12 unit tests cover every threshold combination.

### 4.5 Scorers (`apps/api/services/scorers/`)

Four scorers run sequentially on every case. Earlier scorers can short-circuit expensive later ones (if `contains_match` fails, the LLM judge is still run — but a future optimization would skip it):

**`ContainsMatchScorer`**: checks `contains` strings are present and `must_not_contain` strings are absent in the final assistant message. Pure string matching, zero cost, zero latency.

**`CostScorer`**: sums `cost_usd` across all assistant turns, compares against `max_cost_usd` expectation. Only triggers if the expectation is set.

**`LatencyScorer`**: sums `latency_ms` across all assistant turns, compares against `max_latency_ms` expectation. Only triggers if the expectation is set.

**`LLMJudgeScorer`**: sends the full transcript and `judge_rubric` to Gemini and asks it to return `{"passed": true/false, "reason": "..."}`. The most expensive scorer. Only triggers if `judge_rubric` is set in expectations. Uses `gemini-2.5-flash` for judging regardless of what model the agent uses.

**Why LLM-as-judge:** Natural language behaviors (does the agent stay on topic? does it avoid hallucinating?) cannot be captured by string matching. The judge rubric is a human-written specification that gets evaluated by an LLM against the actual transcript. This is the industry-standard pattern (used by OpenAI Evals, LangSmith, etc.).

### 4.6 The RAG Agent (`agents/rag_agent/agent.py`)

Level 1 benchmark agent. Uses Gemini embeddings for retrieval and Gemini generation for answers. Serves a fictional company called "TrailLight Gear" with 3 policy documents (12 chunks total):

- `refund_policy.md` — 30-day return window, defect policy
- `shipping_policy.md` — standard/express shipping, international
- `product_faq.md` — warranty (2 years), sizing, care instructions

**`run_turn(session_state, user_message) -> AgentTurnResult`:**
1. Lazy-load and embed the knowledge base on first call
2. Embed the user query
3. Cosine similarity search against chunk embeddings
4. Keep chunks above `RELEVANCE_THRESHOLD = 0.60`
5. Generate answer with context in the prompt
6. Return `AgentTurnResult` with latency and cost

**Known issue:** Debug `print()` statements (`True`, PosixPath list, chunk dump) are still in `_load_chunks()`. These spam stdout on every eval run and should be removed before Phase 3.

### 4.7 Baseline Eval Suite (`eval-suites/rag-agent/baseline.yaml`)

Three cases, each testing a different failure mode:

- **`case_001_direct_answer`**: "How many days do I have to return an item?" → `contains: ["30 days"]`. Tests basic grounded retrieval. This case always passes.
- **`case_002_missing_context_honesty`**: "What is the CEO's personal phone number?" → `must_not_contain: ["+1", "phone:"]` + judge rubric requiring honest decline. Tests hallucination resistance. This case passes — the agent correctly declines.
- **`case_003_multiturn_followup`**: Two-turn conversation about international shipping. Judge rubric requires the second answer to directly address international shipping without repeating turn 1. This case **consistently fails** — the RAG agent's context handling across turns is insufficient. Pass rate: 2/3 = 0.67.

**Why 0.67 matters:** The gate threshold is 0.90. The 0.67 pass rate means the gate always fails for this agent. This is the correct behavior — `case_003` is a real behavioral failure, not a test artifact. This failure drives every downstream demonstration: the gate correctly blocks the PR, the drift detector correctly fires alerts, the dashboard correctly shows GATE FAILED.

### 4.8 Phase 1 Job Queue (`apps/api/core/jobqueue.py`)

**`PostgresJobQueue`** — implements the STABLE CONTRACT: `publish(tenant_id, job_type, payload) -> job_id` and `get_status(job_id) -> JobStatus`.

Uses `SELECT ... FOR UPDATE SKIP LOCKED` — a Postgres pattern that allows multiple workers to claim jobs without race conditions. When a worker claims a job row, it locks that row. Other workers trying to claim see the lock and skip to the next unclaimed row.

**Why SKIP LOCKED was the right Phase 1 choice:** It required zero additional infrastructure, worked correctly with the synchronous SQLAlchemy model, and was provably correct (no duplicate processing). The Phase 2 swap to Redpanda was possible without changing any calling code because the STABLE CONTRACT was locked in Phase 1.

### 4.9 The STABLE CONTRACT Decision

The single most important Phase 1 architectural decision. The `publish()` / `get_status()` interface was declared a STABLE CONTRACT: **any class implementing these two methods could be swapped in transparently**. This is why the Phase 2 migration to Redpanda required zero changes to the routers or any code that calls the queue — only the concrete implementation changed.

The `eval_runs` router always calls:
```python
queue = SomeJobQueue(db)
queue.publish(tenant_id, "eval.requested", {"eval_run_id": str(eval_run.id)})
```

In Phase 1: `SomeJobQueue = PostgresJobQueue`  
In Phase 2: `SomeJobQueue = RedpandaJobQueue`  
The calling code is identical.

### 4.10 The Eval Worker (`apps/api/workers/eval_worker.py`)

Phase 1 long-running process. Polls the Postgres `jobs` table every 2 seconds using `PostgresJobQueue.claim_next_job()`. When a job is claimed:
1. Marks job `status = in_progress`
2. Calls `eval_engine.run_eval(eval_run_id)`
3. Marks job `status = completed` or `status = failed`

**Run command:**
```bash
python -m apps.api.workers.eval_worker
```

**Expected output:**
```
eval_worker started, polling for job_type='eval.requested' every 2s
claimed job <job_id> (eval_run_id=<run_id>)
job <job_id> completed
```

### 4.11 The CLI (`apps/cli/`)

Six commands, all using `httpx` against the RedLine API. Never touches the database directly.

**`agentbench login`**: prompts for base URL and API key, hits `/health` to verify, saves to `~/.agentbench/config.toml` (permissions 0o600).

**`agentbench init`**: registers the agent via `POST /agents`, writes `agentbench.yaml` in the current directory with `agent_name`, `agent_id`, `entrypoint`, `api_base_url`.

**`agentbench push-suite <file>`**: reads YAML, calls `POST /eval-suites`, writes `suite_id` back to `agentbench.yaml`. Idempotent — if the suite already exists, updates cases in place.

**`agentbench register-version`**: computes `content_hash` by SHA256-hashing the agent's source file (found via `importlib`), calls `POST /agents/{id}/versions`, writes `version_id` back to `agentbench.yaml`.

**`agentbench run`**: reads `version_id` and `suite_id` from `agentbench.yaml`, calls `POST /eval-runs`, polls `GET /eval-runs/{id}` every 3 seconds until `status == completed`, prints gate verdict.

**`agentbench ci-check`**: used exclusively inside GitHub Actions. Creates a GitHub Check Run (requires `checks: write` permission in workflow), triggers eval, polls, updates the Check Run with the gate verdict, exits 0 (pass) or 1 (fail).

### 4.12 GitHub Actions Workflow (`.github/workflows/agentbench-check.yml`)

Triggers on `pull_request` targeting `main`. Key steps:
1. `agentbench login` — reads `REDLINE_BASE_URL` and `REDLINE_API_KEY` from repo secrets
2. `agentbench ci-check --agent rag-agent --suite baseline`

**The CI→API→Worker→Gate flow:**
1. Actions job calls `POST http://<ngrok-url>/ci/check`
2. API creates `EvalRun`, publishes job to Redpanda (or Postgres in Phase 1)
3. Worker claims job, runs `eval_engine.run_eval()`
4. Gate engine computes verdict
5. CLI polls until completion, updates GitHub Check Run, exits with gate result

**Branch protection:** `AgentBench Reliability Check` is a required status check on `main`. A PR with a failing gate cannot be merged. This was demonstrated on PR #2 (`uh-bhinav/RedLine`) where `case_003` failure blocked the merge. Screenshot/log evidence exists in `docs/ci-demo.md`.

### 4.13 Dashboard (`apps/dashboard/`)

React + Vite frontend, port 5173. Three pages:

**Page 1 — Agents list** (`/`): Table of all registered agents showing name, latest version label, last run ID (clickable), gate status (PASS/FAIL chip), completion timestamp. Calls `GET /dashboard/agents`.

**Page 2 — Agent detail** (`/agents/:id`): Version history table (label, model, entrypoint, content hash, registered date) and recent runs list (run ID, triggered by, gate status, failure reason, completed time). Calls `GET /dashboard/agents/:id`.

**Page 3 — Run detail** (`/runs/:id`): Full-width gate verdict banner (the signature design element — green GATE PASSED or red GATE FAILED with reasons), run metadata, per-case results table (case key, PASS/FAIL, latency, cost, scorer detail). The LLM judge's full reasoning text is visible in the scorer detail column. Calls `GET /dashboard/runs/:id`.

**Design direction:** Terminal-adjacent aesthetic. Dark navy background (`#0d1117`), IBM Plex Mono for data, status communicated by color only (green/red). No decorative chrome. The gate banner on the run detail page is the dominant element — a person with zero context can understand why a run failed without reading any code.

**Vite proxy:** Development proxy routes `/dashboard/*` and `/eval-runs/*` to `http://localhost:8000` so CORS is not needed during local dev.

### 4.14 Test Suite

```
pytest -m unit        → 37 unit tests, no DB, no LLM, < 2s
pytest -m integration → DB-dependent + LLM tests (need docker-compose up)
```

**Unit tests (no dependencies):**
- `test_local_python_adapter.py` — 4 tests: imports, run_turn interface, session state isolation, error handling
- `test_scorers.py` — 15 tests: all 4 scorers, edge cases (empty transcript, missing expectations, cost boundary)
- `test_gate_engine.py` — 12 tests: pass rate threshold, cost threshold, latency threshold, multiple violations, zero cases, exact-at-threshold
- `test_content_hash.py` — 6 tests: SHA256 determinism, uniqueness across entrypoints, 64-char hex format, error on bad entrypoint
- `test_auth.py` — 10 tests: JWT round-trip, expiry enforcement, tamper detection, wrong token type, RBAC allow/block
- `test_drift_detector.py` — 11 tests: stable rates, regression detection, improvement (no alert), threshold edge cases, single snapshot (insufficient data), baseline mean calculation

**Integration tests (need Postgres):**
- `test_jobqueue.py` — 2 tests: SKIP LOCKED prevents concurrent double-claim, restarted worker does not reclaim in-progress job
- `test_worker_restart.py` — 1 test: `test_worker_restart_does_not_duplicate_job` (explicitly named per Section 15 requirement)
- `test_eval_end_to_end.py` — 1 test: full pipeline against real DB + LLM (skips on 429)

---

## 5. Phase 2 — Real Distributed Engineering

Phase 2 goal: turn the Phase 1 monolith into a distributed system that is "architecturally real, not a toy, even if still running on your Mac."

### 5.1 Infrastructure (docker-compose.yml)

Nine containers total:

| Container | Image | Port | Role |
|---|---|---|---|
| `redline_postgres` | postgres:16-alpine | 5433 | Primary database |
| `redline_redis` | redis:7-alpine | 6379 | Rate limiting, locks, cache |
| `redline_redpanda` | redpandadata/redpanda:v26.1.11 | 19092 (ext Kafka) | Event bus |
| `redline_redpanda_console` | redpandadata/console:latest | 8080 | Redpanda web UI |
| `redline_clickhouse` | clickhouse/clickhouse-server:26.3 | 9000 (native), 8123 (HTTP) | Trace analytics |
| `redline_eval_service` | redline-eval_service:latest | 8001 | Eval runs + CI |
| `redline_agent_service` | redline-agent_service:latest | 8002 | Agent registry + suites |
| `redline_gate_service` | redline-gate_service:latest | 8003 | Gate policies + dashboard |
| `redline_gateway` | nginx:alpine | 8085 (docker) / 8000 (k3d) | Reverse proxy |

**Why Postgres is on port 5433, not 5432:** Your Mac already had PostgreSQL running on 5432 (likely from Homebrew). To avoid conflict, the Docker Postgres maps to 5433. The `DATABASE_URL` in `.env` uses 5433. This is documented in ADR-002.

**Why Redpanda on 19092 instead of 9092:** Port 9092 is the Redpanda internal broker port (within the Docker network). Port 19092 is the external Kafka API port mapped to your Mac. The Python clients (running on your Mac) connect to `localhost:19092`. Pods inside k3d connect to `host.k3d.internal:19092`.

**ClickHouse memory config (`infra/clickhouse-config.xml`):** Without limits, ClickHouse defaults to 80% of available RAM. On a 16GB M2, that's 12.8GB. The config caps it to 2GB for local dev. The `clickhouse-client` healthcheck uses `--password redline_dev` to authenticate.

### 5.2 Redis Integration (`apps/api/core/redis_client.py`)

Three distinct use cases, each in its own class:

**`RateLimiter`** — per-tenant sliding window using Redis sorted sets. Key: `rl:{tenant_id}`. Each request adds the current timestamp as a member. Old timestamps outside the 60s window are pruned on every check. Allows 100 requests per 60 seconds per tenant. Middleware in each service's `main.py` calls this before processing any request (excluding `/health` and `/metrics`).

**`DistributedLock`** — prevents duplicate job processing across multiple workers. Key: `lock:job:{job_id}`. Uses Redis `SET NX EX` (atomic set-if-not-exists with expiry). The eval worker acquires this lock before processing, releases it after. If a message is re-delivered by Redpanda (at-least-once semantics), the second worker sees the lock already held and skips the job.

**`JobStatusCache`** — `GET /eval-runs/{id}` reads Redis first, falls back to Postgres. Cache TTL: 30 seconds. Worker calls `invalidate()` when status changes, then `set()` with the new status. Completed runs are cached indefinitely (gate_result is immutable once computed).

**Verified:** `ZCARD rl:{uuid}` showed 6 after 6 authenticated requests, TTL = 26s remaining in the 60s window.

### 5.3 Redpanda Job Queue (`apps/api/core/redpanda_queue.py`)

Phase 2 swap behind the STABLE CONTRACT from Phase 1.

**`RedpandaJobQueue`** — same `publish()` / `get_status()` interface as `PostgresJobQueue`. `publish()` writes a Postgres job row (for audit), then produces a message to `eval.requested` topic. The message is partitioned by `tenant_id` (key), so one tenant's burst never delays another's jobs.

**`RedpandaEvalWorker`** — stateful consumer used by `eval_worker_v2.py`. Subscribes to `eval.requested` topic in consumer group `eval-worker`. Key differences from Phase 1:
- No polling loop — the broker pushes messages via the consumer protocol
- Offset committed **after** processing, never before (at-least-once delivery)
- `DistributedLock` prevents at-least-once re-delivery from causing duplicate processing

**Three Redpanda topics created by `python -m apps.api.scripts.init_topics`:**
- `eval.requested` — API publishes here; eval workers consume
- `eval.completed` — workers publish results (not yet consumed in Phase 2)
- `trace.emitted` — eval engine emits per-turn traces (TraceWorker in Phase 3)

**Why confluent-kafka over aiokafka:** The entire execution model is synchronous. The eval engine uses synchronous SQLAlchemy. The worker is a blocking poll loop. Mixing asyncio with the existing synchronous stack would require `asyncio.run()` inside a sync thread — overhead for zero benefit. `confluent-kafka` is backed by librdkafka, the same C library used in production Kafka deployments. See ADR-001.

### 5.4 ClickHouse Trace Store (`apps/api/core/clickhouse_client.py`)

**Schema (`traces` table):**
```sql
CREATE TABLE traces (
    trace_id     UUID,
    eval_run_id  UUID,
    tenant_id    UUID,
    event_type   String,   -- 'run_started' | 'turn_completed' | 'run_completed'
    case_key     String,
    turn_index   UInt8,
    latency_ms   UInt32,
    cost_usd     Float32,
    passed       Nullable(UInt8),
    detail       String,
    created_at   DateTime64(3, 'UTC')
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, eval_run_id, created_at)
```

**Three event types per eval run:**
- `run_started` — when `run_eval()` begins
- `turn_completed` — one per case, with latency, cost, and pass/fail
- `run_completed` — with final status

**Why ClickHouse and not Postgres for traces:** A single eval run emits ~5 events (3 cases + 2 lifecycle). At 1M runs/day, that's 5M rows/day of time-series data. Postgres would struggle with analytical queries across this volume (e.g. "average cost per case_key over the last 30 days"). ClickHouse's MergeTree engine is specifically designed for this pattern — columnar storage, partition pruning, ORDER BY for efficient range scans.

**`emit_trace()` is non-fatal by design.** A ClickHouse write failure catches the exception, logs it, and continues. A trace write must never fail an eval run.

**Verified:** After a completed eval run, ClickHouse shows:
```
run_started         | (no case data)
turn_completed      | case_001_direct_answer   | 1775ms | $0.000222 | passed=1
turn_completed      | case_002_missing_context | 484ms  | $0.00     | passed=1
turn_completed      | case_003_multiturn       | 3015ms | $0.000598 | passed=0
run_completed       | (no case data)
```

The partial run (from the 429 mid-eval) also appears in ClickHouse as a `run_started` + 1 `turn_completed` + `run_completed` — demonstrating that ClickHouse captures what actually happened, not just what was supposed to happen.

### 5.5 Service Decomposition (`apps/eval_service/`, `apps/agent_service/`, `apps/gate_service/`)

The monolith (`apps/api/main.py`) was split into three independently deployable services. Each is a FastAPI app with its own Dockerfile that imports the shared `apps/api/` library.

**The split rationale (Holy Grail §9.3):** "Policy/Gate logic changes far less often than Eval logic; you don't want to redeploy your entire backend every time you tweak an evaluation metric." The split maps to change frequency:
- `eval_service` changes most often (new scorers, adapter types, eval metrics)
- `agent_service` changes rarely (registry model is stable)
- `gate_service` changes least often (gate policy logic is deliberate and slow to change)

**Service-to-route mapping:**

| Service | Port | Routes owned |
|---|---|---|
| `eval_service` | 8001 | `POST /eval-runs`, `GET /eval-runs/{id}`, `POST /ci/check`, `POST /auth/*` |
| `agent_service` | 8002 | `POST /agents`, `POST /agents/{id}/versions`, `POST /eval-suites` |
| `gate_service` | 8003 | `GET /dashboard/agents`, `GET /dashboard/agents/{id}`, `GET /dashboard/runs/{id}` |

**nginx gateway (`infra/gateway.nginx.conf`):** Runs on port 8085 (docker-compose) or port 80 in k3d (mapped to 8000 externally). Routes by URL prefix:
```
/auth, /eval-runs, /ci → eval_service:8001
/agents, /eval-suites  → agent_service:8002
/dashboard             → gate_service:8003
/health                → inline nginx response (no service hit)
```

**Docker environment override:** Inside Docker containers, `localhost` refers to the container itself, not the host Mac. All three service containers override `DATABASE_URL` to use `postgres:5432` (Docker service name + internal port) instead of `localhost:5433`. Connection strings in `docker-compose.yml` under each service's `environment:` block.

**Healthchecks:** Use TCP socket check instead of HTTP because `python:3.10-slim` doesn't have `curl`:
```yaml
test: ["CMD-SHELL", "python3 -c 'import socket; s=socket.create_connection((\"localhost\",8001),2)'"]
```

**Verified:** All three services healthy (`1/1 Running`), `GET /dashboard/agents` through the nginx gateway returned the real `rag-agent` row.

### 5.6 Full Auth/RBAC (`apps/api/core/auth.py`, `apps/api/core/security.py`)

**Migration 0003** adds `refresh_tokens` table: `user_id`, `tenant_id`, `token_hash` (SHA256 of raw token), `role`, `expires_at`, `revoked_at`.

**Token pair design:**
- `access_token`: signed JWT, 15-minute expiry, verified in-memory (no DB hit per request)
- `refresh_token`: opaque 48-byte URL-safe random string, SHA256 hash stored in DB, 7-day expiry

**Refresh rotation:** On `POST /auth/refresh`, the old token is revoked (`revoked_at = now()`), a new pair is issued. If the same token is used twice (reuse detection), all sessions for that user are revoked immediately. This is the correct response to token theft — a legitimate client never reuses a refresh token.

**`require_api_key()`** (the auth dependency used on all endpoints): Accepts both credential types transparently. If the `Authorization: Bearer` value starts with `rl_live_`, it's treated as an API key (SHA256-hashed, looked up in `api_keys` table). Otherwise it's decoded as a JWT. Both resolve to `AuthContext(tenant_id, role, user_id?)`.

**`require_role(*allowed_roles)`**: RBAC factory function. Returns a FastAPI dependency that calls `require_api_key()` and then checks `ctx.role in allowed_roles`. Returns 403 if not. Used like: `Depends(require_role("admin", "developer"))`.

**Roles:** admin, developer, viewer. Currently seeded user is admin. Future enforcement per endpoint is Phase 3.

**Verified end-to-end:**
1. `POST /auth/login` with `admin@redline.local` / `ChangeMe123!` → returns JWT access token + refresh token
2. `GET /dashboard/agents` with JWT Bearer → returns `rag-agent` data
3. `POST /auth/refresh` with refresh token → returns new pair
4. Reuse old refresh token → `{"detail": "refresh token already used -- all sessions revoked"}`

### 5.7 k3d Kubernetes + Helm + KEDA

**Cluster creation:**
```bash
k3d cluster create redline \
  --port "8000:80@loadbalancer" \
  --agents 1
```

The `--port "8000:80@loadbalancer"` maps `localhost:8000` on your Mac to port 80 inside k3d. Traffic flows: `localhost:8000` → Traefik (k3d's built-in ingress controller) → Ingress → nginx gateway Service → nginx pod → service pods.

**`host.k3d.internal`** resolves to `192.168.65.254` inside k3d pods. This is the Docker Desktop bridge IP — the gateway to your Mac. All Postgres/Redis/Redpanda/ClickHouse connections from k3d pods use this hostname.

**Why infra stays in docker-compose:** StatefulSets in Kubernetes require PersistentVolumes, backup strategies, and careful upgrade procedures. Moving Postgres to k3d would be Phase 4 work. For Phase 2, docker-compose handles stateful infra; k3d handles stateless application services.

**Helm chart (`helm/redline/`):** Single chart for all application resources:
- `templates/base/`: `namespace.yaml`, `configmap.yaml` (non-secrets), `secret.yaml` (stringData — base64-encoded by k8s), `servicemonitor.yaml` (Prometheus scrape config)
- `templates/eval-service/`: `deployment.yaml`, `service.yaml` (named port `http`), `hpa.yaml` (CPU-based, enabled when `autoscaling.enabled=true`)
- `templates/agent-service/`, `templates/gate-service/`: `deployment.yaml`, `service.yaml`
- `templates/worker/`: `deployment.yaml` (no `replicas` field — KEDA owns it), `scaledobject.yaml`
- `templates/gateway/`: nginx ConfigMap + `deployment.yaml`, `service.yaml` + Ingress

**KEDA ScaledObject for the eval worker:**
```yaml
triggers:
  - type: kafka
    metadata:
      bootstrapServers: host.k3d.internal:19092
      consumerGroup: eval-worker
      topic: eval.requested
      lagThreshold: "5"
```
When consumer lag > 5, KEDA adds worker replicas. `cooldownPeriod: 300` (5 minutes) prevents scale-down mid-eval.

**CPU HPA for eval_service:** API pods scale on CPU (70% target, 1–4 replicas). CPU is the correct metric for the API service which is CPU-bound during request processing. CPU is the **wrong** metric for the eval worker which is I/O-bound (blocked on Gemini API calls).

**Verified helm-status output:**
```
eval-service                     HPA: cpu 1%/70%, 1→4 replicas
keda-hpa-eval-worker-scaledobject  KEDA: <unknown>/5 (avg), 1→8 replicas
```
The `<unknown>` for KEDA means no messages are currently in the queue (lag=0) — correct at idle.

**Makefile targets:**
```bash
make infra-up          # docker compose up -d
make cluster-up        # k3d cluster create (idempotent)
make images-build      # docker build for all 3 services
make images-import     # k3d image import (no registry needed)
make keda-install      # helm install kedacore/keda
make helm-install      # first install (includes keda-install)
make helm-upgrade      # upgrade existing release
make helm-status       # show pods, services, ingress, scaledobjects, HPAs
make monitoring-install # install kube-prometheus-stack + loki-stack
make logs              # kubectl logs -f for all redline pods
make deploy            # images-build + images-import + helm-upgrade
make teardown          # helm uninstall + cluster delete
```

**Known k3d issue:** The `eval-service` pod uses `host.k3d.internal:19092` for Redpanda per the ConfigMap, but the pod appears to be picking up `localhost:19092` from the baked-in `.env` file instead. The fix is to add `REDPANDA_BOOTSTRAP_SERVERS: "192.168.65.254:19092"` to the service's `environment:` block in `docker-compose.yml` (using the resolved IP rather than the hostname) and re-run `make helm-upgrade`. This is a pending fix.

### 5.8 Observability

**Three pillars (Holy Grail §10.11):**

**Metrics** — `prometheus-client` directly (not `prometheus-fastapi-instrumentator` due to a Starlette version conflict: the instrumentator 8.x requires starlette>=1.0.0 but fastapi 0.115.6 ships starlette 0.41.x). Each service exposes `/metrics` via a custom middleware + endpoint added by `setup_metrics(app, service_name)`.

HTTP metrics (per service):
- `redline_http_requests_total{service, method, path, status_code}` — Counter
- `redline_http_request_duration_seconds{service, method, path}` — Histogram

Eval business metrics (from eval_engine):
- `redline_eval_runs_total{status}` — Counter (completed/failed)
- `redline_eval_case_results_total{passed}` — Counter (true/false)
- `redline_eval_run_duration_seconds` — Histogram (1s to 300s buckets)
- `redline_eval_case_cost_usd` — Histogram ($0.0001 to $1 buckets)

Drift metrics (from drift runner):
- `redline_drift_check_runs_total{status}` — Counter (ok/error)
- `redline_drift_score_delta{agent_version_id, suite_id}` — Gauge (current delta from baseline)
- `redline_drift_alerts_total{drift_type}` — Counter (model/behavior/rag)

**Logs** — Structured JSON to stdout (`{"time":"...","level":"...","logger":"...","msg":"..."}`). Promtail collects pod stdout and ships to Loki. Queryable in Grafana.

**Traces** — OTel SDK with console exporter. Spans appear in pod logs as JSON objects with `trace_id`, `span_id`, parent relationship, start/end times, and attributes. Two spans per eval run: `eval_run` (top-level) and `eval_case` (one per case, child of `eval_run`). Phase 3 will replace the console exporter with OTLPSpanExporter pointing to Grafana Tempo.

**Prometheus + Grafana:** Installed via `kube-prometheus-stack` Helm chart in the `monitoring` namespace. ServiceMonitor with `port: "http"` (named port) tells Prometheus to scrape `/metrics` on all services with `app.kubernetes.io/instance: redline`. After fixing the named port issue (adding `name: http` to Service YAML), Prometheus shows 3 RedLine targets all `up`.

**Verified:** `redline_http_requests_total{method="POST",path="/eval-runs",service="eval-service",status_code="201"} 1.0` queryable from Prometheus API.

### 5.9 Drift Detection v0 (`apps/api/services/drift/`)

**Migration 0004** adds two tables:

**`drift_snapshots`** — one row per scheduled drift check run. `pass_rate`, `total_cases`, `passed_cases`, `avg_cost_usd`, `avg_latency_ms`. Indexed on `(agent_version_id, created_at)`.

**`drift_alerts`** — raised when a scheduled check detects a regression. `drift_type` (model/behavior/rag), `baseline_pass_rate`, `current_pass_rate`, `delta`, `threshold`, `detail` (human-readable explanation).

**`detect_model_drift(recent_pass_rates, threshold=0.10) -> DriftDetectionResult`** — pure function:
- Baseline = mean of all snapshots except the most recent
- Current = most recent snapshot
- Drift = `current - baseline <= -threshold` (regressions only; improvements do not alert)
- Requires ≥ 2 snapshots

**`run_drift_check()`** — DB-backed orchestrator:
1. Find all registered agent versions
2. For each, find the "baseline" suite
3. Trigger `run_eval()` synchronously
4. Save a `DriftSnapshot`
5. Query recent snapshots for this version + suite
6. Call `detect_model_drift()`
7. If drifted: save `DriftAlert`, emit `redline_drift_alerts_total.inc()`
8. Update `redline_drift_score_delta` Gauge

**`drift_scheduler.py`** — APScheduler `BlockingScheduler` in its own process:
- Default interval: 6 hours (`DRIFT_INTERVAL_HOURS` env var)
- Fires immediately on startup (`next_run_time=datetime.now()`)
- `coalesce=True` — if multiple fires were missed, run once not many
- `misfire_grace_time=300` — if a run is missed by <5 minutes, run it anyway

**Run command:**
```bash
DRIFT_INTERVAL_HOURS=0.0167 python -m apps.api.workers.drift_scheduler
```

**Threshold design:** 10 percentage points (0.10). Calibrated against the observation that LLM provider model updates rarely cause >5pp regressions on typical task suites, but genuine capability regressions tend to move scores 10–20pp. Catches real problems while tolerating normal LLM non-determinism.

**Verified:** After seeding 5 baseline snapshots at `pass_rate=0.90`, the scheduler ran a real eval (which scored 0.67 due to case_003), computed `delta = 0.667 - 0.900 = -0.233`, exceeded the 0.10 threshold, and wrote a `DriftAlert` with the full detail string:
```
pass_rate dropped from 0.900 (baseline over 5 runs) to 0.667 (delta=-0.233, threshold=0.100)
```

### 5.10 Model Profiles (`config/model_profiles.yaml`, `apps/api/core/model_profiles.py`)

**Decision origin (principal engineer review):** The original design asked "should we use gemini-2.0-flash or gemini-2.5-flash to avoid rate limits?" This was identified as a design smell. AgentBench benchmarks agent behavior, not provider quota. The platform must be provider-agnostic. The correct solution is a model profile system.

**`config/model_profiles.yaml`:**
```yaml
profiles:
  standard:
    provider: gemini
    chat_model: gemini-2.0-flash
    embedding_model: gemini-embedding-001
    rpm: 15
    max_tokens: 1024
  high_reasoning:
    provider: gemini
    chat_model: gemini-2.5-flash
    embedding_model: gemini-embedding-001
    rpm: 5
    max_tokens: 2048
  cheap:
    provider: gemini
    chat_model: gemini-2.0-flash-lite
    embedding_model: gemini-embedding-001
    rpm: 30
    max_tokens: 512
```

**`get_profile(name) -> ModelProfile`**: LRU-cached. Raises `KeyError` on unknown profile names. Used in agents: `PROFILE = get_profile("standard")`. No agent ever references a model name directly.

### 5.11 LLM Rate Limiter (`apps/api/core/llm_rate_limiter.py`)

**Decision origin (principal engineer review):** The original proposal was to choose a model based on quota. This was rejected. The correct architectural solution is a provider-aware rate limiter in the eval runner — the same way production systems handle provider limits.

**`LLMRateLimiter(rpm, window_seconds=60)`**: Thread-safe sliding window using a `deque` of monotonic timestamps. Before each LLM call: discard old timestamps, check if `len(timestamps) >= rpm`, sleep until a slot opens if so, record the new timestamp.

**`get_limiter(profile_name) -> LLMRateLimiter`**: Returns a singleton per profile. Agents call this once at module load time. Shared across all calls within one process.

**Why in-process, not Redis:** A single eval worker processes one job at a time, sequentially. In-process rate limiting is correct for this model. Redis rate limiting adds value only when multiple worker pods share a single provider API key quota — which is the Phase 3 multi-worker scenario.

### 5.12 Level 3 Agent — Stateful Customer Support (`agents/stateful_support_agent/`)

Level 3 difficulty: stateful multi-turn sessions with **structured memory extraction**. After every turn, the agent calls the LLM to extract entities, preferences, and constraints into `session_state["memory"]`. These are passed explicitly into subsequent prompts.

**Memory schema extracted per turn:**
```json
{"product": "...", "order_id": "...", "date": "...", "issue": "...", 
 "preference": "...", "constraint": "...", "correction": "..."}
```

**What makes it Level 3:** The failure modes being tested (entity recall, preference honoring, constraint memory, correction handling) cannot be tested with a single-turn agent. They require multi-turn conversation with explicit state tracking across turns.

**7 eval cases covering distinct failure categories:**
1. `entity_memory` — recalls product name across 3 turns
2. `preference_memory` — honors email-over-phone preference
3. `constraint_memory` — factors in missing packaging constraint
4. `correction_memory` — uses corrected value (18 months, not 3 years) in warranty check
5. `no_repeated_questions` — never asks for information user already provided
6. `context_accumulation` — holds 4 turns of context coherently
7. `topic_continuity` — resolves implicit references ("that same warranty")

### 5.13 Level 4 Agent — Multi-Agent Research Pipeline (`agents/research_pipeline_agent/`)

Level 4 difficulty: coordination failure testing across a 5-stage pipeline: `Planner → [Researcher A + Researcher B] → Verifier → Synthesizer`.

**Decision origin (principal engineer review):** The original Planner→Retriever→Synthesizer design was rejected because it "still mostly tests reasoning." The correct design for AgentBench is testing coordination failures — duplicate work, conflicting evidence, verifier rejection, unnecessary loops, cost explosion.

**Pipeline stages:**
1. **Planner**: decomposes the user question into exactly 2 distinct sub-queries (LLM call, JSON response)
2. **Researcher A**: answers sub-query 1 via RAG
3. **Researcher B**: answers sub-query 2 via RAG (sequential in Phase 2, logically independent)
4. **Verifier**: checks A and B for consistency, contradictions, gaps — returns `{"sufficient": true/false, "issues": "..."}`
5. **Synthesizer**: combines both into one coherent answer, acknowledges gaps if verifier flagged them

**5 LLM calls per case** (1 planner + 2 researchers + 1 verifier + 1 synthesizer). Plus embedding calls for retrieval.

**6 eval cases covering coordination failures:**
1. `basic_coordination` — compound question requiring both topics in the answer
2. `sub_query_distinctness` — planner must generate different sub-queries (not duplicates)
3. `synthesis_uses_both` — synthesizer must draw on both researchers
4. `verifier_catches_gaps` — CEO contact info not in KB, verifier should flag it
5. `cost_bounded` — 5-stage pipeline must not exceed $0.05 per case
6. `no_contradictions` — no conflicting numbers/facts in the final synthesis

### 5.14 Migrations Timeline

| Migration | Tables | Trigger |
|---|---|---|
| 0001 | tenants, users, api_keys, agents, agent_versions, eval_suites, eval_cases, eval_runs, eval_case_results, gate_policies | Phase 1 initial |
| 0002 | ALTER agent_versions ADD COLUMN entrypoint | entrypoint field missing from original schema |
| 0003 | refresh_tokens | Phase 2 Section 6 — JWT auth |
| 0004 | drift_snapshots, drift_alerts | Phase 2 Section 9 — drift detection |

---

## 6. Architecture Decision Records

### ADR-001: Use confluent-kafka as the Kafka/Redpanda client

**Decision:** `confluent-kafka==2.14.2`  
**Rejected:** `aiokafka`  
**Rationale:** The entire execution model is synchronous (eval engine, SQLAlchemy, worker loop). Mixing asyncio would require `asyncio.run()` inside sync threads — overhead for zero benefit. confluent-kafka is backed by librdkafka. The synchronous consumer model with horizontal scaling via consumer groups is the correct architecture for eval jobs (10–30s each, strong ordering requirements).  
**Review trigger:** Only if the worker becomes fully async OR if a single worker must multiplex large numbers of concurrent sub-second evaluations.

### ADR-002: Postgres password must match between volume and env vars

**Problem:** `POSTGRES_PASSWORD` in the container env only sets the password at **first volume initialization**. If the volume already existed with a different password, the env var is silently ignored — causing `scram-sha-256` auth failures with no obvious error message.  
**Fix applied:** `ALTER USER redline PASSWORD 'redline_dev_password'` inside the running container.  
**Rule:** `DATABASE_URL` in `.env` is the authoritative password. `POSTGRES_PASSWORD` in docker-compose must always match it. For fresh environments, `docker compose down -v` destroys volumes for clean re-initialization.

### ADR-003: Use KEDA for eval worker autoscaling on Redpanda consumer lag

**Decision:** KEDA `ScaledObject` with Kafka consumer lag trigger for the eval worker. CPU-based HPA for the stateless API services.  
**Rejected:** CPU HPA for the worker.  
**Rationale:** The eval worker spends ~95% of execution time blocked on Gemini API calls (network I/O). CPU stays below 10% even under heavy load. CPU HPA would never trigger regardless of queue depth. Consumer lag directly measures unprocessed work — when lag grows, add workers.  
**`cooldownPeriod: 300s`:** Prevents scale-down mid-eval. A removed worker pod causes the in-flight job's message to be re-delivered. 5-minute cooldown gives jobs time to complete.

### ADR-004 (implicit): Model profiles over provider-coupled rate limiting

**Decision:** Benchmarks declare `model_profile: standard`. The adapter resolves to a concrete model. No benchmark code references a model name.  
**Rejected:** Choosing a model based on quota availability.  
**Rationale:** AgentBench benchmarks agent behavior, not provider quota. If we chose gemini-2.0-flash because of quota, and the quota policy changed, we'd have changed the benchmark without changing the agent. The model profile system decouples benchmark semantics from infrastructure constraints.

### ADR-005 (implicit): In-process LLM rate limiter over model selection

**Decision:** `LLMRateLimiter(rpm)` in the eval runner, acquiring before every LLM call.  
**Rejected:** Choosing a model based on its RPM limit.  
**Rationale:** Infrastructure constraints (RPM limits) should be handled architecturally, not by changing the benchmark. The rate limiter reads RPM from the model profile — if the profile changes, the limiter adapts automatically.

---

## 7. Running the Full Stack

### 7.1 Required Terminals

For local development (not using k3d), you need 3 terminals simultaneously:

**Terminal 1 — Infrastructure:**
```bash
docker compose up -d
```
Starts all 9 containers. Wait until all show `healthy`.

**Terminal 2 — API Server (monolith dev mode):**
```bash
python -m uvicorn apps.api.main:app --port 8000
```
Do NOT use `--reload` when running long eval jobs. Reloading mid-run drops in-flight requests.

**Terminal 3 — Eval Worker:**
```bash
python -m apps.api.workers.eval_worker
```
Phase 1 Postgres-based worker. Works with local uvicorn.

OR for Phase 2 Redpanda worker (requires working Redpanda connectivity):
```bash
python -m apps.api.workers.eval_worker_v2
```

**Optional Terminal 4 — Drift Scheduler:**
```bash
DRIFT_INTERVAL_HOURS=6 python -m apps.api.workers.drift_scheduler
```

**Optional Terminal 5 — React Dashboard:**
```bash
cd apps/dashboard && npm run dev
```
Opens at `http://localhost:5173`.

### 7.2 First-Time Setup

```bash
# 1. Create the database schema
alembic upgrade head

# 2. Seed tenant, admin user, rag-agent, API key
python -m apps.api.scripts.seed

# 3. Get the API key (shown once)
python -m apps.api.scripts.create_api_key
export API_KEY="rl_live_<value>"

# 4. Initialize Redpanda topics
python -m apps.api.scripts.init_topics

# 5. Initialize ClickHouse schema
python -m apps.api.scripts.init_clickhouse

# 6. Register rag-agent and push baseline suite
python -m apps.cli.main login --base-url http://localhost:8000 --api-key "$API_KEY"
python -m apps.cli.main init --agent rag-agent --entrypoint agents.rag_agent.agent:run_turn
python -m apps.cli.main push-suite eval-suites/rag-agent/baseline.yaml
python -m apps.cli.main register-version --version-label v1 --model gemini-2.5-flash
```

### 7.3 Running an Eval

```bash
python -m apps.cli.main run --suite baseline
```

Expected output:
```
Eval run created: <uuid>
⠸ Running...
GATE FAILED  run=<uuid>
  ✗ pass_rate 0.67 is below required minimum 0.90
```

### 7.4 k3d Deployment

```bash
make infra-up          # docker-compose services
make cluster-up        # k3d cluster (already running)
make images-build      # build 3 service images
make images-import     # import into k3d
make keda-install      # install KEDA
make helm-install      # install Helm chart
make helm-status       # verify all pods running
```

Verify:
```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"redline-gateway","env":"k3d"}
```

### 7.5 Key Environment Variables (`.env`)

```
DATABASE_URL=postgresql+psycopg2://redline:redline_dev_password@localhost:5433/redline
POSTGRES_USER=redline
POSTGRES_PASSWORD=redline_dev_password
POSTGRES_DB=redline
JWT_SECRET_KEY=<long random string>
GEMINI_API_KEY=<your key>
REDIS_URL=redis://localhost:6379/0
REDPANDA_BOOTSTRAP_SERVERS=localhost:19092
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_DB=redline
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=redline_dev
```

---

## 8. Seeded Data Reference

| Item | Value |
|---|---|
| Tenant ID | `c1caeaf6-d6ab-4f93-99d8-25907cfebd6d` |
| Admin email | `admin@redline.local` |
| Admin password | `ChangeMe123!` |
| Admin role | admin |
| RAG agent ID | `b8003a26-f601-4c32-a4f3-7ac4fe502cad` |
| RAG agent version ID (v1) | `a259d9c5-9a89-4cbf-9060-edea9d29b325` |
| Baseline suite ID | `b2d571f2-d350-48fd-b485-7fc4273dc743` |
| Content hash (rag_agent v1) | `842a7a049760e678715704267b94307ce0812ba43b15dbb3127891849f9f5280` |
| Level 3 agent ID | `2e216305-6049-41ca-baba-456eb526e47e` |
| Level 3 suite ID | `f4a2bbef-3b0a-4b7b-9c77-a4921c5745d2` |

---

## 9. Known Open Items

These are real open items, not speculative. Each has a clear fix.

**1. Debug prints in `agents/rag_agent/agent.py`**  
`_load_chunks()` still has `print()` calls that output the PosixPath list, `True`, and chunk dump on every eval run. Remove these lines. They spam stdout in worker logs and GitHub Actions.

**2. k3d eval-service pod uses `localhost:19092` for Redpanda**  
The ConfigMap correctly has `host.k3d.internal:19092` but the pod appears to be reading `localhost:19092` from the `.env` baked into the Docker image. Fix: add explicit `REDPANDA_BOOTSTRAP_SERVERS: "192.168.65.254:19092"` to the eval_service `environment:` block in `docker-compose.yml` (and the corresponding section in Helm values.yaml). Then `make helm-upgrade`.

**3. Section 10 acceptance test pending**  
Level 3 and Level 4 agents are fully implemented and registered. Gate verdicts for both suites could not be captured due to Gemini free tier daily quota exhaustion. Run `python -m apps.cli.main run --suite stateful-support-agent-baseline` and `python -m apps.cli.main run --suite research-pipeline-agent-baseline` when quota resets (midnight Pacific).

**4. `eval_service` replica conflict**  
The `eval_service` HPA conflicts with KEDA if both try to manage replicas. Fix already applied: the Deployment YAML omits `spec.replicas` when `autoscaling.enabled=true`. Confirmed resolved after `make helm-upgrade`.

---

## 10. Where We Stand and What Comes Next

### Current State

RedLine Phase 1 and Phase 2 are architecturally complete and proven on a single machine (M2 Air, 16GB RAM). The platform can:

- Register agents, versions, and eval suites
- Run scripted multi-turn evaluations against any agent implementing `run_turn(session_state, user_message) -> AgentTurnResult`
- Score responses using 4 scorer types (string match, cost, latency, LLM judge)
- Gate agent versions against pass rate, cost, and latency thresholds
- Block GitHub PRs from merging when the gate fails (demonstrated on a real PR)
- Display eval history and gate verdicts in a React dashboard
- Publish eval jobs through Redpanda and process them with consumer-group-based workers
- Cache job status in Redis, enforce per-tenant rate limits, prevent duplicate processing with distributed locks
- Store per-turn trace events in ClickHouse for analytics
- Deploy application services to a local k3d Kubernetes cluster with KEDA-managed autoscaling
- Scrape Prometheus metrics from all services, collect structured logs in Loki
- Run scheduled drift checks and alert when agent behavior regresses beyond the configured threshold
- Resolve concrete model + RPM config from a named profile (no model names hardcoded in benchmarks)
- Rate-limit LLM API calls based on provider RPM limits declared in the model profile

### What Phase 3 Builds

Phase 3 moves from "architecturally real on your Mac" to "production-ready." The main areas:

**Proper multi-tenancy:** Per-tenant row-level security in Postgres, tenant-scoped Redpanda partitions (partition key is already `tenant_id`), per-tenant rate limit counters in Redis shared across worker pods (currently in-process).

**Grafana Tempo:** Replace OTel console exporter with `OTLPSpanExporter` pointing to Grafana Tempo. Full distributed trace queries across API → eval worker → LLM call as a single trace.

**True async workers:** Migrate eval engine to `AsyncSession` (SQLAlchemy async) + `aiokafka`. Enables concurrent case execution within a single worker pod — currently cases run sequentially.

**Google OIDC:** Replace email/password login with real OAuth2/OIDC. The token issuance, refresh rotation, and RBAC enforcement don't change — only the credential verification step swaps.

**Daily quota tracking:** Redis counter with 24h TTL per provider per project. The `LLMRateLimiter` currently handles per-minute throttling. A second layer for daily limits would prevent the free-tier daily exhaustion we hit in Section 10.

**Behavior drift + RAG drift:** Extend `drift/detector.py` beyond model drift. Behavior drift compares semantic similarity of responses across versions. RAG drift monitors retrieval quality (chunk scores, fallback rate).

**Reusable benchmark ecosystem:** The `agentbench run <suite-name>` format usable by others. Suite YAML as a published format, not just internal tooling.