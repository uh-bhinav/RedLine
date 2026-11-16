# RedLine onboarding

Start here if you are new to this branch. It explains what RedLine is, **what changed since "phase 1"**, and how to get it running in about ten minutes. For day-to-day operations (env vars, reliability model, troubleshooting) see [RUNNING.md](RUNNING.md).

## 1. What RedLine is

RedLine (CLI name `agentbench`) is a **CI gate for AI agents**. You write eval suites in YAML; RedLine runs your agent against them, scores the transcripts, and **blocks a deploy or pull request** if reliability regresses. Beyond pass/fail it tracks:

| Concept | Meaning |
|---|---|
| **ARS** (Agent Reliability Score) | `0.4*correctness + 0.2*safety + 0.2*latency + 0.2*cost`, per run, 0-1. Target 0.9. |
| **Error budget** | Over the last 5 runs, more than 2 below target = *frozen* (deploys blocked). 1-2 = *at risk*. |
| **Gate** | Pass rate >= 0.90, ARS >= 0.85, and error budget not exhausted (plus optional cost/latency policy). |
| **Drift alerts** | ARS drops > 0.10 below its rolling baseline, typed `model` / `prompt` / `metric`. |
| **Behavioural diff** | Compares what two versions *said*, classified `no_op`, `safe_refactor`, `expected_change` or `silent_drift`. |
| **Load test** | Concurrent users replaying a suite: p50/p95/p99, error rate, throughput, cost per hour. |
| **Failure mining** | Clusters recurring failing prompts (TF-IDF + DBSCAN) and proposes them as new test cases. |

## 2. What changed on this branch

The repository started as **phase 1** (FastAPI + Postgres job queue + gate engine + CLI + one RAG agent). This branch adds the dashboard, the backend it needs, and the reliability work.

### Frontend (new): `apps/dashboard`
React 19, Vite 8, TypeScript, Tailwind 3.4, Radix primitives, React Query, Recharts, Framer Motion.
Pages: login, register, 3-step onboarding (generates a real API key), dashboard home, agents list, agent detail (ARS ring, error budget, drift, 5 tabs), run detail (gate verdict hero, ARS breakdown, transcripts), diff viewer, load-test report, trace timeline, settings (API keys, theme), plus global list pages. Light/dark theme, mobile layout.

### Backend (new and changed): `apps/api`
- **Auth:** register/login with JWT, API keys (create / list masked / revoke), roles `viewer < developer < admin`. Dashboard uses JWTs; the CLI and CI keep using API keys.
- **Tenant isolation:** every dashboard, run, diff, load and mining query is scoped to the caller's tenant. `/eval-runs` previously had no auth and picked the first tenant.
- **New endpoints:** `/auth/*`, `/dashboard/*` (summary, agents, runs, traces, ars-history), `/diffs`, `/load-runs`, `/mining/*`, `/eval-suites`.
- **New engines** (`apps/api/services`): `ars_engine`, `drift_engine`, `diff_engine`, `load_engine`, `mining_engine`. The gate now also enforces the ARS floor and the error budget.
- **Migrations:** `0003` (analytics tables, API-key label, chaos flag) and `0004` (job reliability columns).
- **Hardening:** `/health` (liveness, no DB) and `/ready` (DB + schema at head); one consistent error body `{"error": {code, message, request_id}, "detail": ...}`; request IDs; input limits; the API refuses to boot with a JWT secret under 32 characters; the LLM judge no longer crashes the app without a key and **fails closed** (a case it cannot judge fails).

### Worker reliability: `apps/api/workers/eval_worker.py`
Each job runs in a spawned child process with a timeout (default 600 s). The parent heartbeats; a **reaper** requeues jobs whose heartbeat is stale (default 120 s); failures retry up to 3 times with exponential backoff; SIGTERM finishes the current job and stops claiming. The worker handles `eval.requested`, `diff.requested` and `load.requested`.

### Agents and suites
Two new key-free demo agents, `stateful_support_agent` and `research_pipeline_agent`, so evals, diffs and load tests run without any LLM key. The RAG suite grew from 3 to 6 cases (including a chaos/prompt-injection case). `rag-agent` still needs a Gemini key to run live.

### Infrastructure and tooling
- `docker-compose.yml` runs Postgres 16, a one-shot migrate, API, worker and dashboard, with health checks, restart policies and a named volume. Dockerfiles for the API and dashboard.
- `scripts/redline.ps1`: one entrypoint (`up | down | status | logs | verify`, `-Mode docker|local`).
- `scripts/seed_demo.py`: demo workspace with history, drift, diffs, load runs and clusters.
- `scripts/dev_db.py`: embedded Postgres for machines without Docker.
- `.github/workflows/ci.yml`: backend tests, dashboard typecheck + build, and `docker compose build`.
- `pyproject.toml`: `pip install -e .` provides the `agentbench` command.
- Tests: 181 pass (auth, tenant isolation, dashboard, ARS, diffs, mining, gate, worker process paths), on a throwaway database that never touches dev data.

### Fixes to phase-1 issues
`.env.example` named the wrong LLM key (Anthropic vs Gemini); `requirements.txt` was missing most dependencies; the compose healthcheck used a host-side variable; `/eval-runs` had no auth; the API crashed on startup without a Gemini key.

## 3. Prerequisites

| Tool | Needed for |
|---|---|
| Docker Desktop (with the daemon running) | Docker mode (recommended) |
| Python 3.11+ | seeding the demo, local mode, tests, the CLI |
| Node 20+ | dashboard development only (Docker builds it for you) |
| Git | cloning |

No Docker? Local mode starts an embedded Postgres for you (`pgserver`), so a native Postgres install is **not required**.

## 4. Get it running (Docker, recommended)

```powershell
git clone https://github.com/uh-bhinav/RedLine.git
cd RedLine
git checkout <this-branch>

copy .env.example .env
# edit .env: set JWT_SECRET_KEY to a long random value, e.g.
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt

powershell -File scripts/redline.ps1 up          # build + start everything, waits until healthy

$env:DATABASE_URL = "postgresql+psycopg2://redline:redline_dev_password@localhost:5433/redline"
python -m scripts.seed_demo --reset              # demo data

powershell -File scripts/redline.ps1 verify      # expects OVERALL: PASS
```

Then open:

| URL | What |
|---|---|
| http://localhost:8080 | Dashboard |
| http://localhost:8000/docs | API docs |
| http://localhost:8000/ready | Readiness |

**Demo login:** `demo@redline.dev` / `DemoPass123!` (the login page has a "Use the demo account" shortcut).

Stop with `powershell -File scripts/redline.ps1 down`. `down -Purge` also deletes the database volume and asks for confirmation.

On Mac/Linux, run the same `docker compose` commands directly (`docker compose up -d --build --wait`) and use `source .venv/bin/activate`; `redline.ps1` is PowerShell only.

## 5. Get it running (no Docker)

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt pgserver
pip install -e .                                  # installs the `agentbench` CLI

powershell -File scripts/redline.ps1 up -Mode local   # embedded Postgres, migrations, API, worker
python -m scripts.seed_demo --reset
cd apps/dashboard; npm ci; npm run dev                # http://127.0.0.1:5173
```

`redline.ps1 up -Mode local` does not start the dashboard dev server. `down -Mode local` stops the API and worker; the embedded Postgres keeps running and its data lives in `.pgdata/`.

## 6. Try the product (five-minute tour)

1. **Dashboard:** four stat cards, active alerts (rag-agent budget frozen, a silent-drift diff), agents table with ARS.
2. **rag-agent -> latest run:** big GATE FAILED banner with three reasons (pass rate, ARS, error budget), ARS breakdown, expandable cases with transcripts.
3. **rag-agent -> ARS Trend tab:** score dipping below the 0.9 target line after the v2 model change.
4. **Diffs -> the SILENT DRIFT one:** same code, different behaviour.
5. **rag-agent -> Failure Clusters tab:** mined clusters; approve or reject candidates.
6. **stateful-support-agent -> Run Eval:** a live job through the worker, no API key needed.

## 7. Use the CLI

```powershell
agentbench login --base-url http://localhost:8000 --api-key <key from Settings -> API Keys>
agentbench init --agent my-agent --entrypoint agents.my_agent.agent:run_turn
agentbench push-suite eval-suites/rag-agent/baseline.yaml
agentbench register-version --version-label v1
agentbench run --suite baseline
```

`agentbench ci-check` is for GitHub Actions only; it creates the Check Run and exits non-zero when the gate fails.

## 8. Develop and test

```powershell
# backend tests (needs a reachable Postgres: native :5432, TEST_DATABASE_URL, or the embedded one)
python -m pytest apps/api/tests -q

# dashboard
cd apps/dashboard; npm run typecheck; npm run build
```

Rules that will save you time:
- **Never run two pytest sessions at once**; they share one `redline_test` database and truncate it between tests.
- Tests never touch the dev or Docker database; `conftest.py` refuses a database named `postgres`.
- `GEMINI_API_KEY` unset means 3 LLM-judge tests skip; that is expected.
- Schema changes need an Alembic migration in `apps/api/migrations/versions/`.
- Dashboard API types live in `apps/dashboard/src/lib/types.ts` and are hand-maintained: update them when `apps/api/schemas/dashboard.py` changes.

## 9. Known gaps (read before relying on it)

- Only the unit/integration suite and a Docker `verify` were run. `-Mode local` and the GitHub Actions workflow have **not** been exercised end to end.
- Test coverage is thin for `load_engine`, `drift_engine` and the `scripts/` folder.
- The seeded demo data is scripted (agent replies and judge verdicts); the scoring, ARS, drift, diff and mining logic over it is real.
- The default `JWT_SECRET_KEY` in `.env.example` is a placeholder that passes the length check but is **not secure**. Replace it.
- A worker killed with `docker kill` is treated as a manual stop and is not restarted automatically; a genuine crash restarts under `unless-stopped`.
- Behind an antivirus that re-signs HTTPS, pip/npm/Docker builds can fail TLS verification. See the Troubleshooting section of RUNNING.md.
- Roadmap items such as Redpanda, sandboxed agent execution and an HTTP agent adapter are **not** built.

## 10. Where things live

```
apps/api/            FastAPI app: routers/, services/ (engines), models/, schemas/, workers/, migrations/, tests/
apps/dashboard/      React dashboard (src/pages, src/components, src/hooks, src/lib)
apps/cli/            the `agentbench` CLI
agents/              demo agents (rag, stateful_support, research_pipeline)
eval-suites/         YAML eval suites per agent
scripts/             redline.ps1, seed_demo.py, dev_db.py
docs/                RUNNING.md, ONBOARDING.md, demo screenshots
.github/workflows/   CI
```
