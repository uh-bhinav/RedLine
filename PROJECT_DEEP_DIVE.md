# RedLine / AgentBench Cloud — Complete Project Deep Dive

**A study document for explaining this project in depth.**

Everything below is derived from the actual code in this repository. Where something is *not*
built, it is explicitly marked as such — so you never overclaim in an interview and get caught.

---

## Table of Contents

1. [The One-Paragraph Pitch](#1-the-one-paragraph-pitch)
2. [The Problem and the Thesis](#2-the-problem-and-the-thesis)
3. [Mental Model: One Eval Run, End to End](#3-mental-model-one-eval-run-end-to-end)
4. [Repository Layout](#4-repository-layout)
5. [Technology Stack — What and Why](#5-technology-stack--what-and-why)
6. [The Data Model](#6-the-data-model)
7. [The Three Stable Contracts (the architectural spine)](#7-the-three-stable-contracts-the-architectural-spine)
8. [The Eval Engine](#8-the-eval-engine)
9. [The Scorers](#9-the-scorers)
10. [The Gate Engine](#10-the-gate-engine)
11. [The Async Layer: Redpanda, Redis, Workers, DLQ](#11-the-async-layer-redpanda-redis-workers-dlq)
12. [The Five Differentiator Features (Phase 4)](#12-the-five-differentiator-features-phase-4)
13. [Drift Detection](#13-drift-detection)
14. [Security, Auth, and Multi-Tenancy](#14-security-auth-and-multi-tenancy)
15. [Service Decomposition, Gateway, Kubernetes, KEDA](#15-service-decomposition-gateway-kubernetes-keda)
16. [Observability](#16-observability)
17. [The CLI and the CI/CD Gate](#17-the-cli-and-the-cicd-gate)
18. [The Dashboard](#18-the-dashboard)
19. [The Benchmark Agents (Levels 1, 3, 4)](#19-the-benchmark-agents-levels-1-3-4)
20. [Testing Strategy](#20-testing-strategy)
21. [Recurring Design Principles](#21-recurring-design-principles)
22. [Real Difficulties Faced and How They Were Solved](#22-real-difficulties-faced-and-how-they-were-solved)
23. [What Is Genuinely Novel](#23-what-is-genuinely-novel)
24. [Honest Limitations](#24-honest-limitations)
25. [Numbers Worth Memorizing](#25-numbers-worth-memorizing)
26. [Likely Interview Questions with Answers](#26-likely-interview-questions-with-answers)
27. [Topics and Technologies to Read and Revise](#27-topics-and-technologies-to-read-and-revise)

---

## 1. The One-Paragraph Pitch

> RedLine is an **Agent Reliability Engineering** platform. It treats AI agents like production
> software systems that need real engineering discipline: versioned agents, declarative eval suites,
> automated scoring, and a **deployment gate that physically blocks a bad agent from merging** the
> same way a failing test blocks a bad commit. On top of that baseline it borrows five practices
> from Site Reliability Engineering that essentially no agent-eval tool implements: a composite
> **Agent Reliability Score** with an **SLO error budget**, a **behavioral diff engine** that detects
> silent model drift, **chaos engineering** for agents, **load testing** that measures cost-per-hour
> under concurrency, and **unsupervised failure mining** (DBSCAN over embeddings) that turns
> recurring production failures into candidate regression tests automatically.

The distribution is a Python monorepo: a FastAPI control plane decomposed into three services, a
Redpanda-backed async worker tier autoscaled by KEDA on consumer lag, Postgres for relational truth
plus ClickHouse for append-heavy traces, a React/TypeScript dashboard, and an installable
`agentbench` CLI that drives everything over HTTP and is what runs inside GitHub Actions.

---

## 2. The Problem and the Thesis

### The problem

An LLM *call* is a function you can unit test. An LLM *agent* is not:

1. **Non-deterministic** — the same input produces different outputs run to run.
2. **Multi-step** — an agent plans, calls tools, retrieves, and re-plans. A small error in step 1
   compounds by step 5.
3. **Stateful** — memory across turns is the whole point of an agent, and memory bugs (forgetting a
   constraint, ignoring a correction) are invisible to single-turn testing.
4. **Silently drifting** — a provider can swap the model underneath you. Your code did not change.
   Your `git diff` is empty. Your agent's behavior changed anyway.

Manual spot-checking cannot catch any of #2–#4 reliably. And crucially: existing tools observe, they
do not **enforce**.

### The thesis

| Category | Tools | What they answer |
|---|---|---|
| Observability | LangSmith, Langfuse | "What happened?" |
| Eval scoring | Braintrust, Promptfoo | "Did this score well?" |
| **RedLine** | — | **"Should this ship? No — and here's the blocked merge button."** |

RedLine's core claim is the **enforced gate**: a failing gate returns exit code 1 from
`agentbench ci-check`, which fails a required GitHub status check, which disables the merge button.
That is the difference between a dashboard and a control.

The second claim is that once you have a gate, you can put **SRE metrics** behind it — reliability
scores, error budgets, drift alarms, chaos survival, load-tested cost — instead of just "pass rate."

---

## 3. Mental Model: One Eval Run, End to End

This is the single most important thing to be able to narrate. Walk it top to bottom.

```
 developer / CI
      │  agentbench run --suite baseline
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. CLI (apps/cli)                                               │
│    reads ~/.agentbench/config.toml → base_url + api_key         │
│    reads ./agentbench.yaml        → version_id + suite_id       │
│    POST /eval-runs  (httpx, Bearer <api_key>)                   │
└─────────────────────────────────────────────────────────────────┘
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. eval_service :8001  (routers/eval_runs.py)                   │
│    require_tenant_role("admin","developer")  → AuthContext      │
│    INSERT eval_runs (status='pending', tenant from AUTH)        │
│    RedpandaJobQueue.publish(tenant_id,"eval.requested",{run_id})│
│      ├─ INSERT jobs row (audit trail)                           │
│      ├─ produce to topic `eval.requested`, KEY = tenant_id      │
│      ├─ flush(timeout=10) — bounded, raises if broker down      │
│      └─ warm Redis JobStatusCache                               │
│    return 201 {id, status:'pending'}   ← never blocks           │
└─────────────────────────────────────────────────────────────────┘
      ▼  (Redpanda partition assigned to a consumer in group `eval-worker`)
┌─────────────────────────────────────────────────────────────────┐
│ 3. eval_worker_v2  (KEDA-scaled pod / local process)            │
│    consume_one()  → ClaimedJob (offset NOT yet committed)       │
│    DistributedLock.acquire(job_id)  ← SET NX EX, dedupe         │
│    run_eval(eval_run_id)                                        │
│    commit_offset()   ← only AFTER success                       │
│    on exception: retry_or_dead_letter() then commit_offset()    │
└─────────────────────────────────────────────────────────────────┘
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. eval_engine.run_eval()   (services/eval_engine.py)           │
│    OTel span "eval_run"                                         │
│    load EvalRun, AgentVersion, EvalCases                        │
│    status='running'; emit_trace(run_started) → ClickHouse       │
│    adapter = build_adapter(agent_version.entrypoint)            │
│      "mod:fn" → LocalPythonAdapter | "http(s)://" → HTTPAdapter │
│    for each case:                                               │
│      case_adapter = ChaosAdapter(adapter,...) if case has chaos │
│      for each scripted user turn:                               │
│         adapter.run_turn(session_state, content) → AgentTurnResult│
│         append user + assistant Turn to transcript              │
│      for each scorer in _SCORERS (cheap → expensive):           │
│         ScorerResult(passed, detail)                            │
│      case passes iff ALL scorers passed                         │
│      INSERT eval_case_results (transcript + metrics + scorers)  │
│      Prometheus counters; emit_trace(turn_completed)            │
│    status='completed'; emit_trace(run_completed)                │
│    evaluate_ars(run_id) → persist ARSSnapshot  (non-fatal)      │
└─────────────────────────────────────────────────────────────────┘
      ▼  CLI polls GET /eval-runs/{id} every 3s
┌─────────────────────────────────────────────────────────────────┐
│ 5. gate_engine.evaluate(run_id)  — called on read, when done    │
│    aggregate pass_rate, avg_cost, avg_latency                   │
│    load GatePolicy (missing ⇒ min_pass_rate = 0.9, NOT auto-pass)│
│    read the persisted ARSSnapshot (read path, never recompute)  │
│    _compute_gate_result(...)   ← PURE function, no DB           │
│    + error-budget check across recent runs → can force a FAIL   │
│    → GateResult(passed: bool, reasons: [str])                   │
└─────────────────────────────────────────────────────────────────┘
      ▼
   CLI prints GATE PASSED / GATE FAILED + reasons
   in CI: updates the GitHub Check Run, exits 0 or 1 → merge blocked
```

**Five things to emphasize while narrating this:**

1. The POST **never blocks** — the API returns a `pending` row immediately; the work is a message.
2. The offset is committed **after** processing — at-least-once delivery, no silent job loss.
3. The engine only ever calls `adapter.run_turn(...)` — it does not know if the agent is local
   Python, a remote HTTP service, or chaos-wrapped.
4. Every threshold decision lives in a **pure function** so it is unit-testable with no infra.
5. Trace/metric writes are **non-fatal** — ClickHouse being down never fails an eval.

---

## 4. Repository Layout

```
apps/
  api/                     the control plane (all shared code lives here)
    core/                  config, db, security, auth, jobqueue, redpanda_queue,
                           redis_client, llm_rate_limiter, model_profiles,
                           clickhouse_client, telemetry
    models/                SQLAlchemy 2.0 ORM models (20 model classes)
    schemas/               Pydantic v2 request/response models
    routers/               FastAPI routers (agents, eval-suites, eval-runs, ci,
                           diff-runs, load-runs, mining, dashboard, auth)
    services/              eval_engine, gate_engine, ars_engine, diff_engine,
                           load_engine, embeddings, drift/, mining/,
                           scorers/, adapters/
    workers/               eval_worker_v2, load_worker, drift_scheduler, eval_worker (v1)
    migrations/            Alembic 0001 → 0010
    scripts/               seed, create_api_key, init_topics, init_clickhouse,
                           push_suite, register_agent_version, check_pytestmark
    tests/                 unit/ (218 tests) + integration/ (83 tests)
  eval_service/            FastAPI app :8001  — thin composition of routers
  agent_service/           FastAPI app :8002
  gate_service/            FastAPI app :8003
  cli/                     the installable `agentbench` CLI (HTTP only)
  dashboard/               React 18 + TypeScript + Vite + Tailwind + shadcn/ui
agents/                    the benchmark agents UNDER TEST (fixtures, not library code)
  rag_agent/               Level 1
  stateful_support_agent/  Level 3
  research_pipeline_agent/ Level 4
config/model_profiles.yaml the ONLY place a model name is written
eval-suites/               declarative YAML eval suites, one per benchmark agent
examples/http-agent/       reference implementation of the HTTP agent contract
helm/redline/              Helm chart: 3 services, 2 workers, gateway, KEDA ScaledObjects
infra/                     nginx gateway conf + Dockerfile, ClickHouse conf, Tempo conf
docs/                      ADRs, roadmap, status, proof-of-value, HTTP agent contract
.claude/                   architecture / coding / security rules the codebase is checked against
```

**Why `apps/api` holds everything while three services exist:** the services are *composition
roots*, not code silos. `apps/eval_service/main.py` is ~50 lines that mounts the routers it owns and
calls `setup_metrics()`. All the actual logic lives in `apps/api/`. This means service decomposition
cost almost nothing and can be reversed or re-cut without moving code — a deliberate choice for a
project at this stage.

---

## 5. Technology Stack — What and Why

Never say "I used X" without the "because". These are the actual reasons in this codebase.

### Language and runtime

| Tech | Version | Why |
|---|---|---|
| Python | 3.10 (pinned) | Whole ecosystem (LLM SDKs, sklearn, SQLAlchemy) is Python-first. Pinned at 3.10 so no 3.11+ feature (`tomllib`, `ExceptionGroup`, `except*`) sneaks in and breaks the CI runner. `tomli` is used instead of `tomllib`. |

### Web / API

| Tech | Version | Why |
|---|---|---|
| FastAPI | 0.115.6 | Async-capable ASGI, automatic OpenAPI generation (which the dashboard's TypeScript types are generated *from*), Pydantic-native validation, dependency injection — which is what makes `Depends(require_tenant_role("admin"))` a one-line, uniformly-applied auth rule. |
| Uvicorn | 0.32.1 | ASGI server. |
| Pydantic | v2 (2.12.5) | Request/response validation, and also used for internal value objects (`ScorerResult`, `AgentTurnResult`, `GateResult`). v2 only — `model_validate` / `model_dump`, never `from_orm` / `.dict()`. |
| pydantic-settings | 2.10.1 | 12-factor config: every setting comes from env/`.env`, never hardcoded. `get_settings()` is `@lru_cache`d. |

### Persistence

| Tech | Version | Why |
|---|---|---|
| PostgreSQL | 16 (port **5433**) | Relational source of truth. The data genuinely is relational (suite → case → run → case_result FK chains), it gives `SELECT ... FOR UPDATE SKIP LOCKED` for the v1 job queue, and gate decisions must be transactional. Port 5433 because 5432 is usually taken by a local Postgres. |
| SQLAlchemy | 2.0.36, **sync** | Modern 2.0 style: `Mapped[...]` + `mapped_column`, `select().where()` + `db.execute()`. Synchronous throughout — see the async decision below. |
| Alembic | 1.14.0 | Versioned migrations 0001→0010; every schema change is a reviewable file, not an ad-hoc ALTER. |
| ClickHouse | 26.3 | Column-store for the append-heavy, aggregate-only data: eval traces and load-test samples. A single load run can emit **10,000+** sample rows whose only queries are percentiles and error rates — that is ClickHouse's exact strength and Postgres's exact weakness. `MergeTree`, `PARTITION BY toYYYYMM(created_at)`, `ORDER BY (tenant_id, run_id, created_at)`. |
| Redis | 7 | Three *distinct* patterns, deliberately in three classes: sliding-window rate limiting (sorted set), distributed lock (`SET NX EX`), and a job-status cache. Also backs the cross-worker LLM rate limiter via an atomic Lua script. |
| PgBouncer | 1.25.2 (opt-in) | Connection pooling in front of Postgres, `POOL_MODE=transaction`. **Off by default** (`db_use_external_pooler=false`) because it changes the DB path for every service. When on, SQLAlchemy switches to `NullPool` — double-pooling would defeat the point. |

### Messaging

| Tech | Version | Why |
|---|---|---|
| Redpanda | v26.1.11 | Kafka-wire-compatible broker, single binary, no ZooKeeper/JVM — dramatically simpler to run locally than Kafka while keeping the exact same client, consumer-group, offset, and partition semantics (and the same KEDA scaler). |
| confluent-kafka | 2.14.2 | **ADR-001.** librdkafka C binding, synchronous. Chosen over `aiokafka` because the entire eval path is synchronous; mixing an asyncio event loop with synchronous SQLAlchemy Sessions and blocking LLM calls is a well-known deadlock/race trap. Also battle-tested rather than a pure-Python reimplementation. |

**Partitioning key = `tenant_id`.** One tenant's burst of 500 evals lands on their partitions and
does not starve another tenant's single job. That is noisy-neighbor protection expressed in one
line: `key=str(tenant_id).encode()`.

### LLM layer

| Tech | Why |
|---|---|
| `google-genai` 2.10.0 (Gemini) | Chat + embeddings. Structured output (`response_schema=JudgeVerdict`, `response_mime_type="application/json"`) is what makes the LLM judge return a typed `{passed, reasoning}` instead of prose to regex. `thinking_budget=0` + `temperature=0.0` for judge determinism and cost. |
| `config/model_profiles.yaml` | **The single place any model name is written.** Suites/agents say `model_profile: standard`; the profile resolves to `chat_model`, `embedding_model`, `rpm`, `daily_limit`, `max_tokens`. Swapping providers is a YAML edit. |
| Custom `LLMRateLimiter` | Redis sorted set + daily counter, coordinated across worker pods via a Lua script. See §22 for why. |

### ML

| Tech | Why |
|---|---|
| scikit-learn 1.7.2 — `DBSCAN` | Failure mining. Chosen over k-means because (a) you don't know the number of failure modes up front and DBSCAN doesn't require one, and (b) DBSCAN has a native *noise* label (`-1`) — k-means would force every unrelated response into some cluster. Run over a **precomputed cosine-distance matrix** (`metric="precomputed"`, `eps=0.15` ⇒ cluster at cosine similarity ≥ 0.85). |
| numpy 2.2.6 | Cosine similarity, vector normalization, distance matrix. |

### Container / orchestration

| Tech | Why |
|---|---|
| Docker Compose | The local dev plane: Postgres, PgBouncer, Redis, Redpanda (+ Console), ClickHouse, Tempo, the 3 services, and the nginx gateway. |
| nginx | API gateway on `:8085` (→ `:8000` in k3d). Routes each URL prefix to its owning service and serves the built dashboard SPA with an `try_files $uri /index.html` fallback. |
| k3d / Kubernetes | Local single-node k3s in Docker — real Kubernetes objects (Deployments, Services, HPA, Ingress) without a cloud bill. |
| Helm | **ADR-005.** The chart *is* the deployment interface. One `values.yaml` change, not a hand-edited manifest per environment. Cloud provider deliberately deferred; the chart is provider-agnostic. |
| KEDA | **ADR-003.** Autoscales the eval and load workers on **Redpanda consumer lag**, and can scale to **zero**. |
| Trivy + pip-audit | Image and dependency vulnerability scanning in `ci.yml`. |

### Observability

| Tech | Why |
|---|---|
| prometheus-client 0.21.1 | Metrics, used **directly** — `prometheus-fastapi-instrumentator` 8.x requires `starlette>=1.0` while FastAPI 0.115.6 pins `starlette 0.41.x`. Using the raw client avoids the conflict entirely and gives exact control over metric names/labels. |
| OpenTelemetry SDK 1.34.1 + OTLP gRPC exporter | Distributed traces (`eval_run` span → `eval_case` child spans) exported to **Grafana Tempo**, with `timeout=5` so an unreachable collector fails fast instead of hanging a worker. |
| Grafana Tempo 2.5.0 | Trace backend. |
| Loki / Promtail | Log aggregation; all logs are single-line JSON on stdout by design. |

### Frontend

| Tech | Why |
|---|---|
| React 18 + TypeScript + Vite | **ADR-006.** The v1 dashboard was 546 lines of plain JS with no auth; rewritten because Phase 4 added five new data surfaces. |
| TanStack Query v5 | Server-state caching, polling, invalidation — removes hand-rolled `useEffect` fetch/loading/error triads. |
| Tailwind + shadcn/ui + Radix | Accessible primitives, no heavy component-library lock-in. |
| Recharts | ARS trend charts, load-test latency charts. |
| `openapi-typescript` | **`make generate-types`** generates `api-types.ts` from the live FastAPI OpenAPI schema, and CI fails if the committed file drifts. A backend response-model change therefore breaks the **frontend build in CI** rather than silently breaking a user's browser. |
| Vitest + Testing Library | Frontend tests (`apiClient.test.ts`). |

### CLI

| Tech | Why |
|---|---|
| Typer 0.9.4 + Rich | Declarative commands, typed options, nice terminal output. |
| httpx | The CLI's **only** transport. |
| tomli / tomli-w | Reads/writes `~/.agentbench/config.toml` (chmod `0600`) and `agentbench.yaml`. |

**Packaging enforces the CLI boundary.** `pyproject.toml` declares base dependencies as the CLI's
*only* (typer, click, rich, httpx, tomli, tomli-w, PyYAML). Everything server-side lives in the
`[api]` extra. `packages = ["apps", "apps.cli", "apps.cli.commands"]` is explicit, not
auto-discovered. So if anyone adds `from apps.api...` to a CLI command, a clean
`pip install agentbench` breaks on a missing dependency — the architectural rule is enforced by
packaging, not by convention. There is even a `tests/unit/test_packaging.py` that fails when
`pyproject.toml` and `apps/api/requirements.txt` drift apart.

---

## 6. The Data Model

### Postgres — 20 model classes across 10 migrations

**Identity & tenancy**

| Table | Key columns | Notes |
|---|---|---|
| `tenants` | id, name | Every other table hangs off this. |
| `users` | email UNIQUE, hashed_password, role | Role ∈ {admin, developer, viewer}, CHECK-constrained at DB level. bcrypt via passlib. |
| `api_keys` | key_hash UNIQUE, role, revoked_at | Stores **only** `SHA256(raw)`; raw `rl_live_<token_urlsafe(32)>` shown once. |
| `refresh_tokens` | token_hash UNIQUE, expires_at, revoked_at | `secrets.token_urlsafe(48)`, hashed. Rotation + reuse detection. |

**Agent registry**

| Table | Key columns | Notes |
|---|---|---|
| `agents` | UNIQUE(tenant_id, name) | |
| `agent_versions` | version_label, model_name, **content_hash**, **entrypoint**, UNIQUE(agent_id, content_hash) | `content_hash = SHA256(source file bytes)`, 64 hex chars. The UNIQUE constraint is load-bearing for the diff engine — see §12.2. `entrypoint` is either `module.path:function` or an `http(s)://` URL, which is what selects the adapter with **no schema change** (migration 0002). |

**Eval core**

| Table | Key columns | Notes |
|---|---|---|
| `eval_suites` | UNIQUE(agent_id, name) | |
| `eval_cases` | case_key, `turns` JSONB, `expectations` JSONB | **Session-shaped from day one**: `turns` is a *list*, not one input/output pair. `expectations` is an open dict — a scorer only runs a real check if its key is present. |
| `eval_runs` | status, triggered_by, error, git_pr_number, github_check_run_id | status ∈ pending→running→completed/failed (CHECK). `error` added in 0009 so a failure has a readable reason. Index `(tenant_id, created_at)` added in 0010 — measured seq-scan → index-scan improvement recorded in `docs/explain-analyze-eval-runs-index.md`. |
| `eval_case_results` | passed, `metrics`, `transcript`, `scorer_results` (all JSONB) | The full transcript is stored — this is what the diff engine, mining engine, and dashboard transcript viewer all read later. |
| `gate_policies` | min_pass_rate (default 0.9), max_avg_cost_usd, max_avg_latency_ms, min_ars | UNIQUE(agent_id). NULL threshold = "no check for this dimension". |
| `jobs` | job_type, payload, status, result, error | Kept even after moving to Redpanda, as the audit/recovery record. |

**Phase 2+ / Phase 4 tables**

| Table | Migration | Purpose |
|---|---|---|
| `drift_snapshots`, `drift_alerts` | 0004 | Scheduled pass-rate history and drift alarms. |
| `slo_policies`, `ars_snapshots` | 0005 | Error-budget policy (target_ars, error_budget_pct, window_days) and per-run reliability score. `ars_snapshots.eval_run_id` is UNIQUE — one snapshot per run, updated not duplicated on re-compute. |
| `behavior_diffs` | 0006 | Append-only record of every diff comparison, incl. `per_case_similarity` JSONB and the 4-way `classification`. |
| `load_runs` | 0007 | Aggregate load-test result: p50/p95/p99, error_rate, total_cost_usd, cost_per_hour_usd, throughput_rps. |
| `failure_clusters`, `candidate_cases` | 0008 | Mined clusters and the human-approvable regression cases derived from them. |

### ClickHouse — 2 tables

```sql
traces(trace_id, eval_run_id, tenant_id, event_type, case_key, turn_index,
       latency_ms, cost_usd, passed Nullable(UInt8), detail, created_at)
  ENGINE = MergeTree PARTITION BY toYYYYMM(created_at)
  ORDER BY (tenant_id, eval_run_id, created_at)

load_samples(load_run_id, tenant_id, latency_ms, success, cost_usd,
             error_detail, created_at)
  ENGINE = MergeTree PARTITION BY toYYYYMM(created_at)
  ORDER BY (tenant_id, load_run_id, created_at)
```

The sort key starting with `tenant_id` is intentional: every real query is tenant-scoped, and
ClickHouse's primary index is the sort order.

`traces` is written per event (~20 rows per run); `load_samples` is **batch**-inserted (one INSERT
for thousands of rows) because a load test produces orders of magnitude more rows.

### The Postgres/ClickHouse split — how to justify it

- Postgres: **transactional, relational, mutable, source of truth for decisions.** A gate verdict
  must be consistent; a run's status transitions must be atomic.
- ClickHouse: **append-only, high-cardinality, analytic.** Never updated, never deleted, queried
  only with aggregations. Write failure is tolerable.
- The tolerance is codified: **`emit_trace()` must never raise.** Every call is wrapped; the handler
  logs and continues. An eval run's correctness depends only on Postgres and the LLM provider.

---

## 7. The Three Stable Contracts (the architectural spine)

If you remember one architectural idea from this project, remember this one. Three narrow interfaces
are declared **stable** — they may not gain required parameters, change return types, be renamed, or
become async. Everything else in the system is allowed to change behind them.

### Contract 1 — `AgentAdapter`

```python
class AgentAdapter(Protocol):
    def run_turn(self, session_state: dict, user_message: str) -> AgentTurnResult: ...

class AgentTurnResult(BaseModel):
    assistant_message: str
    tool_calls: list[ToolCall]
    latency_ms: int
    cost_usd: float
```

Four implementations satisfy it:

| Implementation | Selected by | What it does |
|---|---|---|
| `LocalPythonAdapter` | `entrypoint` looks like `module:function` | `importlib.import_module()` + `getattr` → calls **in-process**. Deliberately not `subprocess`: `session_state` is passed by reference, so an agent can keep arbitrary Python objects (graph state, history lists) across turns with no wire protocol. |
| `HTTPAdapter` | `entrypoint` starts with `http(s)://` | POSTs `{session_state, user_message}`, expects `{assistant_message, session_state?, tool_calls?, cost_usd?}`. |
| `ChaosAdapter` | wraps whichever of the above was built, per-case | Fault injection as a **decorator** over the contract. |
| (test fixtures) | | Dummy agents in `tests/unit/fixtures/`. |

`build_adapter(entrypoint)` is the **one** place that decides. Adding HTTP support required **zero
schema migration and zero eval-engine change** — the shape of an existing string column is the
selector.

Two details worth calling out because they show real thinking:

- **HTTPAdapter latency** is the *observed round trip*, not what the agent self-reports. The latency
  gate should assert what a user experiences, and an agent's self-reported internal latency is
  always the smaller, less honest number.
- **HTTPAdapter retries only where the request provably never arrived**: `ConnectError`,
  `ConnectTimeout`, and 502/503/504. It deliberately does **not** retry `ReadTimeout` — the request
  was sent and may have been processed, so retrying could double-execute a side effect (a refund, an
  email). The platform must not cause the class of incident it exists to catch.
- **Session state over HTTP**: an HTTP agent can't mutate our dict, so it returns its new state and
  the adapter writes it back **in place** (`clear()` + `update()`, never rebinding) — because the
  eval engine holds a reference across turns.

### Contract 2 — `JobQueue`

```python
class JobQueue(Protocol):
    def publish(self, tenant_id: UUID, job_type: str, payload: dict) -> UUID: ...
    def get_status(self, job_id: UUID) -> JobStatus: ...
```

Two implementations: `PostgresJobQueue` (Phase 1, `SKIP LOCKED` polling) and `RedpandaJobQueue`
(Phase 2, Kafka producer + Redis-cached status). **The entire transport swap — Postgres table →
distributed log — touched zero router code and zero eval-engine code.** That is the payoff of
declaring the seam before you need it.

### Contract 3 — `Scorer`

```python
class Scorer(Protocol):
    def score(self, case: EvalCase, transcript: list[Turn]) -> ScorerResult: ...

class ScorerResult(BaseModel):
    passed: bool
    detail: str        # human-readable WHY — never just a bool
```

Six implementations. A scorer never returns a raw bool or dict — the `detail` string is what a
developer reads in the dashboard and what makes a failed gate actionable.

---

## 8. The Eval Engine

`apps/api/services/eval_engine.py` — ~250 lines, synchronous, the heart of the system.

```python
_SCORERS = [ContainsMatchScorer(), CostScorer(), LatencyScorer(),
            SafetyScorer(), RecoveryScorer(), LLMJudgeScorer()]
```

**Scorer ordering is a cost decision.** Cheap deterministic scorers run first, the LLM-calling judge
runs last, so an obviously-broken case fails before spending money and latency on a judge call.
`SafetyScorer` and `RecoveryScorer` are also no-LLM unless a case opts into a rubric, so they sit
with the cheap ones.

**Case execution** (`_run_case`):
1. Fresh `session_state = {}` per case (isolation between cases).
2. For each scripted user turn: append the user `Turn`, call `adapter.run_turn(...)`, append the
   assistant `Turn` with `tool_calls`, `latency_ms`, `cost_usd`.
3. Run *every* scorer. A case passes iff **all** scorers pass (`overall_passed`).
4. All six scorer results are stored, not just the failing one — so you can see that the answer was
   correct but too expensive.

**Metrics** are summed across all assistant turns, not just the last one — a multi-turn case's cost
is the cost of the whole session.

**Failure path (worth studying — two real bugs were fixed here):**

```python
except Exception as exc:
    db.rollback()
    failed_run.status = "failed"
    failed_run.error = f"{type(exc).__name__}: {exc}"[:2000]   # truncated defensively
    span.record_exception(exc)          # was: bare Exception() — threw away the diagnostic
    emit_trace(..., tenant_id=failed_run.tenant_id, ...)  # was: uuid.uuid4()
```

The second one is subtle and a great story: failure traces were being stamped with a **random**
tenant id. Since the ClickHouse table is `ORDER BY (tenant_id, eval_run_id, created_at)`, every
failed run was invisible to any per-tenant query — and failures are the one thing you'd look for.

**ARS is computed here, at completion**, not inside the gate — because `gate_engine.evaluate()` runs
on every dashboard page load, and a read path must never be a write path.

---

## 9. The Scorers

| Scorer | Config key(s) | LLM? | What it does |
|---|---|---|---|
| `ContainsMatchScorer` | `contains`, `must_not_contain` | No | Case-insensitive substring check over concatenated assistant text. Case-insensitive deliberately — failing on "30 Days" vs "30 days" is a false negative, not a real failure. |
| `CostScorer` | `max_cost_usd` | No | Sums `cost_usd` over assistant turns. |
| `LatencyScorer` | `max_latency_ms` | No | Sums `latency_ms` over assistant turns. |
| `SafetyScorer` | always-on groundedness + optional `safety_rubric` | Only if rubric | See below. |
| `RecoveryScorer` | auto (chaos marker) + optional `recovery_rubric` | Only if rubric | See below. |
| `LLMJudgeScorer` | `judge_rubric` | Yes | Gemini with structured output. |

**A scorer with no configured key returns `passed=True` with a "not configured" detail.** So
`expectations` is genuinely declarative — you opt into checks per case.

### SafetyScorer — the interesting one

ARS needs a *safety* term. Inventing a number would be dishonest, so this scorer makes safety
concrete via **retrieval groundedness**, always on, no LLM call:

> If a turn made a **retrieval-shaped** tool call (name contains `retriev`/`search`/`lookup`/
> `knowledge_base`/`kb_`/`query_docs`/`rag`) and **every** such call came back empty, then the
> assistant's answer for that turn must contain an honesty signal ("I don't know", "couldn't find",
> …). Otherwise it is a hallucination-without-grounding — a specific, checkable claim.

Scoping matters: it only applies to *retrieval-shaped* tools, because an empty result from an
inventory or calculator tool is legitimate data, not missing context.

What it **deliberately does not do**: generic prompt-injection detection. A keyword heuristic would
either miss real injections or flag legitimate content, giving false confidence either way. The
honest way to test that is Chaos + RecoveryScorer, with a real controlled fault.

### RecoveryScorer

Runs only when the transcript contains the reserved chaos marker tool call (`__chaos_fault__`).
Its deterministic bar is deliberately minimal and defensible: **after the last faulted turn, every
subsequent assistant turn must be non-empty** — i.e. the session kept functioning instead of
cascading into silence. Judging whether the agent recovered *gracefully* requires real judgment
(a short confident answer is sometimes correct and sometimes a hallucinated continuation), so that
is the optional `recovery_rubric` escape hatch, not a keyword guess.

### LLMJudgeScorer

- Uses the **`high_reasoning`** profile, always — grading correctness is a harder reasoning task
  than the call being graded, and a weak judge is worse than a slow one.
- `response_schema=JudgeVerdict` (flat, because nested Pydantic response schemas hit a known
  `$ref`/`$defs` bug in google-genai), `temperature=0.0`, `thinking_budget=0`.
- Prompt explicitly instructs strictness: *"do not be lenient, and do not assume good intent if the
  transcript doesn't actually satisfy the rubric."*
- Calls `get_limiter("high_reasoning").acquire()` first. **This was a real bug** — the judge used to
  make an entirely unmetered LLM call on every rubric case (see §22).

---

## 10. The Gate Engine

Two functions, and the split is the whole point.

```python
def _compute_gate_result(passed_count, total, avg_cost_usd, avg_latency_ms,
                         min_pass_rate, max_avg_cost_usd, max_avg_latency_ms,
                         ars=None, min_ars=None) -> GateResult:
```

**Pure.** No DB session, no Redis, no file I/O, no network, and it never raises — a bad input
produces a failed `GateResult`, not an exception. That purity is why 17 unit tests exercise it in
under 100 ms with zero infrastructure running.

`evaluate(eval_run_id)` is the DB-backed wrapper: aggregate case results → load `GatePolicy` → read
the already-persisted `ARSSnapshot` → call the pure function → then apply the error-budget check.

Three rules encoded here that are worth quoting verbatim in an interview:

1. **A missing policy never auto-passes.** No `GatePolicy` row ⇒ `min_pass_rate = 0.9`. "Nobody
   configured a gate" must not silently mean "anything goes."
2. **A missing optional threshold means "skip that check"**, consistently across
   `max_avg_cost_usd`, `max_avg_latency_ms`, and `min_ars`.
3. **The error-budget check is intentionally *outside* the pure function**, because it is a
   statement about the recent *past*, not about this run's own numbers. An exhausted budget fails
   the gate **regardless of how well this run scored** — that is exactly what distinguishes an error
   budget from a per-run threshold.

`GateResult` carries `reasons: list[str]` — human-readable, one per violated threshold, e.g.
`"pass_rate 0.67 is below required minimum 0.90"`. Those strings are what land in the GitHub Check
Run a developer actually reads.

---

## 11. The Async Layer: Redpanda, Redis, Workers, DLQ

### Producer side (`RedpandaJobQueue.publish`)

1. INSERT a `jobs` row first (audit trail survives even if publish fails).
2. Produce to the topic resolved from `job_type` via `_KNOWN_TOPICS`, with `key = tenant_id`.
3. `acks="all"`, `retries=3`, `retry.backoff.ms=200`.
4. **`flush(timeout=10)` and raise if anything is undelivered.** A bare `flush()` blocks forever when
   the broker is unreachable, which surfaces to a user as an API request that simply never returns.
   Failing loudly after 10 s is the difference between a debuggable error and a hung request.
5. Warm the Redis `JobStatusCache` so the caller's first poll is instant.

### Consumer side (`RedpandaEvalWorker` + `eval_worker_v2`)

- `enable.auto.commit = False`, `auto.offset.reset = earliest`.
- `consume_one()` → process → `commit_offset()`. Committing **after** processing gives
  **at-least-once** delivery: a worker crash mid-run causes re-delivery rather than silent loss.
- At-least-once implies possible duplicates, so `DistributedLock` (Redis `SET NX EX`, TTL 600 s for
  eval / 1800 s for load) guards it: a re-delivered message whose lock is held is skipped and its
  offset committed.
- Consumer group = `eval-worker`. The broker assigns partitions; N worker pods share load with
  **zero coordination code**. That is the reason to use a log instead of a table.

### Dead-letter queue (Phase 5.1)

Every message carries a `retry_count` in its envelope. On failure:

```
retry_count + 1 <= max_job_retries (3)  →  republish to the SAME topic, retry_count+1
otherwise                                →  publish to <topic>.dead-letter with final_error
either way                               →  commit_offset() on the ORIGINAL message
```

The subtle bit, and it's explicitly documented in the code: the retry is a **new message appended to
the tail**, not a redelivery. Committing the original offset is what prevents Redpanda from
redelivering the same message forever; the retry envelope is what gives a transient failure another
chance.

### `load_worker.py`

Structurally identical, different topic (`load.requested`), different consumer group
(`load-worker`), different engine. This is what makes "separate worker pools by resource profile"
real rather than organizational: a load runner holds many concurrent outbound connections while an
eval worker spends ~95% of its time blocked on one LLM call. They get their own KEDA ScaledObject
and their own resource requests/limits.

---

## 12. The Five Differentiator Features (Phase 4)

These are what separate RedLine from an eval-and-observability clone. Each follows the same
discipline: **a pure function you can unit test with plain data, plus a DB-backed orchestrator.**

### 12.1 Agent Reliability Score (ARS) + SLO error budget

```
ARS = 0.4·correctness + 0.2·safety + 0.2·latency + 0.2·cost
```

Each sub-score is `passed / total` for the scorer(s) measuring that dimension:

| Sub-score | Source |
|---|---|
| correctness | `ContainsMatchScorer` **AND** `LLMJudgeScorer` both passed |
| safety | `SafetyScorer` passed |
| latency | `LatencyScorer` passed |
| cost | `CostScorer` passed |

Two honest design notes:

- Sub-scores reuse the existing pass/fail thresholds rather than inventing a new continuous curve
  per dimension ("how good is 3400 ms against a 5000 ms budget?") that the platform doesn't use
  anywhere else.
- A scorer **missing** from `scorer_results` counts as **not passed**, not "not applicable" —
  silently treating missing data as success would inflate the ARS of old runs.

Weights are fixed, not per-agent. A single formula is what makes ARS comparable across agents at
all; per-agent weighting is a product decision, not a code one.

**The error budget** is the SRE mechanic, applied to ARS instead of uptime:

```python
breaches   = count(run.ars < target_ars)   over the last `window_days`
breach_rate = breaches / window_size
exhausted   = breach_rate > error_budget_pct
```

Defaults: `target_ars=0.9`, `error_budget_pct=0.1`, `window_days=7`. If exhausted,
`gate_engine.evaluate()` appends `"error budget exhausted: ..."` and forces `passed=False` — a
**perfect-scoring run still fails the gate** if recent history burned the budget. That is
deployment freeze, and it is the single most SRE-native thing in the codebase.

### 12.2 Behavioral Diff Engine — catching *silent drift*

`git diff` shows that code changed. It says nothing about whether **behavior** changed. And the more
dangerous direction: a provider silently upgrades the model under an agent with **zero** code
changes, and no code review on earth catches that.

Take two completed runs of the same suite. For each `case_key` present in both, embed the final
assistant message from each and take cosine similarity. Mean similarity < 0.90 ⇒ behavior changed.
Cross that with whether `content_hash` differs:

|  | code same | code changed |
|---|---|---|
| **behavior same** | `NO_OP` | `SAFE_REFACTOR` |
| **behavior changed** | **`SILENT_DRIFT`** ⚠️ | `EXPECTED_CHANGE` |

(Plus `INSUFFICIENT_DATA` when no `case_key` is shared.)

**The insight that makes this actually work** — and this is a genuinely good interview answer:

> `agent_versions` has `UNIQUE(agent_id, content_hash)`. So two *different* AgentVersion rows are
> **guaranteed** to have different content hashes. If `compute_diff` took two version ids,
> `code_changed` would be `True` on literally every call — making `SILENT_DRIFT` and `NO_OP`
> **structurally unreachable**, not merely rare.
>
> So the primitive takes two **eval run ids**, not two version ids. That is what allows comparing
> the *same* version against *itself* across two points in time — the only way "code did not change"
> is representable in this schema, and exactly what a real silent-drift event looks like.

Three entry points sit on that one primitive:
- `compute_diff(run_a, run_b)` — the primitive.
- `compute_diff_for_versions(...)` — "was this version bump safe?" (only reaches SAFE_REFACTOR /
  EXPECTED_CHANGE, correctly).
- `compute_diff_over_time(version, suite)` — same version, two most recent runs → only reaches
  NO_OP / **SILENT_DRIFT**. This is what the drift scheduler calls automatically.

Guards: both runs must target the same suite (otherwise you're comparing answers to different
questions), both must be `completed`, both versions must belong to the same agent.

The `0.90` threshold is documented honestly as a **starting default, not empirically calibrated** —
there is no labeled corpus of "safe paraphrase" vs "genuinely different answer" version pairs yet.

### 12.3 Chaos Engineering for agents

Netflix's Chaos Monkey proved that deliberately breaking things in a controlled way is the only
honest way to know a system is resilient. Agents depend on tools, retrieval, memory, and a model
call — all of which fail constantly in production, and almost nobody tests the agent's reaction.

`ChaosAdapter` wraps any adapter and satisfies the same Protocol, so the eval engine cannot tell the
difference. Five fault modes in two families:

| Family | Modes | Behavior |
|---|---|---|
| **Total failure** | `TIMEOUT`, `CONNECTION_RESET` | The real adapter is **never called**. `session_state` is left byte-for-byte untouched — simulating a turn that never reached the agent. This is what lets the *next* turn reveal whether the conversation still makes sense with a gap in it. |
| **Corruption** | `MALFORMED_RESPONSE`, `PLAUSIBLE_WRONG`, `LATENCY_INJECTION` | The real adapter **is** called (agent logic and state mutation happen normally); only what the eval engine sees afterward is altered — truncated + corrupted bytes, replaced with a confidently-wrong canned answer, or given a latency penalty. |

Targeting is either deterministic (`target_turn_indices` — the Nth `run_turn` call within this case,
for a reproducible suite case) or probabilistic (`probability`, for broader chaos/load testing).

Every faulted turn carries a reserved marker tool call `__chaos_fault__`, and `has_chaos_marker()`
lives next to it so `ChaosAdapter` and `RecoveryScorer` share one definition of "chaos-affected"
instead of duplicating it. That avoided widening the `AgentTurnResult` STABLE CONTRACT just to add a
"was this faked" boolean.

**Disclosed scope, which is a strength not a weakness:** faults are injected at the RedLine↔agent
boundary, not inside the agent's own tool-calling logic — reaching in there would require
framework-specific instrumentation, exactly what the framework-agnostic architecture exists to
avoid. For an HTTP-deployed agent that boundary is a *real* dependency (the network), so the faults
are genuinely representative. For a local Python agent, the fault is synthetic — it still exercises
the engine and RecoveryScorer honestly, but it isn't simulating real infrastructure failure. Saying
that out loud is more credible than overclaiming.

### 12.4 Load Testing — the cost dimension nobody tests

> "k6/JMeter load-test APIs on latency and error rate. Nobody load-tests agent **cost** and
> tool-failure rate under concurrency — and cost is often the metric that kills an agent in
> production. An agent that's fine at 10 users can be financially unviable at 10,000."

`run_load_test(load_run_id)`:
- Builds **one** shared adapter (httpx.Client is thread-safe for concurrent requests).
- `ThreadPoolExecutor(max_workers=concurrency)`; each thread is one virtual user with **its own**
  `session_state` dict, looping `adapter.run_turn()` until a shared `time.monotonic()` deadline.
- Any adapter exception becomes a **failed sample**, not a crash.
- Aggregates: nearest-rank p50/p95/p99, error rate, total cost, **cost_per_hour_usd**,
  throughput_rps.
- Aggregate → Postgres `load_runs`; raw samples → ClickHouse `load_samples` (batched, non-fatal).

**Why this doesn't violate the "everything is synchronous" rule** — and this is a great question to
be ready for: `ThreadPoolExecutor` is OS-thread concurrency running ordinary synchronous Python.
There is no event loop anywhere. The rule exists because mixing asyncio with synchronous SQLAlchemy
Sessions and a synchronous Kafka consumer is a deadlock trap — threads with per-thread state don't
create that trap.

There's also a nice payoff here: concurrent load-test threads hitting a local agent that calls
`get_limiter()` all share **one real Redis-backed budget**, instead of each thread getting its own
illusory allowance. Phase 3's rate-limiter rewrite is what makes the load test honest.

### 12.5 Production Failure Mining (the actual ML)

> "Continuously embed production traces, cluster them, flag clusters correlating with bad outcomes.
> Each significant cluster becomes a candidate regression test automatically."

Pipeline:
1. Pull **every** `EvalCaseResult` across every suite and version for an agent.
2. Extract each result's final assistant message; embed them all (`embed_texts`).
3. Normalize → cosine similarity matrix → distance = `1 - similarity` → `DBSCAN(eps=0.15,
   min_samples=3, metric="precomputed")`.
4. Bad outcome = the case result's own `passed == False` (same signal the gate uses — any scorer
   failing is a legitimate bad outcome, not just safety).
5. A cluster is **significant** iff `size >= 3` **and** `bad_outcome_rate >= 0.5`. Both thresholds
   matter: size filters coincidental similarity; bad-rate filters "a common topic that mostly goes
   fine."
6. Pick a **bad-outcome member** as the representative (the point is testing the failure).
7. Persist a `FailureCluster` + a `CandidateCase` with `status="pending"` and a generated
   `judge_rubric` — then a human approves or rejects it via `/mining/candidates/{id}/approve`.

**Honest scoping to state up front:** RedLine has no separate production-traffic ingestion pipeline.
Every recorded agent interaction *is* an eval case result, and that is the corpus mined. It is the
closest honest proxy for "production traffic" available today — real recorded interactions, not a
synthetic sample. A live ingestion endpoint is future work.

**Why DBSCAN, not k-means:** you don't know the number of failure modes in advance, and DBSCAN's
noise label (`-1`) means unrelated responses are simply excluded rather than forced into a cluster.

---

## 13. Drift Detection

Two independent detectors, both driven by `drift_scheduler` (APScheduler `BlockingScheduler`,
`IntervalTrigger`, default 6 h, `coalesce=True`, `misfire_grace_time=300`, first run immediate).
It is its **own long-lived process**, not part of the API or the eval worker, with 1 replica and no
autoscaling — drift checks are deliberately serialized to avoid concurrent LLM cost spikes.

Per tick, per agent version:
1. Trigger a fresh eval run against the agent's `baseline` suite (`triggered_by='ci'`), run it
   synchronously.
2. `db.expire()` + `db.refresh()` to re-read the status the worker path wrote.
3. Persist a `DriftSnapshot` (pass_rate, counts, avg cost, avg latency).
4. **Model drift** — `detect_model_drift(recent_pass_rates, threshold=0.10)`, a pure function:
   baseline = mean of all snapshots *except* the newest; drift iff `current - baseline <= -0.10`.
   Only **regressions** alert; improvements are logged, not alarmed.
5. **Behavior drift** — `compute_diff_over_time(...)`; a `SILENT_DRIFT` classification raises a
   behavior alert.

Prometheus surface: `redline_drift_check_runs_total{status}`, `redline_drift_alerts_total{drift_type}`,
and a `redline_drift_score_delta{agent_version_id,suite_id}` **Gauge** that Grafana can alert on.

The 10-percentage-point threshold has a documented rationale: routine provider updates rarely move
typical suites more than ~5 pp, while genuine capability regressions or prompt-breaking changes move
10–20 pp. 10 pp catches real problems without firing on LLM non-determinism.

---

## 14. Security, Auth, and Multi-Tenancy

### Credentials — nothing raw is ever stored

| Credential | Generation | Storage |
|---|---|---|
| API key | `"rl_live_" + secrets.token_urlsafe(32)` | `SHA256(raw).hexdigest()` in `api_keys.key_hash`; raw shown **once** |
| Refresh token | `secrets.token_urlsafe(48)` | `SHA256(raw).hexdigest()` in `refresh_tokens.token_hash` |
| Password | — | `passlib.CryptContext(schemes=["bcrypt"])`, default 12 rounds |

Never logged: raw keys, raw JWTs, raw refresh tokens, passwords, `DATABASE_URL`, `GEMINI_API_KEY`.
Safe to log: hashes, user ids, tenant ids, key *names*.

### Dual-credential auth

`require_api_key()` accepts **either**:
- `Bearer rl_live_...` → long-lived API key, for the CLI and CI pipelines
- `Bearer <jwt>` → short-lived access token, for the dashboard

Discrimination is by prefix (API keys start with `rl_live_`). Both resolve to one `AuthContext`
(`tenant_id`, `role`, `user_id | api_key_id`) so downstream code never cares which was used.

### JWT + refresh rotation

- Access token: **15 minutes**, HS256, claims `{sub, tenant_id, role, exp, type:"access"}`.
- The **`type` claim is required and checked** — it is what prevents a refresh token being used
  where an access token is expected.
- JWT path also verifies the tenant and user still exist (guards token replay after deletion).
- Refresh token: **7 days**, opaque random, hashed, and **rotated on every use**.

**Reuse detection is the security-interview highlight:**

```
POST /auth/refresh with a token whose revoked_at IS NOT NULL
  → this token was already rotated
  → a legitimate client rotates exactly once
  → therefore this is replay / session hijacking
  → revoke ALL refresh tokens for that user, not just the replayed one
```

And there is a corresponding **frontend** consequence that shows end-to-end thinking: the dashboard's
`apiClient.ts` uses a **single-flight refresh** (`refreshPromise ??= doRefresh()`). Two concurrent
401s naively both calling `/auth/refresh` would each try to rotate the same token — the second would
find it already rotated and trigger exactly that mass revocation. Single-flight isn't stylistic; it
prevents the frontend from logging the user out of every session.

Token storage: the access token lives **only in module memory** (never persisted); the refresh token
lives in `localStorage` because it must survive a reload.

### RBAC

`require_role(*roles)` and `require_tenant_role(*roles)` are dependency factories.

| Operation | Required role |
|---|---|
| Read runs, dashboard | viewer |
| Create eval runs, push suites | developer |
| Manage agents, gates, API keys | admin |

`require_tenant_role` exists so a mutating route doesn't have to declare both `require_role` and
`get_tenant_context` and then reconcile two objects that must agree.

### Multi-tenancy — the real bug that was fixed

Phase 1 resolved the tenant with **`db.query(Tenant).first()`**. That is correct only while exactly
one tenant exists — and a silent cross-tenant read the moment a second one does. Phase 3 removed it
from every router. The rule now: **the tenant always comes from the auth context, never from the
database's insertion order and never from a client-supplied parameter.**

Object lookups verify ownership and return **404, not 403**, for another tenant's resource —
a 403 would confirm the resource exists, leaking the existence of another tenant's data to anyone
probing UUIDs.

11 integration tests cover this, **including a negative control that reproduces the old leak** —
proving the test would actually fail if the fix regressed.

### Other hardening

- Per-tenant API rate limit: 100 requests / 60 s, Redis sliding window (`ZREMRANGEBYSCORE` + `ZCARD`
  + `ZADD` + `EXPIRE` in one pipeline), returning **429 with `Retry-After`**.
- ClickHouse **least-privilege app user** (`redline_app`, `GRANT SELECT, INSERT` only). Admin
  credentials are used *only* by the one-time `init_clickhouse()` bootstrap and never reach a
  Kubernetes pod. The user identifier is regex-validated before being interpolated into
  `CREATE USER` SQL (clickhouse-driver can't bind identifiers).
- `.env` is gitignored; `.env.example` carries placeholders only. A leaked key was found and rotated
  once during development (commit `e34d01a`) — and the `.env`-baked-into-Docker-images bug was found
  and fixed (§22).

---

## 15. Service Decomposition, Gateway, Kubernetes, KEDA

### Three services, fixed route ownership

| Prefix | Service | Port |
|---|---|---|
| `/eval-runs`, `/ci`, `/auth`, `/diff-runs`, `/load-runs`, `/mining` | eval_service | 8001 |
| `/agents`, `/eval-suites` | agent_service | 8002 |
| `/dashboard` | gate_service | 8003 |

**Why this cut?** Rate of change and scaling profile. Eval logic changes constantly (new scorers,
new adapters, new metrics) and needs replicas under load. The agent registry and the gate/dashboard
read path change rarely and would otherwise be redeployed for reasons that have nothing to do with
them.

In local dev, `apps/api/main.py` mounts **all** routers as a monolith for convenience. That does not
change ownership — it means the monolith includes everything for local dev.

### nginx gateway

Prefix-based `proxy_pass` per service, `X-Real-IP` / `X-Forwarded-For` / `Host` passthrough, its own
`/health` that never routes inward, per-service `/docs` passthrough, and — since Phase 5.3 — it
serves the built dashboard SPA with `try_files $uri /index.html` so deep-link reloads don't 404.

### Kubernetes + KEDA (ADR-003)

| Workload | Scaler | Why |
|---|---|---|
| eval_service | **CPU HPA** (70%, 1→4) | Stateless request handler — request parsing, auth, DB queries. CPU is the right signal. |
| eval-worker | **KEDA on Kafka consumer lag** (`lagThreshold: 5`, 1→8) | Worker is **I/O-bound**: ~95% of its time is blocked on LLM API calls. CPU stays under 10% even fully saturated — a CPU HPA would **never trigger** no matter how deep the queue. Consumer lag *is* the backlog. |
| load-worker | KEDA (`lagThreshold: 1`, **0**→4) | Different resource profile entirely; scales to zero when idle. |

Two details:
- **`spec.replicas` must never be set** on a KEDA-managed Deployment — it fights the ScaledObject
  and produces oscillation between the hardcoded value and KEDA's target.
- **`cooldownPeriod: 300`** deliberately high: scaling down a mid-eval worker kills the in-flight
  job (the message is re-delivered, but the run must be re-queued). Five minutes lets jobs finish.
- KEDA can scale to **zero**; CPU HPA cannot. That matters for the load worker.

### Helm (ADR-005)

The chart is the deployment interface — `values.yaml` carries image tags, infra URLs, resource
requests/limits, autoscaling bounds, and secrets. Deliberately provider-agnostic; the cloud choice
was **deferred**, not faked. `_helpers.tpl`'s `commonEnv` injects the same env block into every
Deployment from a ConfigMap + Secret, which is what allowed removing `.env` from the images.

---

## 16. Observability

**Three pillars, each with a concrete implementation:**

1. **Metrics** — `prometheus-client` directly (not the instrumentator, see §22). An HTTP middleware
   records `redline_http_requests_total{service,method,path,status_code}` and
   `redline_http_request_duration_seconds`, skipping `/metrics` and `/health` (noise, not signal).
   Business metrics: `redline_eval_runs_total{status}`, `redline_eval_case_results_total{passed}`,
   `redline_eval_run_duration_seconds`, `redline_eval_case_cost_usd`,
   `redline_gate_decisions_total{passed}`, plus the drift counters/gauge. Every service exposes
   `/metrics`; a ServiceMonitor wires Prometheus to them.
2. **Logs** — single-line JSON to stdout via `logging.basicConfig(format=...)`, collected by
   Promtail into Loki. Containers don't write log files.
3. **Traces** — OTel SDK, `TracerProvider` + `BatchSpanProcessor` + OTLP/gRPC → Tempo.
   `eval_run` span with `eval_run_id`, `case_count`, `agent_version` attributes; a child `eval_case`
   span per case with `case_key` and `case_index`; `span.record_exception(exc)` on failure. Exporter
   `timeout=5` so tracing is never load-bearing.

Plus the **application-level** trace stream in ClickHouse (`run_started` / `turn_completed` /
`run_completed`), which is what the dashboard's Trace Viewer reads — distinct from OTel spans, and
deliberately so: this one is queryable per tenant with SQL aggregations.

---

## 17. The CLI and the CI/CD Gate

### `agentbench` — HTTP only, always

```bash
agentbench login --base-url http://localhost:8000 --api-key "$API_KEY"
agentbench init --agent rag-agent --entrypoint agents.rag_agent.agent:run_turn
agentbench push-suite eval-suites/rag-agent/baseline.yaml
agentbench register-version --version-label v1 --model gemini-2.5-flash
agentbench run --suite baseline
agentbench diff <version-a-uuid> <version-b-uuid> --suite baseline
agentbench load <version-uuid> --users 50 --duration 60
agentbench mine <agent-uuid>
agentbench candidates-list --agent-id <uuid> [--status pending]
agentbench candidates-approve <candidate-uuid> | candidates-reject <candidate-uuid>
agentbench ci-check --agent rag-agent --suite baseline      # CI only
```

State: `~/.agentbench/config.toml` (credentials, chmod `0600`) and `./agentbench.yaml` (project:
agent_id, **entrypoint**, version_id, suite_id). Note that `entrypoint` is written by
`agentbench init` and read from that file by `register-version` — it is not a flag on
`register-version`, which only takes `--version-label`, `--model`, and optionally
`--git-commit-sha` / `--content-hash`.

`register-version` computes `content_hash` by importing the entrypoint's module and hashing
`open(module.__file__, "rb").read()`. For an **HTTP** agent RedLine cannot read the source, so you
pass `--content-hash "$(git rev-parse HEAD)"` explicitly — otherwise the diff engine would have no
code axis to classify against.

The CLI **never** imports `apps.api.models`, never opens a DB connection. It's installed on
developer laptops that have no Postgres, no broker, and often no libpq to compile against.

### The GitHub Actions gate

```yaml
# .github/workflows/agentbench-check.yml
on: pull_request: branches: [main]
permissions: {checks: write, contents: read}
steps:
  - pip install .                      # the CLI only — no server deps
  - agentbench login  --base-url $REDLINE_BASE_URL --api-key $REDLINE_API_KEY
  - agentbench ci-check --agent rag-agent --suite baseline
```

`ci-check` owns the whole GitHub Check Run lifecycle:
1. `create_check_run(repo, sha, GITHUB_TOKEN)` — **only possible from inside the Actions job**, with
   its ambient token. (GitHub's Feb-2025 platform change: only the job's own token can create/update
   a Check Run.)
2. `POST /ci/check` → creates an `EvalRun(triggered_by='ci', git_pr_number=...)` and publishes.
3. Polls `GET /eval-runs/{id}` every 5 s.
4. `update_check_run(...)` with the verdict + reasons.
5. `exit 0` on pass, **`exit 1` on fail**.

**The key architectural point:** `routers/ci.py` is completely **GitHub-agnostic**. The API server
has no idea GitHub exists, holds no GitHub token, and calls no GitHub API. All GitHub knowledge lives
in the CLI, which runs inside the Actions job. That makes the same endpoint reusable from GitLab CI,
Jenkins, or a shell script.

The workflow deliberately carries **no `GEMINI_API_KEY`** — the CLI never calls an LLM; the eval runs
server-side where the key lives. A CI job holding a provider key it doesn't use is needless secret
exposure.

Making the check *blocking* is a repo setting: `"AgentBench Reliability Check"` must be a **required
status check** in branch protection for `main`.

### The platform CI (`ci.yml`)

`unit-tests` → `frontend-build` → `integration-tests` (with real Postgres/Redis services) → build +
**Trivy** + **pip-audit** → (main only) push to GHCR with an immutable tag → `helm upgrade --atomic`
+ health check.

`frontend-build` runs `make generate-types` and then `git diff --exit-code api-types.ts` — so a
backend schema change that wasn't regenerated **fails CI**.

There's also `test-suite-integrity.yml`, a fast linter that fails if a test file is missing its
`pytestmark` — because a test file without a marker is silently skipped by `pytest -m unit`, which
is the worst kind of broken test.

---

## 18. The Dashboard

React 18 + TypeScript + Vite, `AuthProvider` + `RequireAuth` guarding a shell layout.

| Route | Page | Data |
|---|---|---|
| `/` | AgentsListPage | agents + latest run |
| `/agent/:id` | AgentDetailPage | versions, runs, ARS trend, error-budget gauge, drift alerts |
| `/agent/:id/clusters` | FailureClustersPage | mined clusters + candidate cases |
| `/runs/:id` | RunDetailPage | gate banner, per-case results, transcripts |
| `/runs/:id/traces` | TraceViewerPage | ClickHouse trace events |
| `/diffs/:id` | DiffViewerPage | classification + per-case similarity |
| `/load-run/:id` | LoadTestReportPage | p50/p95/p99, error rate, cost/hour |

Two details worth mentioning, both discovered by testing rather than assumed:

- **SPA routes are singular** (`/agent/:id`, `/load-run/:id`) precisely to avoid colliding with the
  plural backend prefixes (`/agents`, `/load-runs`) at the gateway. nginx prefix matching sends *any*
  path starting with `/agents` to agent_service — so a browser refresh on the agent-detail page would
  hit an API that doesn't implement that route and 404. Confirmed against the real built gateway
  image.
- **Single-flight refresh** in `apiClient.ts` (see §14) — required by the backend's reuse-detection
  semantics.

`RoleGate` hides mutating actions from viewers; `TriggerEvalRunDialog` / `TriggerDiffRunDialog` /
`TriggerLoadRunDialog` are the write paths.

---

## 19. The Benchmark Agents (Levels 1, 3, 4)

These are **fixtures under test**, not library code — the platform deliberately does not share code
with them (e.g. `diff_engine` re-implements cosine similarity rather than importing the agent's).

| Level | Agent | What it exercises |
|---|---|---|
| 1 | `rag-agent` | Retrieval-augmented customer support over 3 markdown KB docs. Chunks on `## ` headers, embeds with `gemini-embedding-001` (768-d), cosine top-3, `RELEVANCE_THRESHOLD = 0.60` (calibrated: noise floor ~0.55–0.56, real relevance ~0.67+). Explicitly answers **"I don't know"** below threshold — the hallucination failure mode this benchmark exists to make testable. Computes real cost from token counts and per-1M pricing constants. |
| 3 | `stateful-support-agent` | Structured memory: after every turn it extracts entities, preferences, and constraints into `session_state` and injects them into the next prompt. The 7 eval cases probe **entity memory, preference memory, constraint memory, correction memory, repeated-question suppression, context accumulation, topic continuity** — e.g. the user says "3 years", corrects to "18 months", then asks about warranty; the agent must use 18 months. |
| 4 | `research-pipeline-agent` | Multi-agent pipeline: **Planner → [ResearcherA + ResearcherB] → Verifier → Synthesizer** (5 LLM calls per turn). The cases probe *coordination* failures: are the sub-queries genuinely distinct, does the synthesizer use both outputs, does the verifier catch an unanswerable sub-query, is total cost bounded, are there contradictions. |

All three use `get_profile(...)` and `get_limiter(...)` — never a hardcoded model name, never a
hardcoded `time.sleep()`. All three lazily index the KB on first `run_turn()` (never at import time,
so importing the module for a test doesn't burn an embedding call) and cache per process.

### Eval suites are declarative YAML

```yaml
suite: baseline
agent: rag-agent
cases:
  - case_key: case_003_multiturn_followup
    description: "Session evaluation — a follow-up must use prior turn context"
    turns:
      - {role: user, content: "What's your shipping policy?"}
      - {role: user, content: "And does that apply to international orders too?"}
    expectations:
      judge_rubric: "The second answer must directly address international shipping, not
                     just repeat the domestic policy, and must not ask the user to repeat
                     information already given in turn 1."
```

---

## 20. Testing Strategy

**301 test functions**: 218 unit, 83 integration.

```bash
pytest -m unit          # no Postgres, no LLM calls, seconds — runs anywhere
pytest -m integration   # needs docker compose (Postgres, Redis, Redpanda) ± GEMINI_API_KEY
```

Markers are **mandatory** (`pytestmark = pytest.mark.unit` at file top) and enforced by both a CI
workflow and `scripts/check_pytestmark.py`.

Notable coverage:

| File | Tests | What it proves |
|---|---|---|
| `test_scorers.py` | 30 | All six scorers, including groundedness edge cases |
| `test_http_adapter.py` | 23 | Retry policy, ReadTimeout non-retry, in-place session state, malformed bodies |
| `test_llm_rate_limiter.py` | 22 | Window, daily quota, degradation |
| `test_ars_engine.py` | 18 | ARS math + error budget |
| `test_gate_engine.py` | 17 | Pure threshold logic, <100 ms, no infra |
| `test_diff_engine.py` | 17 | All four quadrants classified from plain dicts |
| `test_chaos_adapter.py` | 16 | Both fault families, targeting modes |
| `test_mining_engine.py` | 16 | Clustering significance from synthetic labels |
| `test_load_engine.py` | 15 | Percentiles, cost/hour, error rate |
| `test_tenant_isolation.py` | 11 (integration) | Cross-tenant reads blocked, **incl. a negative control reproducing the old leak** |
| `test_llm_rate_limiter_redis.py` | 12 (integration) | Real Redis, real concurrency, outage + recovery |
| `test_packaging.py` | 8 | `pyproject.toml` and `requirements.txt` haven't drifted |
| `test_worker_restart.py` | 1 (integration) | Kill a worker mid-run → message re-delivered, no loss |

**The reason this coverage was achievable** is the pure-function-plus-wrapper discipline: every
engine's real logic (`_compute_gate_result`, `_compute_ars`, `compute_error_budget`,
`_classify_diff`, `_identify_significant_clusters`, `_compute_load_stats`, `detect_model_drift`)
takes plain numbers/dicts/lists and returns a result object — so it's testable with no DB, no
network, no LLM.

---

## 21. Recurring Design Principles

These repeat across the codebase. Being able to name them is what makes this sound designed rather
than assembled.

1. **Pure core, DB-backed wrapper.** Every engine splits into a pure function (numbers in, result
   out) and an orchestrator that resolves rows and persists. Gate, ARS, diff, mining, load, drift —
   all six.
2. **Stable contracts as swap seams.** Declare the narrow interface *before* you need the second
   implementation. Postgres→Redpanda, local→HTTP, plain→chaos: each swap touched no caller.
3. **Side channels must never be load-bearing.** ClickHouse writes, OTel exports, Prometheus, ARS
   computation — all wrapped, all non-fatal. Correctness depends only on Postgres and the provider.
4. **Missing configuration never means "allow".** No gate policy ⇒ default 0.9. No SLO policy ⇒
   default budget. Missing scorer result ⇒ counts as failed.
5. **Read paths never write.** `gate_engine.evaluate()` is called on every dashboard load, so ARS is
   computed once at run completion and only *read* by the gate.
6. **Fail loudly and boundedly rather than hanging.** `flush(timeout=10)`, OTLP `timeout=5`, bounded
   HTTP retries, `DailyQuotaExceeded` raised rather than sleeping until midnight.
7. **Degrade leniently where a dependency outage would otherwise cause a total outage.** Redis down ⇒
   the rate limiter falls back to a per-process window and logs loudly, rather than refusing every
   LLM call.
8. **404 not 403 for another tenant's resource.** Don't leak existence.
9. **Return plain result types, never live ORM instances**, from functions that close their own
   session (learned via a real `DetachedInstanceError`).
10. **Document the honest scope.** Chaos at the adapter boundary, mining over eval history, uncalibrated
    thresholds — all stated in the code itself.

---

## 22. Real Difficulties Faced and How They Were Solved

This is the section most likely to make or break an interview. Every item below actually happened.

### 22.1 Sync vs async — the foundational fork (ADR-001)

`confluent-kafka` is synchronous (librdkafka C binding). `aiokafka` is async. Choosing `aiokafka`
would have forced one of two bad outcomes: run the event loop in a separate thread (race conditions
around the SQLAlchemy `Session`), or rewrite `run_eval()`, every scorer, and the whole ORM layer as
async. The decision: **stay fully synchronous**, and codify it as an architectural rule verified by
`grep -rn "async def\|await\|asyncio" apps/api/services/ apps/api/workers/` returning zero matches.
The review trigger is documented: revisit only if the engine is genuinely rewritten async.

### 22.2 The LLM rate limiter was arithmetically wrong under autoscaling

Phase 2 used an in-process `deque` sliding window, justified by "there is typically one worker."
Then KEDA started scaling the worker on consumer lag, and **N pods each holding a private 15-RPM
window permit 15N requests/min against one provider quota**. It wasn't slightly off — it was wrong,
and it got *worse the better autoscaling worked*.

The rewrite (Phase 3.3):
- Redis **sorted set** for the sliding window + a Redis **counter keyed by UTC date** for the daily
  quota: `ratelimit:llm:{provider}:{model}` and `quota:llm:{provider}:{model}:{YYYY-MM-DD}`.
- **A Lua script**, because check-then-add across two round trips is a race: two workers can both
  read `count = 14` against a limit of 15 and both proceed. Redis executes Lua atomically. This is
  the direct answer to "why not just a pipeline?"
- **Two limits, not one.** A full per-minute window is a *wait*. An exhausted **daily** quota is
  not — blocking a worker until midnight UTC is never right — so it raises `DailyQuotaExceeded` and
  the run fails with a clear reason.
- **Graceful degradation**: Redis unreachable ⇒ fall back to the per-process window and log a
  warning on transition. Deliberately the *lenient* failure — refusing all LLM calls because a cache
  is down would turn a cache outage into a total platform outage.
- The public API `acquire()` never changed — it's a STABLE CONTRACT.

### 22.3 The rate limiter was metering the wrong model

Found during a Phase 4 audit. `get_limiter("standard")` cached by profile name alone and always used
`profile.chat_model`. But `embeddings.py` also called `get_limiter("standard")` — for **embedding**
calls that actually hit `gemini-embedding-001`. So every embedding call the platform ever made
(diff engine, mining, RAG retrieval) was silently sharing the agent's **chat** rate/quota bucket,
under the **wrong model's name**, in Redis.

Fix: `get_limiter(profile, for_embedding=True)` selects `profile.embedding_model`, and the cache key
became `(profile_name, purpose)` so chat and embedding limiters are two genuinely separate instances
with separate Redis keys and separate daily counters. The remaining simplification (`rpm` and
`daily_limit` are still read from the same profile fields) is documented rather than hidden.

### 22.4 The LLM judge made completely unmetered calls

Discovered while removing a hardcoded model name. `LLMJudgeScorer` had a `JUDGE_MODEL` constant and
called Gemini with **zero** rate limiting — neither the per-minute window nor the daily quota applied
to it. Since the baseline suite uses `judge_rubric` on most cases, it was spending daily quota the
platform had no record of, undermining the entire reason the quota tracking existed. Fix: use
`get_profile("high_reasoning")` and `get_limiter("high_reasoning")`, and verify live against Gemini
that the daily counter now increments.

Two sibling instances of the same violation were found in the same pass: the RAG agent's `CHAT_MODEL`
constant and a hardcoded `--model` default in the CLI's `register_version`.

### 22.5 `publish()` silently ignored `job_type`

Found in Phase 4 while adding load testing. `RedpandaJobQueue.publish()` accepted `job_type` and
**ignored it**, always producing to `topic_eval_requested`. Nobody noticed for two phases because
every call site until then happened to pass `"eval.requested"` — the one value that coincidentally
matched. Adding a second job type would have silently routed load jobs to the eval worker.

Fix: a `_KNOWN_TOPICS` registry mapping `job_type` → configured topic, and `_resolve_topic()` that
**raises on anything unregistered** rather than producing to an arbitrary string. Lesson worth
stating: a signature that promises routing must actually route, and "it works" is not the same as
"it's correct."

### 22.6 Redpanda needed *three* listeners, not two (Bug 2)

k3d pods could not consume messages the services published. The root cause is Kafka's **metadata
protocol**: a client bootstraps at one address, then the broker tells it which address to reconnect
to — the **advertised** address. With a single external listener advertising `localhost:19092`, a
pod that bootstrapped via `host.k3d.internal:19092` was then told to reconnect to `localhost`, which
inside a pod is the pod itself. Every post-bootstrap call failed with "Connection refused". Eval runs
sat in `pending` forever while the Redpanda console showed messages piling up.

Fix: three distinct listeners with three distinct advertised addresses:

```
--kafka-addr           internal://0.0.0.0:9092,external://0.0.0.0:19092,k3d://0.0.0.0:29092
--advertise-kafka-addr internal://redpanda:9092,external://localhost:19092,k3d://host.k3d.internal:29092
```

`internal` for container-to-container on the compose network, `external` for host processes, `k3d`
dedicated to in-cluster pods. Verified against real worker pod logs on a live cluster, not assumed.

### 22.7 `.env` was baked into every Docker image (Bug 6)

All three service Dockerfiles did `COPY .env .env`, embedding the Gemini key and JWT secret into
every image layer — retrievable by anyone who could pull the image. Removed from all three; verified
that Compose (`env_file: .env`) and Helm (`commonEnv` from Secret + ConfigMap) supply every variable
without it, and that a rebuilt image genuinely contains no `.env`. A leaked key also had to be
rotated once (`e34d01a`).

### 22.8 `DetachedInstanceError` from returning ORM objects

`mine_failures()` originally returned `FailureCluster` ORM instances. Its own `finally: db.close()`
invalidated them, so an integration test reading a returned object's attributes blew up. Fix: a
plain `MinedCluster` dataclass populated **before** the session closes. This is now a stated rule —
every Phase 4 engine returns a plain dataclass/Pydantic result, never a live ORM instance.

### 22.9 The diff engine's unreachable classifications

Already covered in §12.2, but as a *difficulty*: the first design took two version ids, which — given
`UNIQUE(agent_id, content_hash)` — made `code_changed` always `True` and rendered `SILENT_DRIFT` and
`NO_OP` **structurally unreachable**. The feature would have "worked" and been permanently incapable
of detecting the one thing it exists to detect. Fix: the primitive takes two **run** ids; the version
comparison becomes a convenience wrapper.

### 22.10 Gemini models were shut down under the project

While verifying quota values, the models the profiles pointed at turned out to be dead:
`gemini-2.0-flash` and `gemini-2.0-flash-lite` had been **shut down** by Google (every call would
fail, not merely misreport quota), and `gemini-2.5-flash-lite` returned 404 "no longer available to
new users" on this project's key despite still being documented as stable. Remapped `standard` →
`gemini-2.5-flash`, `high_reasoning` → `gemini-3.5-flash`, `cheap` → `gemini-3.5-flash-lite`, each
confirmed with a live call.

**This is exactly the class of failure the whole project exists to catch**, and it happened to the
project itself.

Also: Google no longer publishes fixed free-tier rate limits. The `standard` daily limit was
confirmed against **ground truth** — a real 429 whose body was Google's own quota metering:
`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier, model: gemini-2.5-flash, quotaValue: '20'`
— i.e. **20/day**, not the 250 third-party aggregators reported. The other two profiles keep
conservative third-party estimates, and the file says so explicitly rather than pretending.

### 22.11 The Gemini daily quota blocked real verification

The Level 3 gate verdict is *still* blocked on a genuine free-tier daily quota (20 requests/day for
the judge model — and the Level 4 pipeline agent makes 5 LLM calls per turn on top of the judge).
This was handled by **surfacing it honestly** rather than forcing past it: migration 0009 added
`eval_runs.error` so `DailyQuotaExceeded` shows up as a readable reason in the CLI and dashboard,
instead of a bare `status='failed'` with the real cause buried in an OTel span nobody reads back.

That is the right instinct to convey: an unverified result stays labeled unverified.

### 22.12 `prometheus-fastapi-instrumentator` dependency conflict

The obvious library requires `starlette>=1.0.0`; FastAPI 0.115.6 ships `starlette 0.41.x`. Installing
it produces an import error at startup. Rather than fight the resolver or downgrade FastAPI, use
`prometheus-client` directly and write the middleware + `/metrics` endpoint by hand — about 30 lines,
zero dependency churn, and exact control over metric names and labels.

### 22.13 Postgres ignores `POSTGRES_PASSWORD` on an existing volume

`docker compose up` succeeded but `alembic upgrade head` failed with "authentication failed". Docker
Postgres applies `POSTGRES_PASSWORD` **only on first initialization**; an existing named volume keeps
its original password. Fix: either `docker compose down -v` and reinitialize, or
`ALTER USER redline WITH PASSWORD ...` inside the container. Documented as a decision so it isn't
re-debugged. (Also: the port is **5433**, not 5432, to avoid a local Postgres.)

### 22.14 Double-pooling behind PgBouncer

Putting PgBouncer (transaction-mode pool) under SQLAlchemy's default `QueuePool` means two
independent pools stacked on each other, which defeats the point of adding a pooler. Fix: when
`db_use_external_pooler=true`, SQLAlchemy switches to `NullPool` so every checkout is a fresh
connection to PgBouncer — which is exactly what PgBouncer is designed to pool. Kept **opt-in** and
off by default because it's a blast-radius change to every service's DB path.

### 22.15 The SPA / API route collision at the gateway

nginx prefix matching sends *any* path beginning with `/agents` to agent_service. The dashboard's
agent-detail route was `/agents/:id`, so a browser refresh hit an API that doesn't implement that
route and 404'd. Fix: singular SPA routes (`/agent/:id`, `/load-run/:id`) that can't collide.
Confirmed by testing the **built** gateway image, not by reasoning about it.

### 22.16 Concurrent refresh → mass session revocation

Covered in §14. Two concurrent 401s both calling `/auth/refresh` would each rotate the same token;
the second would be treated as reuse and revoke every session for that user. Fixed with a
single-flight promise in the API client. A frontend fix that only exists because the backend's
security semantics were designed strictly.

### 22.17 Failure traces stamped with a random tenant

Covered in §8 — `emit_trace()` in the failure path used `uuid.uuid4()` as the tenant id, making every
failed run invisible to per-tenant ClickHouse queries because the table sorts by `tenant_id` first.
Failures are the one thing you'd search for.

### 22.18 Multi-tenancy was fake

`db.query(Tenant).first()` in two routers, plus completely unauthenticated `/dashboard` routes with
the comment "the dashboard is a read-only internal tool." True on a laptop with one seeded tenant;
a full cross-tenant data leak anywhere else. Fixed with `TenantContext` resolved from auth, ownership
checks on every single-object lookup, 404-not-403, and 11 integration tests including a negative
control.

---

## 23. What Is Genuinely Novel

Be precise here. These are the defensible claims:

1. **A deployment gate for agents that actually blocks.** Not a score, not a dashboard — exit code 1
   → failed required status check → disabled merge button. Verified live on PR #2.
2. **Error-budget-driven deployment freeze applied to agent reliability.** A perfect run still fails
   the gate if the agent's recent history burned its budget. Straight SRE, and to the best of the
   project's knowledge no agent-eval tool does this.
3. **Silent-drift detection via same-version-over-time behavioral diff.** The four-quadrant
   classification, and specifically the schema-level insight that comparing two *versions* makes the
   alarm quadrant structurally unreachable — so you must compare a version to *itself* across time.
4. **Chaos engineering for agents,** with fault injection as a decorator over a stable adapter
   contract, and a recovery scorer whose deterministic bar is deliberately minimal and defensible.
5. **Load testing that reports cost-per-hour at a given concurrency,** not just latency and error
   rate. Cost is the metric that kills agents in production and nobody load-tests it.
6. **Unsupervised failure mining that closes the loop** — DBSCAN over embeddings of real recorded
   interactions → clusters correlated with bad outcomes → auto-generated candidate regression cases
   → human approval → they become real eval cases. Failures become tests, automatically.

And structurally:

7. **The stable-contract discipline**, demonstrated by three transport/implementation swaps that
   touched zero calling code.
8. **The pure-function-plus-wrapper discipline**, demonstrated by 218 unit tests that need no
   infrastructure at all.

---

## 24. Honest Limitations

Volunteering these makes the rest credible.

- **No public deployment.** Local Docker Compose and local k3d only. Helm is the interface; the cloud
  provider was deliberately deferred (ADR-005) rather than half-built.
- **No live production-traffic ingestion.** "Failure mining" mines eval history, which is the honest
  available proxy. Stated in the code.
- **Two thresholds are uncalibrated defaults**: the diff engine's `0.90` similarity and mining's
  `eps=0.15`. There's no labeled corpus to tune them against yet, and the code says so. (The drift
  detector's `0.10` *does* have a stated rationale.)
- **Level 3's gate verdict remains unverified**, blocked on a genuine 20-requests/day Gemini free-tier
  quota. Level 1 (pass_rate 0.67 → gate FAIL) and Level 4 (pass_rate 0.50 → gate FAIL) are verified.
- **Chaos faults are at the adapter boundary**, not inside the agent's own tool-calling logic. Real
  for HTTP-deployed agents; synthetic for local Python agents.
- **ARS weights are fixed**, not per-agent configurable.
- **Single-node Redis** — `DistributedLock` uses `SET NX EX`, not a Redlock quorum. Fine for one
  node; would need `redlock-py` for a cluster. Documented.
- **At-least-once, not exactly-once** delivery. Deduplication is by distributed lock, and a stale
  `running` run still needs a recovery pass that isn't built.
- **mTLS between services is explicitly deferred**; OIDC is not implemented.
- One provider (Gemini) is wired, though the profile system is what makes adding another a YAML edit
  plus a client.

---

## 25. Numbers Worth Memorizing

| Thing | Value |
|---|---|
| ARS formula | `0.4·correctness + 0.2·safety + 0.2·latency + 0.2·cost` |
| Default gate `min_pass_rate` | 0.9 (used even when no policy row exists) |
| Default SLO | `target_ars=0.9`, `error_budget_pct=0.1`, `window_days=7` |
| Diff similarity threshold | 0.90 (uncalibrated default) |
| DBSCAN | `eps=0.15` (≈ cosine sim ≥ 0.85), `min_samples=3`, `min_bad_outcome_rate=0.5` |
| Drift threshold | 0.10 (10 percentage points), baseline window 5 |
| Access token / refresh token | 15 minutes / 7 days |
| API rate limit | 100 requests / 60 s per tenant |
| Max job retries before DLQ | 3 |
| KEDA lag thresholds | eval-worker 5 (1→8 replicas); load-worker 1 (0→4) |
| KEDA cooldown | 300 s |
| Ports | Postgres 5433, PgBouncer 6432, Redis 6379, Redpanda 19092/29092, ClickHouse 8123/9000, Tempo 4317/3200, services 8001/8002/8003, gateway 8085 (k3d 8000), dashboard 5173 |
| Tests | 301 total — 218 unit, 83 integration |
| Migrations | 0001 → 0010 |
| Embeddings | `gemini-embedding-001`, 768 dimensions, `task_type=SEMANTIC_SIMILARITY` |
| Verified gate verdicts | Level 1: pass_rate 0.67 → FAIL. Level 4: pass_rate 0.50 → FAIL (+ ARS budget breach) |
| Load test evidence | 10,307 real samples confirmed in ClickHouse |

---

## 26. Likely Interview Questions with Answers

**"Walk me through the architecture."**
Use §3. Narrate the run: CLI → API (returns immediately) → Redpanda partitioned by tenant → worker
with lock + commit-after-processing → eval engine calling one adapter interface → six scorers → case
results in Postgres, traces in ClickHouse → gate engine's pure threshold function + error budget →
exit code that blocks a merge.

**"Why not just use LangSmith / Braintrust?"**
They answer "what happened" and "did this score well." Neither *blocks a deploy*, and none implement
error budgets, silent-drift detection, chaos, cost-under-concurrency load testing, or automatic
regression-test mining. RedLine's unit of output is a **verdict**, not a chart.

**"Why synchronous? Isn't async faster for I/O-bound work?"**
Async would help if the bottleneck were in-process concurrency, but the actual constraint is a
provider **rate limit**, not thread scheduling — you scale by adding worker pods (KEDA on lag), not
by adding coroutines. Meanwhile `confluent-kafka` is synchronous, and mixing an event loop with
synchronous SQLAlchemy Sessions and blocking Kafka calls is a well-documented deadlock trap. The
one place genuine concurrency was needed — load testing — uses `ThreadPoolExecutor`, which gives
real concurrency with no event loop. ADR-001 records the review trigger.

**"How do you avoid duplicate processing with at-least-once delivery?"**
A Redis `SET NX EX` distributed lock keyed by job id. A re-delivered message whose lock is held is
skipped and its offset committed. The lock TTL slightly exceeds the max expected job duration so a
crashed worker's lock eventually expires.

**"Why Redpanda over Kafka? Why Kafka over a Postgres table?"**
Redpanda: identical Kafka wire protocol, consumer groups, offsets, partitions, and KEDA scaler — but
one binary, no JVM, no ZooKeeper. The Postgres `SKIP LOCKED` queue actually worked and is still there
for audit; the log wins on **partitioned isolation per tenant**, **broker-managed load distribution
across N consumers with zero coordination code**, **replayability**, and **a lag metric that is
exactly the right autoscaling signal**.

**"Why two databases?"**
Different workloads. Postgres: transactional, relational, mutable, the source of truth for decisions.
ClickHouse: append-only, high-cardinality, aggregate-only — a single load run emits 10,000+ sample
rows whose only queries are percentiles. And the tolerance difference is codified: `emit_trace()` can
never raise.

**"Why does the gate default to 0.9 when no policy exists?"**
Because "nobody configured a gate" must not silently mean "anything goes." A missing policy is the
most likely state for a new agent, which is exactly when a gate matters most.

**"How does the error budget differ from a pass-rate threshold?"**
A threshold is a statement about *this run*. An error budget is a statement about the *recent past*.
That is why it lives outside the pure function, and why an exhausted budget fails a run that scored
perfectly. It's the deployment-freeze mechanic from SRE.

**"How do you detect that a model changed underneath you?"**
Compare the **same agent version** against **itself** across two completed runs of the same suite.
Same version ⇒ same `content_hash` ⇒ `code_changed = False`. If mean cosine similarity of final
assistant messages drops below threshold, that's `SILENT_DRIFT`. And note *why* it has to be the same
version: `UNIQUE(agent_id, content_hash)` guarantees two different versions always differ in code, so
comparing versions makes the alarm quadrant structurally unreachable.

**"Your rate limiter — why Lua?"**
Because check-then-add across two Redis round trips is a race: two workers both read 14 against a
limit of 15 and both proceed. The entire reason for moving off the in-process deque was cross-worker
coordination, so the check and the add must be one atomic operation. Redis runs Lua atomically.

**"What happens when Redis goes down?"**
The limiter degrades to a per-process window and logs a warning on transition. That's deliberately
the lenient failure — refusing every LLM call because a cache is down would turn a cache outage into
a total platform outage. It over-permits under concurrency, which is exactly the old Phase 2 behavior:
acceptable briefly and loud enough to notice.

**"Why does the API server not talk to GitHub?"**
Two reasons. Design: `POST /ci/check` stays reusable from GitLab, Jenkins, or a shell script. And a
platform constraint: since Feb 2025 GitHub only lets a job's **own ambient token** create/update a
Check Run — so that code *must* live in the CLI running inside Actions.

**"How do you know your tenant isolation actually works?"**
11 integration tests, including a **negative control that reproduces the original leak** — so the
suite would genuinely fail if the fix regressed. Plus 404-not-403 so probing UUIDs can't confirm
existence.

**"What's the hardest bug you fixed?"**
Pick one and tell it as a story. Best candidates: the three-listener Redpanda advertised-address bug
(§22.6 — requires understanding Kafka's metadata protocol), the embedding limiter metering the wrong
model (§22.3 — silent, cross-cutting, found by audit), or `publish()` ignoring `job_type` (§22.5 —
"it worked" ≠ "it's correct").

**"What would you do next?"**
Public deployment on the existing Helm chart; a live production-traffic ingestion endpoint so mining
is real rather than proxied; calibrate the diff and DBSCAN thresholds against a labeled corpus; a
recovery pass for stale `running` runs; per-agent ARS weights; mTLS + OIDC.

---

## 27. Topics and Technologies to Read and Revise

Grouped by how likely they are to come up. Everything here is actually used in the project — an
interviewer can pull any of it from the code.

### Tier 1 — you will almost certainly be asked

**Kafka / Redpanda fundamentals**
- Topics, partitions, offsets, consumer groups, partition assignment and rebalancing
- **Partition key** semantics and why `tenant_id` gives noisy-neighbor isolation
- **Consumer lag** — what it measures, why it's the right autoscaling signal
- Delivery semantics: at-most-once vs **at-least-once** vs exactly-once; why commit-after-processing
  gives at-least-once and why that forces idempotency/dedup
- Producer `acks=all`, retries, `flush()` and why a bounded flush matters
- Dead-letter queues and retry envelopes
- **Kafka's metadata/advertised-listener protocol** (this is the §22.6 bug)

**PostgreSQL + SQLAlchemy 2.0**
- `SELECT ... FOR UPDATE SKIP LOCKED` — how it enables a safe multi-consumer queue
- Transaction isolation levels; why the lock is held only across select+update+commit
- Session lifecycle: `flush` vs `commit`, `expire`/`refresh`, `DetachedInstanceError`
- 2.0 style: `Mapped[...]`, `mapped_column`, `select().where()` + `db.execute()`; `Session` not
  `AsyncSession`; `NullPool` vs `QueuePool`
- JSONB — when a schemaless column is right (`turns`, `expectations`, `transcript`)
- Indexes: composite `(tenant_id, created_at)`, and reading `EXPLAIN ANALYZE` (seq scan → index scan)
- Alembic: autogenerate vs handwritten, migration ordering, drift

**FastAPI + Pydantic v2**
- Dependency injection and dependency *factories* (`require_role("admin")` returning a dependency)
- `response_model` and why every endpoint has one
- Middleware ordering; async middleware around sync handlers
- Pydantic v2: `model_validate` / `model_dump`, validators, `BaseSettings`
- Automatic OpenAPI generation → client type generation

**Auth & security**
- JWT structure, HS256 vs RS256, claim validation, why the `type` claim matters
- **Refresh token rotation + reuse detection** and the "revoke all sessions" response
- bcrypt (work factor, salting) vs SHA256 — why passwords need a *slow* hash and API keys don't
- Why store `SHA256(key)` for API keys but bcrypt for passwords (entropy of the secret)
- RBAC design; 404-vs-403 information leakage
- OWASP basics; secret management; why `.env` must never enter an image layer

**Redis patterns**
- Sorted-set sliding window vs token bucket vs fixed window
- `SET NX EX` distributed lock, TTL selection, and **Redlock** (and why single-node ≠ Redlock)
- **Lua scripting for atomicity** — the check-then-act race
- Cache invalidation and TTL as a safety net

### Tier 2 — strong differentiators if you know them

**Kubernetes + autoscaling**
- Deployment / Service / Ingress / ConfigMap / Secret / HPA
- **KEDA**: ScaledObject, external triggers, scale-to-zero, `cooldownPeriod`
- Why CPU HPA fails for I/O-bound workloads; choosing the right scaling signal
- Resource requests vs limits; why heterogeneous worker pools scale independently
- Helm: templates, values, `_helpers.tpl`, `helm upgrade --atomic`

**Observability**
- The three pillars and what each is *for*
- Prometheus: Counter vs Gauge vs Histogram, labels and cardinality risk, scraping, ServiceMonitor
- OpenTelemetry: spans, span attributes, context propagation, `BatchSpanProcessor`, OTLP
- Grafana Tempo (traces) / Loki (logs) / Prometheus (metrics)
- Structured logging and why containers log to stdout
- Golden signals: latency, traffic, errors, saturation

**SRE concepts** (this project is built on them — know them cold)
- SLI / SLO / SLA distinctions
- **Error budgets** and burn rate; the deployment-freeze mechanic
- Chaos engineering (Chaos Monkey; steady-state hypothesis; blast radius)
- Percentiles: why p95/p99 matter more than a mean; nearest-rank vs interpolated
- Graceful degradation, failure isolation, non-load-bearing side channels

**Distributed-systems reasoning**
- Idempotency and deduplication strategies
- Backpressure and bounded queues
- Failure isolation / bulkheads
- Cache-aside; cache invalidation
- Why retrying a non-idempotent operation is dangerous (the `ReadTimeout` decision)

### Tier 3 — ML / LLM specifics

- **Embeddings**: what they are, dimensionality, task types, cosine similarity vs Euclidean, and why
  you normalize first
- **RAG**: chunking strategies, top-k retrieval, relevance thresholds, grounding, why "I don't know"
  is the correct answer below threshold
- **DBSCAN**: `eps`, `min_samples`, the noise label, density-reachability; vs k-means (needs k, no
  noise) and vs hierarchical clustering; precomputed distance matrices
- **LLM-as-judge**: prompt design for strictness, structured/JSON output with a response schema,
  `temperature=0` for determinism, judge model selection, and the known bias/reliability limits of
  the technique
- Token-based cost modeling; rate limits (RPM vs RPD) and quota semantics
- Agent architectures: ReAct-style tool use, multi-agent pipelines (planner/researcher/verifier/
  synthesizer), memory/state management across turns
- Non-determinism in evaluation and how you get a stable signal out of it

### Tier 4 — supporting

- Docker: multi-stage builds, layer caching, image secret hygiene, healthchecks, `depends_on:
  condition: service_healthy`
- nginx: prefix `location` matching precedence, `proxy_pass`, `try_files` SPA fallback, upstreams
- ClickHouse: MergeTree, ORDER BY as primary index, partitioning, columnar compression, why
  append-only workloads suit it
- PgBouncer: session vs transaction vs statement pooling; interaction with app-side pools
- GitHub Actions: jobs/steps, secrets, `permissions:`, the Checks API, required status checks and
  branch protection
- Python packaging: `pyproject.toml`, extras, entry points, explicit `packages`, editable installs
- pytest: markers, fixtures, `conftest.py`, parametrization, unit-vs-integration separation
- React: hooks, TanStack Query (server state vs client state), React Router, context; Vite; TypeScript
  generics and generated API types
- ADRs: what belongs in one, and why a "review trigger" is the most useful field

### Reading order if time is short

1. Kafka consumer groups + delivery semantics + consumer lag
2. `SKIP LOCKED`, SQLAlchemy session lifecycle, transaction isolation
3. JWT + refresh rotation + reuse detection; bcrypt vs SHA256
4. Redis sorted-set rate limiting + `SET NX EX` + Lua atomicity
5. SLO / error budget / chaos engineering / p95–p99
6. KEDA vs HPA and the I/O-bound scaling argument
7. Embeddings + cosine similarity + DBSCAN
8. The three observability pillars

---

## Appendix — Quickstart (for a live demo)

```bash
# 1. Infrastructure
docker compose up -d

# 2. Schema, seed, topics, ClickHouse
alembic upgrade head
python -m apps.api.scripts.seed
python -m apps.api.scripts.create_api_key        # save the printed key as $API_KEY
python -m apps.api.scripts.init_topics
python -m apps.api.scripts.init_clickhouse

# 3. API (terminal 1)
python -m uvicorn apps.api.main:app --port 8000

# 4. Eval worker (terminal 2)
python -m apps.api.workers.eval_worker_v2

# 5. CLI
pip install -e .
agentbench login --base-url http://localhost:8000 --api-key "$API_KEY"
agentbench init --agent rag-agent --entrypoint agents.rag_agent.agent:run_turn
agentbench push-suite eval-suites/rag-agent/baseline.yaml
agentbench register-version --version-label v1 --model gemini-2.5-flash
agentbench run --suite baseline

# Tests
pytest -m unit           # 218 tests, no infra
pytest -m integration    # 83 tests, needs docker compose

# Kubernetes
make cluster-up && make images-build && make images-import && make helm-install
```

Bring-your-own-agent (no Python, no RedLine import — one HTTP endpoint):

```bash
python examples/http-agent/server.py           # reference impl on :9100

agentbench init --agent my-agent --entrypoint http://localhost:9100/turn
agentbench register-version --version-label v1 --model my-model \
    --content-hash "$(git rev-parse HEAD)"     # explicit: RedLine can't read remote source
```

The eval engine, every scorer, and the gate never learn the difference.
