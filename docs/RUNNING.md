# Running RedLine

This guide covers running the stack with Docker (recommended), running it locally without Docker, running the tests, and troubleshooting. Commands are shown for Windows PowerShell; the Bash equivalents work the same way on macOS/Linux.

Services (from `docker-compose.yml`):

| Service     | Purpose                                              | Host port        |
|-------------|------------------------------------------------------|------------------|
| `postgres`  | PostgreSQL 16 (alpine), volume `redline_pg_data`     | 5433 -> 5432     |
| `migrate`   | One-shot `alembic upgrade head`                      | none             |
| `api`       | FastAPI (`apps.api.main:app`)                        | 8000             |
| `worker`    | Eval / diff / load job worker                        | none             |
| `dashboard` | Vite build served by nginx                           | 8080 -> 80       |

## Quick start (Docker)

1. Create the config file (first time only):

   ```powershell
   copy .env.example .env
   ```

   Then replace `JWT_SECRET_KEY` with a long random value. The API refuses to boot with a weak signing key (see `validate_jwt_secret` in `apps/api/core/security.py`).

2. Start the stack. This builds the images and waits for health checks:

   ```powershell
   powershell -File scripts/redline.ps1 up
   ```

3. Seed the demo workspace (safe to re-run; `--reset` wipes all tables first):

   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg2://redline:redline_dev_password@localhost:5433/redline"
   python -m scripts.seed_demo --reset
   ```

   The bash form is `DATABASE_URL=postgresql+psycopg2://redline:redline_dev_password@localhost:5433/redline python -m scripts.seed_demo --reset`.

4. Verify:

   ```powershell
   powershell -File scripts/redline.ps1 verify
   ```

   `verify` checks `GET /health`, `GET /ready`, demo login, `GET /dashboard/summary`, the dashboard on http://localhost:8080, and runs one smoke eval on `stateful-support-agent` (up to 120 s). It prints PASS/WARN/FAIL per check and exits 1 on any FAIL. A WARN on demo login means the seed step was skipped.

Demo login: **demo@redline.dev / DemoPass123!**

Other `redline.ps1` actions: `status`, `logs` (add `-Service api` and `-Tail 200`), and `down`. `down -Purge` deletes the Postgres volume and all data; it asks you to type `PURGE` first.

## Local mode (no Docker)

```powershell
powershell -File scripts/redline.ps1 up -Mode local
powershell -File scripts/redline.ps1 verify -Mode local
```

What `up -Mode local` does, in order:

1. If the `DATABASE_URL` in `.env` is reachable, it uses that database. Otherwise it runs `scripts/dev_db.py`, which starts an embedded Postgres 16 (`pgserver`) with data in `.pgdata/` and writes `DATABASE_URL` into `.env`. It also sets `JWT_SECRET_KEY` only if the key is missing; a placeholder already in `.env` is kept, so replace it yourself.
2. Runs `python -m alembic upgrade head`.
3. Starts the API (uvicorn on port 8000) and the worker as hidden background processes. PIDs are in `.run/*.pid`, logs in `.run/*.log` and `.run/*.err.log`.
4. Waits up to 60 s for `/health`.

It does **not** start the dashboard. Start it yourself, and `verify -Mode local` expects it on port 5173:

```powershell
cd apps/dashboard; npm ci; npm run dev
```

Stop local processes with `powershell -File scripts/redline.ps1 down -Mode local`. The embedded Postgres keeps running after `down` (data stays in `.pgdata/`); `-Purge` is ignored in local mode, so delete `.pgdata/` by hand if you want a clean slate.

For a manual setup without the script, see `scripts/dev_db.py`, then run `python -m alembic upgrade head`, `python -m uvicorn apps.api.main:app --port 8000`, `python -m apps.api.workers.eval_worker`, and the dashboard `npm run dev`.

### Native Postgres (optional)

If you already run Postgres 16 on the host, point `DATABASE_URL` in `.env` at it (for example port 5432). `redline.ps1 up -Mode local` reuses any reachable database from `.env`. The test harness also uses a native server on `localhost:5432` automatically when one is reachable (see Running tests). The compose stack does not use it: compose publishes its own Postgres on 5433.

## Environment variables

Read by the API and worker through `apps/api/core/config.py` (pydantic settings, case-insensitive) and by compose. Defaults are the values in code.

| Variable | Default | Used by | Notes |
|---|---|---|---|
| `POSTGRES_USER` | `redline` | compose | Role created on first volume init |
| `POSTGRES_PASSWORD` | `redline_dev_password` | compose | Changing it later needs `down -v` or `ALTER ROLE`. URL-encode special characters |
| `POSTGRES_DB` | `redline` | compose | Database created on first volume init |
| `POSTGRES_HOST`, `POSTGRES_PORT` | `localhost`, `5433` | host reference | Host-side access to compose Postgres |
| `DATABASE_URL` | `postgresql+psycopg2://redline:redline_dev_password@localhost:5433/redline` | API, worker, scripts | Containers override it to host `postgres`, port 5432 |
| `JWT_SECRET_KEY` | placeholder in `.env.example` | API | Required. Replace the placeholder; API refuses weak keys |
| `JWT_ALGORITHM` | `HS256` | API | |
| `JWT_EXPIRE_MINUTES` | `1440` | API | |
| `CORS_ORIGINS` | `http://localhost:5173,...,http://localhost:8080,...` (in `.env.example`) | API | Comma-separated. Code default lists only 5173 origins |
| `VITE_API_URL` | `http://localhost:8000` | dashboard build | Baked into the bundle at build time; rebuild the image after changing it |
| `LLM_PROVIDER` | `gemini` | API | |
| `GEMINI_API_KEY` | empty | RAG agent, `llm_judge` scorer | Needed for `rag-agent` live runs and the LLM-judge tests |
| `GITHUB_TOKEN` | empty | `agentbench ci-check` | Only used inside GitHub Actions |
| `WORKER_POLL_SECONDS` | `2.0` | worker | Sleep between queue polls when idle |
| `JOB_TIMEOUT_SECONDS` | `600` | worker | Child process is killed after this |
| `JOB_STALE_SECONDS` | `120` | worker | Heartbeat age after which a job is reaped |

`POSTGRES_HOST` and `POSTGRES_PORT` appear only in `.env.example` and are not read by any code; `redline.ps1` parses `DATABASE_URL` instead. `GROQ_API_KEY` and `OLLAMA_BASE_URL` are read by `config.py` with defaults but are not listed in `.env.example`.

## Reliability model

**Health vs readiness**

- `GET /health` is liveness only: the process is up. It does not touch the database. The compose `api` healthcheck uses it.
- `GET /ready` returns 200 `{"status":"ready"}` only when the database answers `SELECT 1` and the schema revision equals the Alembic head. Otherwise it returns 503 (`database unreachable` or `database schema is not at head; run alembic upgrade head`). Use it before sending traffic.

**Startup order (compose)**: `postgres` (healthy via `pg_isready`) -> `migrate` (completes successfully) -> `api` and `worker`; `dashboard` waits for `api` to be healthy. `docker compose up --wait` blocks until these are ready.

**Worker job handling** (`apps/api/workers/eval_worker.py`, `apps/api/core/jobqueue.py`)

- Jobs are claimed with `SKIP LOCKED`. Types: `eval.requested`, `diff.requested`, `load.requested`.
- Each job runs in a `spawn` child process, so a hang, crash or OOM cannot take the worker down.
- **Timeout**: the parent kills the child after `JOB_TIMEOUT_SECONDS` (default 600) with terminate, then kill.
- **Heartbeat**: the parent updates `heartbeat_at` every 10 s (constant `HEARTBEAT_SECONDS`, not configurable).
- **Stale-job reaper**: runs every 30 s (constant `REAP_INTERVAL_SECONDS`) and also finds `in_progress` jobs whose heartbeat is older than `JOB_STALE_SECONDS` (default 120). Each one is routed through the retry logic.
- **Retries**: `max_attempts` defaults to 3. A failed or reaped job goes back to `pending` with `available_at = now + 5 * 2^attempts` seconds (exponential backoff); after the last attempt it is `failed`. The domain row (eval/diff/load run) is synced to `pending` or `failed`.
- **Idempotent handlers**: a completed run is a no-op; partial results from an interrupted attempt are deleted before re-running.
- **Shutdown**: SIGTERM/SIGINT stop claiming new jobs; the current job finishes. Compose gives the worker `stop_grace_period: 60s`.

**Restart policy**: `postgres`, `api`, `worker` and `dashboard` use `restart: unless-stopped`. `migrate` uses `restart: "no"`. Docker does not auto-restart a container you stopped manually; `docker kill` counts as a manual stop, so the service stays down until you start it again (`docker compose up -d` or `redline.ps1 up`).

## Running tests

```powershell
pip install -r apps/api/requirements-dev.txt
pytest apps/api/tests -q
```

Test database selection (`apps/api/tests/conftest.py`), in order:

1. `TEST_DATABASE_URL`, if set. CI sets it to `postgresql+psycopg2://postgres:postgres@localhost:5432/redline_test`.
2. A native Postgres at `localhost:5432` (user `postgres`, password `redline_dev_password`), if reachable.
3. The embedded `pgserver` from `scripts/dev_db.py`, with the database name replaced by `redline_test`.

The harness creates `redline_test` if missing, runs `alembic upgrade head` once per session, and truncates every table except `alembic_version` around each test. It refuses to run against a database named `postgres`. Tests never touch the dev database.

Tests marked `requires_llm` are skipped when `GEMINI_API_KEY` is not set. The number of skipped tests depends on the suite and was not verified here; check the pytest summary.

**Do not run two pytest sessions at once against the same test database.** Each session truncates all tables at start and after each test, so concurrent runs will corrupt each other's results. Use a different `TEST_DATABASE_URL` database name per concurrent run if you need parallelism.

## Dashboard development

`apps/dashboard/package.json` scripts:

| Script | Command | Use |
|---|---|---|
| `npm run dev` | `vite` | Dev server, http://127.0.0.1:5173 |
| `npm run build` | `tsc -b && vite build` | Production bundle to `dist/` |
| `npm run typecheck` | `tsc -b` | Type check only |
| `npm run lint` | `oxlint` | Lint |
| `npm run preview` | `vite preview` | Serve the built bundle |

Run `npm ci` (not `npm install`) to match `package-lock.json`. Node 20 is used in CI.

## CI

`.github/workflows/ci.yml` runs on pushes to `main` and on pull requests:

- **api-tests** (ubuntu, Python 3.11, native Postgres 16 service): `pip install -r apps/api/requirements-dev.txt`, then `pytest apps/api/tests -q`.
- **dashboard** (Node 20): `npm ci`, `npm run typecheck`, `npm run build`.
- **docker-build**: `docker compose build`.

CI does not run `scripts/redline.ps1 verify` or the seed script.

## Troubleshooting

**Antivirus re-signs HTTPS (TLS errors in pip, npm or Docker builds)**

- Export the root certificate from the Windows certificate store as a PEM and place it in `certs/` (for example `certs/winca.pem`, which is already in this repo). The API image's Dockerfile installs every `certs/*.pem` into its trust store at build time. The dashboard Dockerfile does **not** do this, so a dashboard image build behind such an antivirus may still fail; this was not tested.
- For local (non-Docker) runs, set `PIP_CERT` and `NODE_EXTRA_CA_CERTS` to that PEM, for example `$env:PIP_CERT = "C:\path\to\cert.pem"`. (These variable names come from the project's existing notes; they are not read by any repo script.)
- `winget` with `msstore` source certificate errors: use `winget --source winget ...`. (From project notes; not verified in repo files.)

**Docker daemon not running**: `redline.ps1` reports "docker.exe not found" only if Docker Desktop is not installed. If it is installed but the engine is down, `docker compose` fails. Start Docker Desktop, wait for it to report running, then retry.

**Ports 8000, 8080 or 5433 already in use**: find the owner with `netstat -ano | findstr :8000` and stop it, or change the host side of the mapping in `docker-compose.yml`. Local mode refuses to start the API if port 8000 is held by something other than the RedLine API process.

**Changing `POSTGRES_PASSWORD` does not take effect**: compose creates the role only on first volume initialization. Either run `powershell -File scripts/redline.ps1 down -Mode docker -Purge` (deletes all data; type `PURGE`), or `ALTER ROLE` inside the container. Also update `DATABASE_URL` to match.

**`/ready` returns 503 "schema is not at head"**: run `python -m alembic upgrade head` (local) or `docker compose run --rm migrate`.

**Dashboard shows the wrong API URL**: `VITE_API_URL` is baked into the bundle at build time. After changing it, rebuild: `docker compose build dashboard` then `docker compose up -d dashboard`.

**Demo login fails / verify shows WARN**: run the seed step (`python -m scripts.seed_demo --reset`) with the `DATABASE_URL` shown in Quick start.

**`rag-agent` runs fail or the LLM judge fails**: set `GEMINI_API_KEY` in `.env` and restart the API and worker. With no key, the LLM judge fails the case rather than passing it.

## Notes

- `stateful-support-agent` and `research-pipeline-agent` need no API key, so Run Eval / Diff / Load Test work out of the box. `rag-agent` calls Gemini.
- Seeded data is scripted (agent replies and judge verdicts) but runs through the real scorers, ARS, drift, diff and mining engines.
