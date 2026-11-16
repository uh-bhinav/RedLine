# Running RedLine locally (Windows)

Companion docs: [ONBOARDING.md](ONBOARDING.md) (what/why) and [DEMO_GUIDE.md](DEMO_GUIDE.md) (presenting).
This is the exact path that was used and verified on Windows 11 with Docker Desktop, PowerShell 5.1, Python 3.12.4 and Node v26.13.0.

## 1. Prerequisites

- **Docker Desktop** (running). Docker CLI lives in `C:\Program Files\Docker\Docker\resources\bin`; `scripts\redline.ps1` adds it to PATH for you, but your own shell may not have it.
- **Python 3.10+** (project targets 3.10; 3.12 works locally).
- **Node.js + npm** (for `apps/dashboard`).
- Ports free: 5433 (Postgres), 6379 (Redis), 19092 (Redpanda), 8123 and 9000 (ClickHouse), 8000 (API), 5173 (Vite).

## 2. First-time setup

Run everything from the repo root, e.g. `C:\Users\arjun\agentic\RedLine-phase2`.

### 2.1 Antivirus / TLS interception workaround (only if pip or npm fail with certificate errors)

Export the Windows certificate store to a PEM file and point the tools at it (the exact PEM export command was not captured; any export of the trusted-roots store to PEM works):

```powershell
$env:PIP_CERT = "C:\path\to\windows-roots.pem"
$env:NODE_EXTRA_CA_CERTS = "C:\path\to\windows-roots.pem"
```

### 2.2 Python environment

```powershell
python -m venv .venv
.venv\Scripts\pip install -r apps\api\requirements.txt
```

`email-validator` is already listed in `requirements.txt`, so no extra install is needed.

### 2.3 `.env`

```powershell
copy .env.example .env
```

Edit `.env`:
- `DATABASE_URL` must use port **5433** (the demo compose maps Postgres 5433 -> 5432) and host `127.0.0.1`. The `POSTGRES_PORT=5432` line in the example is not what the app connects with. Postgres credentials for the demo compose are user `redline`, db `redline`, and the password set in `docker-compose.demo.yml`.
- `JWT_SECRET_KEY` must be 32+ characters. Generate one:
  ```powershell
  .venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- `CLICKHOUSE_PASSWORD` must not be empty.
- `GEMINI_API_KEY` is optional (only needed for live `rag-agent` runs).
- **Never commit `.env`** (it is in `.gitignore`).

### 2.4 Dashboard dependencies

```powershell
cd apps\dashboard
npm ci
cd ..\..
```

## 3. Start, seed, verify

```powershell
powershell -ExecutionPolicy Bypass -File scripts\redline.ps1 up -Dashboard
.venv\Scripts\python -m scripts.seed_demo --reset
powershell -ExecutionPolicy Bypass -File scripts\redline.ps1 verify
```

`up` does, in order: `docker compose -f docker-compose.demo.yml up -d --wait`; `alembic upgrade head`; `apps.api.scripts.init_topics`; `apps.api.scripts.init_clickhouse`; starts `api` (uvicorn on 127.0.0.1:8000), `worker` (`eval_worker_v2`), `load-worker`, and with `-Dashboard` Vite on :5173. PIDs and logs go to `.run\` (`api.log`, `api.err.log`, `vite.err.log`, ...).

`seed_demo --reset` deletes the demo tenant's data and re-creates it. It prints a fresh API key once (not needed for the dashboard). Login: **demo@redline.dev / DemoPass123!**.

`verify` checks `/health`, registers a throwaway user, logs in, calls `/dashboard/agents` (expects HTTP 200) and, if running, Vite on :5173.

Check state any time:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\redline.ps1 status
```

Open **http://localhost:5173** (use `localhost`, not `127.0.0.1`; see troubleshooting).

## 4. What runs where

| Component | Where | Port |
|---|---|---|
| Postgres 16 | Docker `redline_demo_postgres` | 5433 |
| Redis 7 | Docker `redline_demo_redis` | 6379 |
| Redpanda | Docker `redline_demo_redpanda` | 19092 |
| ClickHouse | Docker `redline_demo_clickhouse` | 8123 (HTTP), 9000 |
| API (monolith, all routers) | host, uvicorn | 8000 |
| Eval worker (`eval_worker_v2`) | host | none |
| Load worker | host | none |
| Dashboard (Vite dev) | host | 5173 |

## 5. Stop and reset

```powershell
powershell -ExecutionPolicy Bypass -File scripts\redline.ps1 down     # stops host processes and `docker compose down`
.venv\Scripts\python -m scripts.seed_demo --reset                       # pristine demo data again (stack must be up)
```

`down` stops containers but keeps the data volume (`demo_pg_data`). The `--reset-all` seed flag truncates every table except `alembic_version`.

## 6. Tests

```powershell
.venv\Scripts\python -m pytest -m unit          # no infrastructure needed
.venv\Scripts\python -m pytest -m integration   # needs the compose stack up; LLM cases also need a Gemini key
cd apps\dashboard; npm test                     # vitest (not run in this pass)
```

Test files must carry `pytestmark = pytest.mark.unit` or `integration` or they are not selected.

## 7. Conflicts with another RedLine checkout

The full stack (`docker-compose.yml`) uses container `redline_postgres` on 5433 and Redpanda Console on 8080; the demo stack here uses `redline_demo_*` containers but the **same host ports 5433/6379/19092/8123/9000**. Only one stack can run at a time. If `up` fails with "port is already allocated":

```powershell
docker ps --format "{{.Names}}  {{.Ports}}"
docker compose -f <path-to-other-tree>\docker-compose.yml down     # stop the older stack
```

Also stop any other uvicorn on :8000 or Vite on :5173 from another tree.

## 8. Troubleshooting (all seen for real)

| Symptom | Cause / fix |
|---|---|
| `docker` not recognised | Docker CLI not on PATH. `$env:Path += ";C:\Program Files\Docker\Docker\resources\bin"` (the launcher does this itself). |
| `.venv missing` / `.env missing` thrown by `up` | Do sections 2.2 and 2.3. |
| `UnicodeEncodeError ... cp1252` from a script that prints a check mark | `$env:PYTHONUTF8 = "1"` (the launcher sets it; set it yourself when running scripts by hand). |
| Dashboard blank or API calls fail at `http://127.0.0.1:5173` | Vite binds `localhost` (can resolve to IPv6). Use `http://localhost:5173`. |
| Rate-limiter / 500 errors on API calls | Redis is required (rate limiter). Confirm `redline_demo_redis` is healthy with `status`. |
| ClickHouse trace queries empty | Teammate `init_clickhouse` creates tables in `default` instead of `redline`; `seed_demo` works around this. Re-run the seed. |
| `401` on `/auth/me` in the browser console on the login page | Expected before sign-in. A `401` after login: session expired (access token life is short); sign in again. |
| `404 /agent` from the API (or `/agent` returning "Not Found" with curl) | The API path is `/agents`; the SPA path is `/agent`. See ONBOARDING section 7. |
| Eval/load run stays queued | Worker not running. `status` should show `worker` and `load-worker` running; read `.run\worker.err.log`. |
| `Run Eval` on `rag-agent` fails | Needs a Gemini key. Use `demo-support-agent` instead. |
| Login with the demo account fails after experiments | Re-seed: `.venv\Scripts\python -m scripts.seed_demo --reset`. |
| API did not become healthy | `.run\api.err.log` (commonly `.env` / DB port / JWT secret too short). |
| Vite did not respond | `.run\vite.err.log`; run `npm ci` in `apps\dashboard`. |

## 9. Full Docker / k3d deployment (optional, not exercised here)

Use the teammate's docs: root `README.md` (architecture, services, ports), `checkpoint.md` (full setup including k3d/Helm and monitoring), `DEPLOYMENT_AND_DEMO_GUIDE.md`, `docs/infra-hardening.md`, `docs/adr/ADR-005-helm-as-deployment-interface.md`, and Makefile targets `infra-up`, `cluster-up`, `images-build`, `keda-install`, `helm-install`, `deploy`, `monitoring-install`. In that mode the nginx gateway serves `:8085` (`:8000` on k3d) in front of eval/agent/gate services.
