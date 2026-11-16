# RedLine Onboarding

Read this first. Then [RUNNING.md](RUNNING.md) to start the stack and [DEMO_GUIDE.md](DEMO_GUIDE.md) to present it.

Everything here was checked against this tree (branch `feat/reliability-on-phase2`, base commit `7e17127 "latest"`). Items marked **UNVERIFIED** were not re-checked.

## 1. What RedLine is

RedLine treats an AI agent like a deployable service. It blocks a bad agent from shipping the way a failing CI check blocks a bad commit.

| Concept | Meaning |
|---|---|
| **ARS** (Agent Reliability Score) | `0.4*correctness + 0.2*safety + 0.2*latency + 0.2*cost`, per eval run. |
| **Error budget** | SRE-style. Target ARS 0.90; if too many of the last 5 runs fall below it (allowed breach rate 10%), deployments are FROZEN. |
| **Gate** | Pass/fail verdict per run with human-readable reasons. Default policy: pass_rate >= 0.90, ARS >= 0.85, error budget not exhausted. |
| **Drift** | Detectors on pass-rate and behaviour; "silent drift" = code hash unchanged but behaviour changed (a provider updated the model). |
| **Behavioural diff** | Compares two versions' answers per case by embedding similarity (threshold 0.90). Classes: NO CHANGE, EXPECTED CHANGE, SAFE REFACTOR, SILENT DRIFT. |
| **Chaos** | Fault injection (timeout, wrong data, malformed response) to test recovery. |
| **Load test** | N virtual users for T seconds: p50/p95/p99, error rate, cost per hour, 10x/100x projection. |
| **Failure mining** | Clusters recurring failures, proposes regression test cases (candidates) that a human approves or rejects. |

## 2. Architecture as it is in this tree

```
Browser :5173 (Vite dev) --proxy--> API :8000  (monolith apps/api/main.py, all routers)
CLI / CI (apps/cli, httpx only) ----^
API --> Postgres :5433   (tenants, agents, runs, gates, drift, diffs, load, mining)
API --> Redis :6379      (rate limiter, daily quota)
API --> Redpanda :19092  (job topics) --> eval_worker_v2 (eval jobs), load_worker (load jobs)
workers/API --> ClickHouse :8123 (per-case traces)
drift_scheduler (APScheduler) runs model-drift checks
```

- **Dev / demo (what RUNNING.md starts):** one monolith FastAPI app on :8000 includes every router. `docker-compose.demo.yml` runs only Postgres, Redis, Redpanda and ClickHouse (containers `redline_demo_*`). API, eval worker, load worker and Vite run on the host.
- **Full deploy (not exercised in this work):** nginx gateway (8085, or :8000 on k3d), `apps/eval_service` :8001, `apps/agent_service` :8002, `apps/gate_service` :8003, Helm chart in `helm/redline`, KEDA scales the worker on Redpanda lag (Makefile targets `cluster-up`, `deploy`, ...). Route ownership is fixed by `.claude/rules/architecture.md` (`/dashboard` belongs to gate_service, `/agents` to agent_service, `/eval-runs /ci /auth /diff-runs /load-runs /mining` to eval_service).

## 3. Repo map

| Path | What |
|---|---|
| `apps/api/` | FastAPI monolith: `routers/`, `services/` (eval_engine, ars_engine, gate_engine, diff_engine, load_engine, mining, drift, scorers, adapters), `workers/`, `models/`, `schemas/`, `migrations/`, `tests/` |
| `apps/cli/` | `agentbench` CLI (login, init, push-suite, register-version, run, ci-check, diff, load, mine). HTTP only. |
| `apps/dashboard/` | React + Vite + Tailwind SPA (this work). |
| `apps/eval_service`, `agent_service`, `gate_service` | Decomposed services for the full deploy. |
| `agents/`, `eval-suites/` | Sample agents + their suites. `rag_agent` needs a Gemini key; `demo_support_agent` and `demo_research_agent` are key-free. |
| `scripts/` | `redline.ps1` (launcher), `seed_demo.py`, `k6/` |
| `helm/`, `infra/`, `docker-compose*.yml`, `Makefile` | Deployment |
| `docs/` | Teammate docs (architecture-roadmap, status, proof-of-value, ci-demo, adr/, infra-hardening) plus ONBOARDING / RUNNING / DEMO_GUIDE and `demo/` screenshots |
| `.claude/rules/` | Project rules (section 5) |

## 4. What the dashboard work added (all uncommitted in this worktree)

Verified with `git status`: the teammate's commits are untouched; the following are modified (M) or new (??).

- **Frontend, `apps/dashboard/src/`:** pages `DashboardPage`, `AgentsListPage`, `AgentDetailPage`, `RunDetailPage`, `TraceViewerPage`, `DiffsListPage`, `DiffViewerPage`, `EvalRunsListPage`, `LoadTestsListPage`, `LoadTestReportPage`, `SettingsPage`, `LoginPage`, `RegisterPage`, `OnboardingPage`; components (ARSRing, AgentHealthHeader, ArsTrendChart, ArsBreakdownBars, FailureClustersTab, LoadTestsTab, CaseResultRow, SimilarityBar, GateBadge, AlertStrip, ...); hooks (`useRuns`, `useDiffs`, `useApiKeys`, `usePlatformSummary`, `useTheme`, ...); `lib/theme.tsx`.
- **Backend:** changes in `routers/dashboard.py`, `diff.py`, `mining.py`, `auth.py`, `schemas/dashboard.py`, `schemas/diff.py`, `models/api_key.py`, `core/config.py`, `services/embeddings.py`, `services/scorers/llm_judge.py`; migration `0011_add_api_key_display_columns.py`; endpoint tests in `apps/api/tests/api_endpoints/`.
- **Demo tooling:** `scripts/seed_demo.py`, `scripts/redline.ps1`, `docker-compose.demo.yml`, key-free agents `agents/demo_support_agent`, `agents/demo_research_agent` with suites `eval-suites/demo-*`.
- **Reused from the earlier standalone branch `feat/dashboard-and-reliability` (GitHub):** the dashboard SPA and the dashboard/diff/mining API work were carried onto the teammate's up-to-date tree rather than rewritten. **UNVERIFIED:** the exact commit-level split between "carried" and "newly written" was not audited.

## 5. Project rules (`.claude/rules/`)

- Python **3.10 target** (no `tomllib`, `ExceptionGroup`, `TaskGroup`). The local `.venv` is 3.12.4, so CI/rules are stricter than your machine.
- **Sync SQLAlchemy 2.0** (`Session`, `select()`), never `AsyncSession`. Eval engine, scorers, gate engine and workers are synchronous (`confluent-kafka` is sync).
- Pydantic v2 API; UUID PKs with `server_default=gen_random_uuid()`; every endpoint has `response_model`.
- `emit_trace()` must never raise (wrap in try/except). `_compute_gate_result()` stays a pure function.
- `JobQueue.publish` / `get_status` signatures are a stable contract.
- Credentials: API keys `rl_live_` + SHA256 hash stored, shown once; bcrypt passwords; JWT HS256 with `type` claim; never log keys.
- CLI is HTTP-only. No hardcoded model names in agents (`get_profile()`).
- Tests need `pytestmark = pytest.mark.unit` or `integration`.

## 6. Known issues

| # | Issue | Status |
|---|---|---|
| 1 | Chaos mode `malformed_response` inserts `\x00`, which Postgres JSONB rejects (teammate bug) | Reported to us; not reproduced here. Seed avoids it. |
| 2 | `init_clickhouse` creates tables in `default`, not `redline` (teammate bug) | Reported; the seed works around it. |
| 3 | Suite flag `chaos: true` has no effect; chaos only happens via `expectations.chaos` per case | Reported; not re-tested. |
| 4 | `rag-agent` live runs need a Gemini key (`GEMINI_API_KEY`) | Verified by design: seeded rag history is scripted, live rag runs are not key-free. |
| 5 | **Live load test on a demo agent gives absurd numbers.** A 10-user/10s run reported 3,408,202 requests, 339,281 req/s, $73,284.82/hour. The demo agents answer in-process in microseconds. | Seen in rehearsal. Do not show a live load run to the panel; use the seeded rag 50-user report. |
| 6 | Charts/ring animate slowly: ARS ring and ARS Trend lines take roughly 5-7 s to finish drawing after the page loads | Seen. Pause before talking over them. |
| 7 | Load report p95 SLO label ("200ms") is clipped behind the p99 bar | Seen, cosmetic. |
| 8 | "Use the demo account" only prefills the form; you must then click Sign in | Seen. |
| 9 | Revoking an API key happens immediately with no confirmation dialog | Seen. |
| 10 | Older `rag-agent` runs list ARS 1.000 beside a FAIL gate | Seen in the Recent Runs table; cause not investigated (**UNVERIFIED**). |
| 11 | TanStack Query devtools button shows (bottom-right) in `npm run dev` | Seen; dev only. Screenshots hide it. |
| 12 | Vite console shows `404 .../FailureClustersPage.tsx` HMR error | Stale HMR from a deleted file (git shows it deleted, replaced by `FailureClustersTab`); harmless after reload. |
| 13 | `docs/ci-demo.md` says screenshots are "in this directory" but no images exist under `docs/` in this tree | Seen. The text narrative and log excerpt are present. |
| 14 | `docs/status.md` still says Phase 5.3 "Dashboard v2" is not started | Stale relative to this work. |
| 15 | `.env.example` lists `ANTHROPIC_API_KEY` while config uses `llm_provider="gemini"` / `gemini_api_key` | Seen in files; harmless. |

## 7. How to contribute

1. Branch off `feat/reliability-on-phase2` (or the teammate's main line); never work in `C:\Users\arjun\agentic\RedLine` from this task.
2. **Routing trap:** the SPA uses `/agent` and `/agent/:id`. The API owns `/agents`, and Vite proxies the `/agents` prefix to the API. A SPA route named `/agents` would be sent to the backend. Do not rename the SPA routes.
3. **Migrations:** Alembic, files in `apps/api/migrations/versions/`. The latest is `0011`; the next must be `0012_*` with `down_revision` pointing to 0011. Run `.venv\Scripts\python -m alembic upgrade head`.
4. **Tests:** `pytest -m unit` runs anywhere. `pytest -m integration` needs the compose stack (Postgres, Redis, ...) and, for LLM cases, a Gemini key. Frontend: `npm test` (vitest) in `apps/dashboard` (**UNVERIFIED** in this pass).
5. Follow section 5. Keep demo seed data deterministic. After changing anything the demo shows, re-seed and re-take `docs/demo/` screenshots.
6. Never commit `.env`, API keys, or JWT secrets.
