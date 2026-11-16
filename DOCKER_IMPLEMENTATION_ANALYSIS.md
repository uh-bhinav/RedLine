# Docker Implementation Analysis — RedLine (AgentBench Cloud)

---

## 1. Executive Summary

**What this project does:** RedLine is an agent reliability engineering platform — it runs evaluation suites against AI agents, scores them, and enforces a pass/fail gate that can block a bad agent version from being deployed (similar to how a failing CI check blocks a bad commit).

**Why Docker is used here:** to stand up the entire backing infrastructure (Postgres, Redis, Redpanda/Kafka, ClickHouse, Tempo) with one command, and to package the three FastAPI microservices + the nginx gateway into deployable images that run identically in local Docker Compose and in a k3d/Kubernetes cluster via the same images.

**Which parts are containerized:**
- Infrastructure: PostgreSQL, PgBouncer, Redis, Redpanda, Redpanda Console, ClickHouse, Grafana Tempo — all pulled as public third-party images.
- Application: `eval_service`, `agent_service`, `gate_service` (three FastAPI microservices) and a `gateway` (nginx reverse proxy that also bakes in the built React dashboard) — all custom-built images from this repo's own Dockerfiles.

**What Docker solves here:** reproducible local dev environment (no one installs Postgres/Kafka/ClickHouse by hand), consistent image builds in CI, and portable images that move from `docker compose` on a laptop to k3d/Kubernetes pods without changing the image — only the environment variables change.

**Where Docker is used:** Local development, integration testing (CI reuses the same `docker-compose.yml`), and CI image build/scan/push. It is **not** used for local hot-reload development of app code (the services build once from source, no bind-mount dev loop). Kubernetes deployment (Helm/k3d) consumes the same images but is delivered through `k3d image import` / Helm, not Docker Compose.

**Overall architecture:**

```
Developer
   |
   | docker compose up -d
   ↓
Docker Compose (docker-compose.yml)
   |
   ├── Infrastructure (public images) ─────────────────────────┐
   │   Postgres · PgBouncer · Redis · Redpanda · Redpanda       │
   │   Console · ClickHouse · Tempo                             │
   |                                                             │
   └── Application (built from this repo's Dockerfiles) ───────┤
       eval_service (:8001) · agent_service (:8002) ·           │
       gate_service (:8003) · gateway/nginx (:8085 → :8000)     │
                                                                  ↓
                                                    all reachable via
                                                    Docker's default
                                                    bridge network,
                                                    service-name DNS
```

---

## 2. Docker Files and Configuration Inventory

| File | Purpose | Important details |
|---|---|---|
| `docker-compose.yml` (repo root) | Defines the entire local stack: 7 infra services + 4 app services + named volumes | Single compose file for both dev and CI (CI reuses it directly) |
| `apps/eval_service/Dockerfile` | Builds the `eval_service` image | Single-stage, `python:3.10-slim` |
| `apps/agent_service/Dockerfile` | Builds the `agent_service` image | Single-stage, `python:3.10-slim` |
| `apps/gate_service/Dockerfile` | Builds the `gate_service` image | Single-stage, `python:3.10-slim` |
| `infra/gateway/Dockerfile` | Builds the `gateway` image (nginx + baked-in dashboard SPA) | **Only multi-stage** Dockerfile in the repo (`node:20-alpine` build stage → `nginx:1.27-alpine` runtime stage) |
| `infra/gateway.nginx.conf` | nginx reverse-proxy config, mounted into the gateway container (also baked into the image) | Routes `/eval-runs`, `/ci`, `/auth`, `/diff-runs`, `/load-runs`, `/mining` → eval_service; `/agents`, `/eval-suites` → agent_service; `/dashboard` → gate_service |
| `infra/clickhouse-config.xml`, `infra/clickhouse-users.xml` | Mounted read-only into the ClickHouse container | Not Docker-specific config, just container-mounted app config |
| `infra/tempo.yaml` | Mounted read-only into the Tempo container | Same — app config, not Docker-specific |
| `.env.example` | Template for the `.env` file consumed by `docker-compose.yml` via `env_file:` and variable substitution (`${POSTGRES_USER}`, etc.) | Committed with placeholder/dev values only |
| `.env` | Real local secrets file | **Not committed** — confirmed present in `.gitignore` |
| `Makefile` | Wraps Docker/Compose/k3d/Helm commands for the k3d deployment workflow | `infra-up`/`infra-down` run `docker compose up -d` / `down`; `images-build` runs `docker build` per service; `k6-load-test` runs a standalone `docker run` |
| `.github/workflows/ci.yml` | CI pipeline: builds all 4 images, scans them, pushes to GHCR on `main`, also runs `docker compose up -d` for integration tests | The only place a full Docker CI/CD flow exists in this repo |
| `.github/workflows/agentbench-check.yml` | CI gate check | **Does not use Docker at all** — installs the CLI via `pip install .` and talks to a live RedLine instance over HTTP |
| `.github/workflows/test-suite-integrity.yml` | Fast pytest marker linter | Not reviewed in depth — not Docker-related based on its name and role described in `ci.yml`'s comments |
| `helm/redline/` | Kubernetes Helm chart (Chart.yaml, values.yaml, templates/) | Consumes the **same images** built by the Dockerfiles above, referenced by `image.tag`/`image.registry` in `values.yaml` — this is Kubernetes packaging, not Docker Compose, but it's downstream of the same build artifacts |

**Files that look Docker-related but are not:** none found — every Docker-adjacent file located traces back to an actual, active role in the build/run/CI pipeline.

**No `.dockerignore` file exists anywhere in the repository** — confirmed via filesystem search. This is a real gap (see Section 14).

---

## 3. Dockerfile Deep Analysis

### 3.1 `apps/eval_service/Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.10-slim

WORKDIR /app

COPY apps/api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api ./apps/api
COPY apps/eval_service ./apps/eval_service
COPY agents ./agents
COPY config ./config

RUN touch apps/__init__.py

EXPOSE 8001
CMD ["uvicorn", "apps.eval_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

**Base image:** `python:3.10-slim`. Not pinned to a specific patch version or digest — it floats on whatever `3.10-slim` resolves to at build time. This matches the project's committed Python 3.10 requirement (see `.claude/rules/coding-standards.md` Rule 1) but is not a fully reproducible/pinned base.

**Build context:** the repo root (`.`), not the `apps/eval_service/` directory. This is explicit in `docker-compose.yml` (`context: .`, `dockerfile: apps/eval_service/Dockerfile`) and in the Makefile (`docker build -t redline-$$svc:latest -f apps/$$svc/Dockerfile .`). The Dockerfile must therefore be built from the root so that `COPY apps/api ...`, `COPY agents ...`, `COPY config ...` paths resolve — building with `apps/eval_service/` as the context would break every COPY line.

**WORKDIR:** `/app`. All subsequent COPY/RUN/CMD operate relative to this.

**Dependency installation:** `apps/api/requirements.txt` is copied and installed **before** any application code is copied. This is a deliberate Docker layer-caching pattern — as long as `requirements.txt` doesn't change, `pip install` is skipped on rebuild and only the later `COPY` layers (application code) are invalidated, making iteration faster.

**COPY:** four separate COPY instructions, layered in this specific order:
1. `apps/api` → `./apps/api` — the shared library (models, core, services, scorers, gate engine)
2. `apps/eval_service` → `./apps/eval_service` — this specific service's routers/main.py
3. `agents` → `./agents` — the benchmark agent code, imported directly by `LocalPythonAdapter` (importlib-based, per architecture Rule 9)
4. `config` → `./config` — `model_profiles.yaml`, resolved at runtime by `get_profile()`. The Dockerfile comment explains this was a real bug fix: without this COPY, the image builds and starts fine but fails on the *first eval* with `FileNotFoundError`.

**Deliberately NOT copied:** `.env`. The Dockerfile's own comment states this explicitly — baking `.env` into the image would embed the Gemini API key and JWT secret into every image layer permanently (image layers are immutable and inspectable even if a later layer "deletes" the file). Instead, secrets are injected at container start via `docker-compose.yml`'s `env_file: .env` (Compose) or Kubernetes Secrets/ConfigMaps (Helm).

**RUN:** two RUN instructions — `pip install --no-cache-dir -r requirements.txt` (dependency install, `--no-cache-dir` avoids storing pip's download cache in the image layer) and `touch apps/__init__.py` (makes `apps/` an importable Python package inside the container, since `COPY` doesn't automatically create `__init__.py`).

**ENV / ARG:** **none declared in the Dockerfile itself.** All runtime environment variables (`DATABASE_URL`, `REDIS_URL`, etc.) are supplied externally by `docker-compose.yml`'s `environment:` block and `env_file: .env` — not baked in as Dockerfile `ENV` instructions. No `ARG` is used anywhere in this Dockerfile (no build-time parameterization).

**EXPOSE:** `8001` — documentation only; it does not publish the port. The actual host↔container port mapping happens in `docker-compose.yml`'s `ports: ["8001:8001"]`.

**USER:** not present. The container runs as **root** (the default for `python:3.10-slim` unless overridden). See Section 15 for the security implication.

**CMD:** `uvicorn apps.eval_service.main:app --host 0.0.0.0 --port 8001` — runs directly, not via an entrypoint script. `--host 0.0.0.0` is required for the process to accept connections from outside the container (binding to `127.0.0.1` would make it unreachable from the host or other containers).

**Execution story:**

```
Dockerfile
   ↓
docker build -f apps/eval_service/Dockerfile .   (context = repo root)
   ↓
Layer 1: pull python:3.10-slim
Layer 2: WORKDIR /app
Layer 3: COPY requirements.txt + pip install       ← cached unless requirements.txt changes
Layer 4: COPY apps/api, apps/eval_service, agents, config
Layer 5: touch apps/__init__.py
   ↓
final image: redline-eval_service:<tag>
   ↓
docker compose up  →  container created, env vars injected (env_file + environment:),
                       port 8001 published, joins default Compose network
   ↓
uvicorn starts, binds 0.0.0.0:8001, FastAPI app becomes reachable at
http://eval_service:8001 (from other containers) or http://localhost:8001 (from host)
```

### 3.2 `apps/agent_service/Dockerfile` and `apps/gate_service/Dockerfile`

Both are **structurally identical** to `eval_service`'s Dockerfile, differing only in:
- Which service directory is copied (`apps/agent_service` / `apps/gate_service` instead of `apps/eval_service`)
- `agent_service`'s Dockerfile does **not** copy `agents/` (agent_service owns the agent *registry*, not agent execution — it doesn't need to import agent code directly; `eval_service` does, since the eval engine runs agents)
- The `EXPOSE` port and the `CMD` port (`8002` and `8003` respectively)

All three services share the exact same base image, same layer-caching pattern, same "no `.env` baked in" reasoning (each Dockerfile repeats or references the same comment), and same lack of `USER`/`ENV`/`ARG`.

### 3.3 `infra/gateway/Dockerfile` — the one multi-stage build

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci
COPY apps/dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/gateway.nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8000
```

This is the **only multi-stage Dockerfile** in the repository.

**Stage 1 (`build`, `node:20-alpine`):**
- `package.json` + `package-lock.json` copied **first**, before the rest of the source — same layer-caching intent as the Python services: `npm ci` (a clean, lockfile-exact install) only reruns when the lockfile changes.
- `npm run build` produces a static SPA build (Vite, based on `apps/dashboard`'s tooling) into `/app/dist`.

**Stage 2 (runtime, `nginx:1.27-alpine`):**
- `COPY --from=build /app/dist /usr/share/nginx/html` — pulls **only the built static output** from stage 1 into the final image. Node, npm, `node_modules`, and all dashboard source are discarded — they exist only in the intermediate build stage, which is never shipped. This is the textbook benefit of multi-stage builds: a ~1GB+ Node build environment collapses into a lean nginx-plus-static-files image.
- `infra/gateway.nginx.conf` is baked in as the default nginx config.
- No `USER` — runs as nginx's default user setup inside the alpine image (nginx images typically drop to a non-root worker process internally, but the Dockerfile itself does not declare a `USER` instruction).
- `EXPOSE 8000` documents the port; actual mapping is `docker-compose.yml`'s `"8085:8000"`.

**Important nuance (per the Dockerfile's own top comment and `docker-compose.yml`'s `gateway` service comment):** `docker-compose.yml` **also** bind-mounts `./infra/gateway.nginx.conf:/etc/nginx/conf.d/default.conf:ro` at container start, which **overrides** the config baked into the image at build time. This means: in local Compose, editing the nginx config takes effect on container restart with **no image rebuild required** — only the baked-in dashboard `dist/` actually requires a rebuild to update. This is a deliberate dev-convenience layering documented directly in the compose file's own comments.

---

## 4. Image Analysis

**Images this project builds (custom):**
| Image | Dockerfile | Stages |
|---|---|---|
| `redline-eval_service` | `apps/eval_service/Dockerfile` | 1 (single-stage) |
| `redline-agent_service` | `apps/agent_service/Dockerfile` | 1 (single-stage) |
| `redline-gate_service` | `apps/gate_service/Dockerfile` | 1 (single-stage) |
| `redline-gateway` | `infra/gateway/Dockerfile` | 2 (multi-stage: node build → nginx runtime) |

Image names/tags: locally via the Makefile these are tagged `:latest` (`docker build -t redline-$$svc:latest ...`). In CI (`ci.yml`), they're tagged with the immutable `${{ github.sha }}` and — on `main` only — additionally tagged and pushed as `ghcr.io/<owner>/redline-<service>:${{ github.sha }}`.

**Images pulled from public registries (not built, used as-is):**
`postgres:16-alpine`, `edoburu/pgbouncer:v1.25.2-p0`, `redis:7-alpine`, `redpandadata/redpanda:v26.1.11`, `redpandadata/console:latest`, `clickhouse/clickhouse-server:26.3`, `grafana/tempo:2.5.0`, and (via the Makefile's `k6-load-test` target, standalone, not in compose) `grafana/k6`.

Most public images are version-pinned (`16-alpine`, `v1.25.2-p0`, `7-alpine`, `v26.1.11`, `26.3`, `2.5.0`) except `redpandadata/console:latest` and `grafana/k6` (implicitly `latest`), which are the two unpinned exceptions.

**Multi-stage builds:** used in exactly one place (`infra/gateway/Dockerfile`). The three FastAPI service Dockerfiles are single-stage.

```
Source code
   ↓
docker build (context = repo root, -f apps/<service>/Dockerfile)
   ↓
Image  (redline-<service>:<tag>, layered: base → deps → app code)
   ↓
docker compose up  /  docker run  /  k3d image import + Helm-managed pod
   ↓
Container  (env vars injected at this step, not baked into the image)
```

---

## 5. Container Runtime Analysis

Containers are started three ways in this repo: (a) `docker compose up`, (b) the Makefile's `docker build` + `k3d image import` + Helm path for Kubernetes, (c) a standalone `docker run` for the k6 load-test tool. There are no raw `docker run` commands for the application services themselves anywhere in the repo — they are always started via Compose or via Kubernetes pods.

| Service | Image | Command | Ports | Key env vars | Volumes | Networks | Restart policy | Depends on |
|---|---|---|---|---|---|---|---|---|
| `postgres` | `postgres:16-alpine` | image default | `5433:5432` | `POSTGRES_USER/PASSWORD/DB` (from `.env`) | `redline_pg_data` (named) | default Compose network | `unless-stopped` | — |
| `pgbouncer` | `edoburu/pgbouncer:v1.25.2-p0` | image default | `6432:5432` | `DATABASE_URL` (constructed, points at `postgres`), pool config | none | default | `unless-stopped` | `postgres` (healthy) |
| `redis` | `redis:7-alpine` | image default | `6379:6379` | none | `redline_redis_data` | default | `unless-stopped` | — |
| `redpanda` | `redpandadata/redpanda:v26.1.11` | custom `redpanda start` with 3 listeners (internal/external/k3d) | `19092`, `29092`, `18082`, `9644` | none (config via command args) | `redline_redpanda_data` | default | `unless-stopped` | — |
| `redpanda-console` | `redpandadata/console:latest` | image default | `8080:8080` | `CONFIG_FILEPATH` | config file (ro) | default | `unless-stopped` | `redpanda` (healthy) |
| `clickhouse` | `clickhouse/clickhouse-server:26.3` | image default | `8123:8123`, `9000:9000` | `CLICKHOUSE_DB/USER/PASSWORD` | 2 named volumes + 2 config mounts (ro) | default | `unless-stopped` | — |
| `eval_service` | built (`redline-eval_service`) | Dockerfile `CMD` | `8001:8001` | `DATABASE_URL`, `REDIS_URL`, `REDPANDA_BOOTSTRAP_SERVERS`, `CLICKHOUSE_HOST`, `OTEL_EXPORTER_ENDPOINT` + `env_file: .env` | none | default | `unless-stopped` | `postgres`, `redpanda`, `redis` (all healthy), `tempo` (started) |
| `agent_service` | built (`redline-agent_service`) | Dockerfile `CMD` | `8002:8002` | same pattern | none | default | `unless-stopped` | `postgres`, `redis` (healthy), `tempo` (started) |
| `gate_service` | built (`redline-gate_service`) | Dockerfile `CMD` | `8003:8003` | same pattern | none | default | `unless-stopped` | `postgres`, `redis`, `clickhouse` (all healthy), `tempo` (started) |
| `tempo` | `grafana/tempo:2.5.0` | `-config.file=/etc/tempo.yaml` | `4317:4317`, `3200:3200` | none | 1 config mount (ro) + 1 named volume | default | `unless-stopped` | — |
| `gateway` | built (`redline-gateway`) | image default (nginx) | `8085:8000` | none | `gateway.nginx.conf` mounted (ro), overriding the baked-in config | default | `unless-stopped` | `eval_service`, `agent_service`, `gate_service` (all healthy) |

**Health checks:** every service except `redpanda-console` and `gateway`'s upstream dependencies has an explicit `healthcheck:`. Notably, the three FastAPI services check liveness via a raw Python socket connect (`socket.create_connection`) rather than an HTTP request to `/health` — meaning the healthcheck only confirms the port is *listening*, not that `/health`'s own DB check (per architecture coding-standards Rule 12) passes. This is a real gap — see Section 16.

**Networks:** no custom network is declared. All services join Compose's implicit default bridge network, and reach each other by service name (`postgres`, `redis`, `redpanda`, `clickhouse`, `eval_service`, etc.) — Docker Compose's built-in DNS resolves service names to container IPs automatically.

**Volumes:** all named volumes are declared at the bottom of `docker-compose.yml`: `redline_pg_data`, `redline_redis_data`, `redline_redpanda_data`, `redline_ch_data`, `redline_ch_logs`, `redline_tempo_data`. No bind mounts of application source code exist for any of the three FastAPI services or the gateway — meaning there is no hot-reload dev loop through Compose (see Section 10).

---

## 6. Docker Compose Analysis

### Services (11 total)
Infrastructure: `postgres`, `pgbouncer`, `redis`, `redpanda`, `redpanda-console`, `clickhouse`, `tempo`
Application: `eval_service`, `agent_service`, `gate_service`, `gateway`

Full per-service breakdown is in Section 5's table above (image/build/ports/env/volumes/depends_on/healthcheck already covered there to avoid duplication).

### Service communication

Every cross-service reference in `docker-compose.yml` uses the **Compose service name**, never `localhost`:
- `eval_service`/`agent_service`/`gate_service` → Postgres via `postgresql+psycopg2://...@postgres:5432/...`
- → Redis via `redis://redis:6379/0`
- → Redpanda via `redpanda:9092` (the **internal** listener — see the redpanda command block's extensive comment explaining why three separate listeners exist: `internal` for container-to-container, `external` (`localhost:19092`) for a host-run process like a locally-run worker, `k3d` (`host.k3d.internal:29092`) for pods in a k3d cluster reaching the same Redpanda instance running outside the cluster)
- → ClickHouse via `clickhouse` (host) — port unspecified in the app services' env (defaults presumably read from `.env`/Settings)
- → Tempo via `http://tempo:4317`
- `gateway` (nginx) → `eval_service:8001`, `agent_service:8002`, `gate_service:8003` (declared as nginx `upstream` blocks using the Compose service names directly)
- `pgbouncer` → `postgres:5432`

**This project correctly uses Compose service names for all container-to-container communication.** `localhost` inside a container would refer to that container itself, not a sibling — the repo avoids this mistake everywhere in the compose file. The **only** place `localhost` legitimately appears is the Redpanda `external` listener's advertised address, which is intentionally meant for processes running directly on the host (documented explicitly in the command's inline comment as a deliberate three-listener design, not an oversight).

### Lifecycle

**`docker compose up -d`:** Compose reads `docker-compose.yml` + `.env` (for variable substitution like `${POSTGRES_USER}`), builds the four application images if not already built (or if `--build` is passed / Dockerfile changed and cache is stale), creates the default bridge network if it doesn't exist, creates/reuses the six named volumes, then starts containers respecting `depends_on` conditions (`service_healthy` gates like `postgres: condition: service_healthy` mean dependent services wait for the healthcheck to pass, not just for the container to start).

**`docker compose down`:** stops and **removes containers and the default network**. Named volumes (`redline_pg_data`, etc.) are **preserved by default** — `docker compose down` does not delete volumes unless run with `-v`/`--volumes`. So Postgres data, Redis data, Redpanda's log data, and ClickHouse data all **survive** a `down`/`up` cycle; only the containers themselves are recreated.

---

## 7. Docker Networking in This Project

**Networks:** exactly one — Compose's implicit default bridge network (project-name-prefixed, auto-created). No custom `networks:` block is declared in `docker-compose.yml`.

**Service discovery:** Docker Compose's embedded DNS resolves each service's name (e.g., `postgres`, `redis`, `eval_service`) to its container's IP on that network — confirmed by every connection string in the compose file using service names, as detailed in Section 6.

**Host-published ports:**

```
Host                                    Container
 |
 |  :8085 ──────────────────────→  gateway :8000  (nginx, proxies to below)
 |  :8001 ──────────────────────→  eval_service :8001
 |  :8002 ──────────────────────→  agent_service :8002
 |  :8003 ──────────────────────→  gate_service :8003
 |  :5433 ──────────────────────→  postgres :5432   (nonstandard host port — avoids clashing with a local Postgres)
 |  :6432 ──────────────────────→  pgbouncer :5432
 |  :6379 ──────────────────────→  redis :6379
 |  :19092/:29092/:18082/:9644 ─→  redpanda (4 listeners, purpose-specific — see §6)
 |  :8080 ──────────────────────→  redpanda-console :8080
 |  :8123/:9000 ────────────────→  clickhouse :8123/:9000
 |  :4317/:3200 ────────────────→  tempo :4317/:3200
```

Internally (container-to-container, not published to host), the gateway reaches the three FastAPI services on their container-internal ports (`8001`/`8002`/`8003`) directly over the bridge network — no separate internal port scheme.

**Potential networking issues identified:**
- Postgres is mapped to the nonstandard host port `5433` specifically to avoid colliding with a locally-installed Postgres on `5432` — this is a real, deliberate choice (also reflected in `.env.example`'s own comments about IPv4-vs-IPv6 loopback ambiguity for `DATABASE_URL`), not an oversight.
- The Redpanda **three-listener** setup is the most networking-sophisticated part of this repo and is explicitly there to solve a real, previously-encountered bug (documented inline in `docker-compose.yml`): a pod inside k3d that bootstraps against Redpanda gets told via Kafka's metadata protocol to reconnect to whatever address is *advertised* — if that's `localhost`, a pod resolves that to itself, not the Mac host, breaking every call after the initial connection. The dedicated `k3d://host.k3d.internal:29092` listener exists solely to give k3d pods a working address distinct from what a host process or a Compose container would use.

---

## 8. Environment Variables and Configuration

**`.env` usage:** `docker-compose.yml` uses `env_file: .env` for all three FastAPI services, plus direct `${VAR}` substitution (e.g., `${POSTGRES_USER}`) sourced from the same `.env`/shell environment for the infra services' `environment:` blocks. `.env.example` is the committed template with placeholder values; the real `.env` is gitignored.

**Key variables (from `.env.example`) and where each is consumed:**

| Variable | Defined in | Enters container via | Consumed by | Build-time or runtime? |
|---|---|---|---|---|
| `POSTGRES_USER/PASSWORD/DB` | `.env` | `docker-compose.yml` `environment:` (Postgres container) + string-interpolated into `DATABASE_URL` for app services | `postgres` container itself; app services via `DATABASE_URL` | Runtime |
| `DATABASE_URL` | Constructed inline in `docker-compose.yml`'s `environment:` block per app service (not read verbatim from `.env` for the containerized services — it's rebuilt using the Compose service name `postgres` instead of `.env.example`'s `127.0.0.1`) | `environment:` | `apps/api/core/config.py` (`Settings`, pydantic-settings) | Runtime |
| `REDIS_URL` | Same pattern — rebuilt to point at `redis` (service name) rather than `.env.example`'s `localhost` | `environment:` | `apps/api/core/redis_client.py` | Runtime |
| `REDPANDA_BOOTSTRAP_SERVERS` | Rebuilt to `redpanda:9092` (internal listener) | `environment:` | `apps/api/core/redpanda_queue.py` | Runtime |
| `CLICKHOUSE_HOST/PASSWORD` | Rebuilt to `clickhouse` (service name); password required per security rules (Rule 7) | `environment:` | `apps/api/core/clickhouse_client.py` | Runtime |
| `JWT_SECRET_KEY` | `.env` (passed through via `env_file:`) | `env_file: .env` | `apps/api/core/security.py` / auth router | Runtime |
| `ANTHROPIC_API_KEY` / Gemini key | `.env` | `env_file: .env` | LLM-calling code (RAG agent, `llm_judge` scorer) | Runtime |
| `OTEL_EXPORTER_ENDPOINT` | Rebuilt to `http://tempo:4317` | `environment:` | `apps/api/core/telemetry.py` | Runtime |

**No Dockerfile `ENV` or `ARG` instructions exist anywhere in this repo's four custom Dockerfiles.** All configuration is runtime-injected by Compose (locally) or by Kubernetes Secrets/ConfigMaps (via Helm's `_helpers.tpl`, referenced in the gateway Dockerfile's own comments) — meaning the **same image** is reused unmodified across environments, with only the injected environment differing. This is a deliberately portable pattern, matching the project's explicit architecture note (`.env` is never baked into images, per the comment in every service Dockerfile).

**Secrets baked into images:** none found. Every Dockerfile explicitly avoids `COPY .env .env`, with a comment explaining why. This was verified to be intentional and documented, not merely absent by chance.

**CI secrets:** `ci.yml` and `agentbench-check.yml` reference `${{ secrets.GEMINI_API_KEY }}`, `${{ secrets.GITHUB_TOKEN }}`, `${{ secrets.KUBE_CONFIG }}`, `${{ secrets.JWT_SECRET_KEY }}`, `${{ secrets.REDLINE_API_KEY }}`, `${{ secrets.REDLINE_BASE_URL }}` — all standard GitHub Actions encrypted secrets, injected as job/step env vars, never written into a Docker image layer.

---

## 9. Storage and Persistence

**Named volumes (all declared in `docker-compose.yml`):**
- `redline_pg_data` → Postgres data directory (`/var/lib/postgresql/data`)
- `redline_redis_data` → Redis data directory (`/data`)
- `redline_redpanda_data` → Redpanda's log/data directory
- `redline_ch_data` + `redline_ch_logs` → ClickHouse data + logs
- `redline_tempo_data` → Tempo's trace storage

**Bind mounts (all read-only, all configuration, not source code):**
- `./infra/redpanda-console-config.yml` → Redpanda Console
- `./infra/clickhouse-config.xml`, `./infra/clickhouse-users.xml` → ClickHouse
- `./infra/tempo.yaml` → Tempo
- `./infra/gateway.nginx.conf` → gateway (overrides the image's baked-in copy at runtime)

**No bind mounts of application source code** for `eval_service`, `agent_service`, `gate_service`, or the dashboard build — application code is copied into the image at build time only; there is no live-reload dev loop via Compose.

**What survives `docker compose down` (no `-v` flag):** all six named volumes and their data — Postgres tables, Redis keys, Redpanda topic data, ClickHouse tables, Tempo traces.

**What disappears:** the containers themselves and the network; anything written to a container's writable layer outside a mounted volume (irrelevant here since app containers have no volumes at all — they're fully stateless and disposable).

```
Container deleted (docker compose down, no -v)
   ↓
Containers + default network: gone
   ↓
Named volumes: survive on disk
   ↓
docker compose up again: same volumes reattached, Postgres/Redis/Redpanda/
ClickHouse/Tempo data is exactly as it was
```

```
docker compose down -v  (explicit, not the default)
   ↓
Named volumes deleted too → all persisted data is gone, next `up` starts from empty state
```

---

## 10. Development Workflow

Reconstructed from `README.md`'s Quickstart section and the Makefile:

```
git clone
   ↓
cp .env.example .env  (implied — CI does this explicitly; README doesn't show this exact step but .env.example exists for this purpose)
   ↓
docker compose up -d          (README step 1: "Infrastructure")
   ↓
alembic upgrade head           (schema migration — runs on host, not in a container)
python -m apps.api.scripts.seed
python -m apps.api.scripts.create_api_key
python -m apps.api.scripts.init_topics
python -m apps.api.scripts.init_clickhouse
   ↓
python -m uvicorn apps.api.main:app --port 8000     (README step 3: API server — run directly on
                                                       the host with the monolith, NOT via Docker)
python -m apps.api.workers.eval_worker_v2            (README step 4: worker — also run on host)
   ↓
pip install -e .                                     (installs the `agentbench` CLI)
   ↓
agentbench login / init / push-suite / register-version / run
```

**Important nuance:** the README's Quickstart runs the **monolith** (`apps.api.main:app`) and the worker **directly on the host** via `uvicorn`/`python -m`, not through Docker — Docker Compose is used only for the **infrastructure** (Postgres/Redis/Redpanda/ClickHouse) in this everyday dev flow. The **containerized microservices** (`eval_service`, `agent_service`, `gate_service`, `gateway`) defined in `docker-compose.yml` represent the Phase 2+ service-decomposed architecture, built and run via `make images-build` / `docker compose up` for the k3d/Helm deployment path, or the full-stack Compose run — not the everyday hot-loop the README's Quickstart describes.

**Hot reload:** **not present.** No bind mount of source code, no `uvicorn --reload` flag in any Dockerfile `CMD`. Rebuilding the image (`docker compose build` or `docker build`) is required to pick up code changes in the containerized services.

**Rebuilding after a dependency change:** since `requirements.txt` is copied before app code, only a `requirements.txt` change invalidates the `pip install` layer; an app code change only invalidates the later `COPY` layers and is fast to rebuild.

**Stopping/rebuilding:** `make infra-down` (`docker compose down`) / `docker compose up -d --build` to force a rebuild — this exact `--build` invocation is not shown in the repo, but is standard Compose usage consistent with the Makefile's documented `infra-up`/`infra-down` targets.

---

## 11. Docker + Database / Redis / Other Services

```
eval_service / agent_service / gate_service
 ├── PostgreSQL   [Docker container]  — accessed via service name `postgres:5432`, persists to redline_pg_data
 ├── PgBouncer    [Docker container]  — optional connection pooler in front of Postgres (`pgbouncer:5432`→postgres), opt-in via DB_USE_EXTERNAL_POOLER
 ├── Redis        [Docker container]  — accessed via `redis:6379`, persists to redline_redis_data
 ├── Redpanda     [Docker container]  — accessed via `redpanda:9092` (internal listener), persists to redline_redpanda_data
 ├── ClickHouse   [Docker container]  — accessed via `clickhouse:8123/9000`, persists to redline_ch_data/redline_ch_logs
 └── Tempo        [Docker container]  — accessed via `tempo:4317` (OTLP gRPC), persists to redline_tempo_data
```

Every backing dependency in this project is a Docker container, not an external managed service — there is no evidence of connecting to a cloud-hosted Postgres/Redis/etc. in local dev or CI. (Production/Helm deployment points at `host.k3d.internal` addresses per `helm/redline/values.yaml`, meaning in the k3d deployment path the *same* Dockerized infra containers, running outside the k3d cluster via Compose, are reached from inside k3d pods — not a separate managed cloud service.)

All are accessed via **Docker service name**, never `localhost`, from within other containers — consistent with Section 6's finding.

All persist data via named volumes except `pgbouncer` and `redpanda-console` (both stateless proxies/UIs with no volume declared, which is correct — they hold no data of their own).

---

## 12. Docker + CI/CD

Docker **is** used in CI/CD, in `.github/workflows/ci.yml`, in two distinct ways:

**1. Integration test infra (the `integration-tests` job):**
```yaml
docker compose up -d postgres redis redpanda clickhouse
```
This reuses the **exact same** `docker-compose.yml` developers use locally (explicitly called out in a comment: "Reuses the SAME docker-compose.yml developers use locally — a separate CI-only compose file would drift out of sync with what's actually being tested"). It brings up only the four infra services (not the app services), waits for Postgres readiness via a `pg_isready` polling loop, then runs Alembic migrations and `pytest -m integration` against it.

**2. Image build/scan/push (the `build-scan` job):**
```
Git push
   ↓
CI (unit-tests + integration-tests + frontend-build, all must pass)
   ↓
Build image  (docker build -t redline-<service>:<sha> -f <dockerfile> . , matrix over 4 services)
   ↓
pip-audit (dependency vuln scan, non-blocking: `|| true`)
   ↓
Trivy scan (image vuln scan, report-only: exit-code "0", not yet a hard gate)
   ↓
Tag + Push to GHCR  (only on push to main, not on PRs — `ghcr.io/<owner>/redline-<service>:<sha>`)
   ↓
Deploy job (helm upgrade --atomic, gated on a KUBE_CONFIG secret that doesn't exist yet —
            job runs and exits cleanly with "no deploy target yet" if the secret is absent)
```

The pipeline builds and scans **all four** images (`eval_service`, `agent_service`, `gate_service`, `gateway`) via a matrix build. Every image gets both a `pip-audit` dependency scan and a Trivy image scan, though both are currently **non-blocking/report-only** by explicit design (the workflow's own comments say this is deliberate: "Non-blocking initially — report and triage before flipping this to a hard gate").

**Important distinction:** `agentbench-check.yml` (the separate "AgentBench Reliability Check" workflow, the one referenced by RedLine's branch-protection requirement per architecture Rule 10 — see also `security.md` Rule 10) does **not** use Docker at all. It installs the `agentbench` CLI via plain `pip install .` and talks to a live, already-deployed RedLine instance over HTTP — this is the CLI's own architecture rule (Rule 7: "The CLI Is HTTP-Only") playing out directly in CI.

---

## 13. Production / Deployment Usage

There **is** evidence of a deployment path, but it is explicitly **not yet live**:

```
Development (docker-compose.yml, local)
   ↓
Build   (ci.yml build-scan job — matrix build of all 4 images)
   ↓
Registry   (GHCR — ghcr.io/<owner>/redline-<service>:<sha>, on main only)
   ↓
Deployment   (ci.yml deploy job — `helm upgrade redline ./helm/redline --set image.tag=<sha> ...`)
```

The `deploy` job in `ci.yml` is described in its own comment as "Correct and complete, but INERT until a `KUBE_CONFIG` secret + a reachable cluster exist (Phase 5.4, deferred). Not a broken job — there is simply nowhere to deploy to yet." The job checks for the secret and exits 0 with a message if absent, rather than failing.

**Local production-like deployment does exist and is functional:** the Makefile's `deploy` target (`images-build` → `images-import` → `helm-upgrade` → rolling restarts) deploys the same images into a local **k3d** cluster, using Helm and KEDA for autoscaling — this is a real, working path (per architecture Rule 10, the worker's replica count is explicitly left unset in the Helm templates so KEDA owns it), just not a *cloud* production deployment.

**No evidence of:** a cloud container registry beyond GHCR, a production Kubernetes cluster actually receiving traffic, or any deployment scripts targeting AWS/GCP/Azure managed container services.

---

## 14. Docker Optimization

### Good practices already implemented
- **Dependency-first COPY ordering** in all four custom Dockerfiles — `requirements.txt`/`package.json`+`package-lock.json` copied and installed before application source, maximizing layer cache reuse on code-only changes.
- **`pip install --no-cache-dir`** — avoids storing pip's download cache inside the image layer, reducing image size.
- **`npm ci`** (not `npm install`) in the gateway build stage — deterministic, lockfile-exact installs, and faster/cleaner than `npm install` in a CI/build context.
- **Multi-stage build for the gateway** — the Node.js build toolchain (a large image) is entirely discarded from the final image; only the compiled static `dist/` output ships in the `nginx:1.27-alpine` final stage.
- **Alpine-based images throughout** for infra (`postgres:16-alpine`, `redis:7-alpine`) and for the gateway's runtime stage (`nginx:1.27-alpine`) — smaller base images than their Debian-based equivalents.
- **Slim Python base** (`python:3.10-slim`, not the full `python:3.10`) for all three FastAPI services.
- **Secrets never baked into images** — verified across all four Dockerfiles, each with an explicit comment explaining the reasoning.

### Potential improvements
- **No `.dockerignore` file exists anywhere in the repo.** Since build context is the repo root, `docker build` sends the *entire* repository (including `.git/`, `node_modules` if present locally, test files, docs, `helm/`, etc.) to the Docker daemon as build context on every build, even though only a handful of subdirectories are ever actually `COPY`'d. This doesn't bloat the final image (unused files are never copied in), but it slows down every `docker build` invocation, especially in CI, by transferring an unnecessarily large context.
- **Base images are not pinned to a digest**, only a tag (`python:3.10-slim`, `nginx:1.27-alpine`). Tags can be repointed by the upstream maintainer; a digest pin (`@sha256:...`) would make builds fully reproducible. This is a reasonable, not urgent, hardening step.
- **`redpandadata/console:latest`** and **`grafana/k6`** (implicitly `:latest`) are the two genuinely unpinned image references in the whole stack — inconsistent with the otherwise careful version pinning seen everywhere else (Postgres, Redis, Redpanda itself, ClickHouse, Tempo, PgBouncer are all pinned).
- The three FastAPI Dockerfiles are near-duplicates of each other (differing only in which service dir is copied and which port is used) — not a Docker problem per se, but a Dockerfile-template opportunity (e.g., a shared base image or `ARG SERVICE_NAME`/`ARG PORT` pattern) that isn't used. This is a legitimate, low-priority DRY improvement, not a correctness issue.

---

## 15. Docker Security

### Security practices implemented
- **No secrets baked into any image** — confirmed, and explicitly reasoned about in code comments in every service Dockerfile.
- **`.env` is gitignored**; `.env.example` ships only placeholder values.
- **CI secrets** are handled via GitHub Actions' encrypted secrets mechanism, never hardcoded, and the CLI-only `agentbench-check.yml` workflow deliberately omits `GEMINI_API_KEY` from its environment entirely on the grounds that "a CI job holding a provider key it does not use is needless secret exposure" (a real, documented least-privilege decision).
- **Image vulnerability scanning is wired up** (Trivy) and **dependency vulnerability scanning is wired up** (pip-audit) in CI, even though both are currently non-blocking.
- **ClickHouse least-privilege app user**: `.env.example` documents a Phase 5.1 change to a dedicated `CLICKHOUSE_USER=redline_app` with `SELECT, INSERT only`, distinct from the container's bootstrap admin/superuser (`CLICKHOUSE_ADMIN_USER=default`) — a real separation-of-privilege pattern, not just a superuser used everywhere.

### Security risks
- **No `USER` instruction in any of the four custom Dockerfiles** — all containers (the three FastAPI services and the gateway's build stage) run as **root** by default. This is the single most interview-relevant weak point: a real principal-engineer-level review would flag this. (Note: `nginx:1.27-alpine`'s own upstream image conventionally runs its worker processes as a lower-privilege `nginx` user internally, but this repo's Dockerfile does not add its own `USER` instruction, so this is inherited image behavior, not something the project itself configured.)
- **Trivy scan and pip-audit are both non-blocking** (`exit-code: "0"` and `|| true` respectively) — vulnerabilities are surfaced in CI logs but currently cannot fail a build. The workflow's own comments acknowledge this is intentional-but-temporary ("flip to a hard gate" once a baseline is triaged), so this is an honestly-documented gap, not a hidden one.
- **Postgres/Redis/ClickHouse ports are all published to the host** (`5433`, `6379`, `8123`/`9000`) — fine for local dev, but if this exact compose file were ever run on an internet-facing host, these would be open to any client that can reach that host's IP. No evidence this compose file is used for anything beyond local dev/CI, so this is a theoretical risk given current usage, not an active one.

### Reasonable improvements
- Add a `USER appuser` (non-root) instruction to the three Python service Dockerfiles and the gateway Dockerfile.
- Pin base images by digest for full reproducibility.
- Flip Trivy and pip-audit to blocking once a vulnerability baseline is triaged (already the team's own stated plan per the workflow comments).

---

## 16. Docker Debugging Knowledge From This Project

### Scenario 1: An app service container exits immediately
**Check:** `docker compose logs eval_service` first — since there's no volume-mounted code and the `CMD` is a direct `uvicorn` invocation, an immediate exit is almost always an import-time failure: a missing `config/model_profiles.yaml` (the exact bug the Dockerfile's own comment warns about — "the image builds and starts fine, then fails on the first eval" is actually a *different*, later-stage failure; a true immediate exit is more likely a Python import error from a missing dependency or a typo in one of the `COPY`'d paths). Also check that the image was actually rebuilt after the last code change — no hot reload means a stale image silently runs old code without erroring at all, which is a different but related trap.

### Scenario 2: A service can't connect to PostgreSQL
**Check:** first, whether `DATABASE_URL` inside the container actually resolves to `postgres` (the service name), not `127.0.0.1`/`localhost` — the `.env.example` comment explicitly warns that `127.0.0.1` vs `localhost` IPv4/IPv6 ambiguity broke Postgres auth once before (a real prior incident referenced in that file). Then check `postgres`'s healthcheck status (`docker compose ps`) — the app services' `depends_on: postgres: condition: service_healthy` means they *shouldn't* start before Postgres is ready, but if the healthcheck itself is misconfigured or slow, a race is possible. Also verify `POSTGRES_USER/PASSWORD/DB` are actually set in `.env` — if `.env` is missing, Compose's `${VAR}` substitution silently becomes empty strings rather than failing loudly.

### Scenario 3: A service can't connect to Redis
**Check:** `REDIS_URL` should be `redis://redis:6379/0` inside containers (service name, not `localhost`) — confirm the environment actually being injected via `docker compose exec eval_service env | grep REDIS`. Check Redis's healthcheck (`redis-cli ping`) via `docker compose ps`.

### Scenario 4: Works locally (host-run) but not in Docker
**Check:** this is the single most likely category of bug in this repo specifically, because the README's own Quickstart runs the monolith and worker **directly on the host**, not in a container — meaning "local" and "Dockerized" are two genuinely different code paths with different `DATABASE_URL`/`REDIS_URL`/`REDPANDA_BOOTSTRAP_SERVERS` values (host values use `localhost`/`127.0.0.1` per `.env.example`; containerized values use Compose service names, rewritten separately inside `docker-compose.yml`'s `environment:` blocks). A working host setup does not guarantee the containerized environment variables were updated to match — check `docker-compose.yml`'s `environment:` block for the affected service directly, not `.env`.

### Scenario 5: An environment variable is missing inside the container
**Check:** distinguish whether the variable is supposed to come from `env_file: .env` (raw pass-through — if it's missing from `.env`, it's missing in the container) or is one of the *rebuilt* variables in `docker-compose.yml`'s own `environment:` block (like `DATABASE_URL`, which is **not** read verbatim from `.env`, but reconstructed with a different host). Run `docker compose exec <service> env` to see what actually landed inside the running container, and compare against both `.env` and the compose file's `environment:` section.

### Scenario 6: A port is inaccessible from the host
**Check:** confirm the `ports:` mapping in `docker-compose.yml` for that specific service (host-port:container-port) — note several services use **nonstandard host ports** deliberately (Postgres on host `5433`, not `5432`) specifically to avoid clashing with a locally-installed instance of the same software; connecting to the "obvious" default port from the host will fail even though the container itself is fine. Also confirm the service's healthcheck is passing (`docker compose ps`) — a container in a crash-loop or still starting won't accept connections yet even if the port mapping is correct.

---

## 17. Docker Architecture Diagram

```
Developer
   |
   | docker compose up -d
   ↓
Docker Compose  (docker-compose.yml, repo root, default bridge network)
   |
   ├── Infra (public images, all pinned except Console) ───────────────────┐
   │     postgres:16-alpine        :5433→5432   [redline_pg_data]          │
   │     pgbouncer:v1.25.2-p0      :6432→5432                              │
   │     redis:7-alpine            :6379→6379   [redline_redis_data]       │
   │     redpanda:v26.1.11         :19092/:29092/:18082/:9644              │
   │                                             [redline_redpanda_data]   │
   │     redpanda-console:latest   :8080→8080                              │
   │     clickhouse-server:26.3    :8123/:9000  [redline_ch_data/_logs]    │
   │     tempo:2.5.0               :4317/:3200  [redline_tempo_data]       │
   |                                                                        │
   └── App (built from this repo) ─────────────────────────────────────────┤
         eval_service    (Dockerfile, python:3.10-slim)   :8001→8001       │
         agent_service   (Dockerfile, python:3.10-slim)   :8002→8002       │
         gate_service    (Dockerfile, python:3.10-slim)   :8003→8003       │
         gateway         (Dockerfile, node:20-alpine→                     │
                           nginx:1.27-alpine, multi-stage) :8085→8000      │
                           (nginx.conf bind-mounted, overrides baked-in)   ┘
   |
   ↓ all services communicate via Compose service-name DNS on the
     default bridge network — no custom network, no localhost between
     containers
```

---

## 18. "What Actually Happens?" Walkthrough

1. Developer runs `docker compose up -d` from the repo root.
2. Compose reads `docker-compose.yml`, substitutes `${POSTGRES_USER}` etc. from `.env`.
3. For the four app services, Compose checks if the image needs building (first run, or Dockerfile/context changed) — each is built with the **repo root** as build context, using its respective Dockerfile path.
4. Each app Dockerfile's build: pulls `python:3.10-slim` (or `node:20-alpine`→`nginx:1.27-alpine` for gateway), sets `WORKDIR /app`, installs dependencies (`pip install -r requirements.txt` / `npm ci`) as an early, cacheable layer, then copies application code.
5. Infra images are pulled from Docker Hub/registries if not already cached locally (`postgres:16-alpine`, `redis:7-alpine`, etc.).
6. The default bridge network is created (or reused) for the Compose project.
7. Named volumes are created (or reused if they already exist from a prior run) — `redline_pg_data`, `redline_redis_data`, etc.
8. Containers start in dependency order: `postgres`, `redis`, `redpanda`, `clickhouse` start first (no `depends_on` of their own); `pgbouncer` and `redpanda-console` wait for their respective `service_healthy` conditions; `eval_service`/`agent_service`/`gate_service` wait for `postgres`+`redis`+(`redpanda`/`clickhouse` depending on service) to be healthy and `tempo` to have started; `gateway` waits for all three app services to be healthy.
9. Environment variables are injected at container-create time — `env_file: .env` for the three app services, plus the `environment:` block's explicitly reconstructed `DATABASE_URL`/`REDIS_URL`/etc. that point at Compose service names rather than `.env`'s host-oriented `localhost` values.
10. Each service's process starts: Postgres/Redis/Redpanda/ClickHouse/Tempo start their normal server processes; each FastAPI service runs its Dockerfile's `CMD` (`uvicorn apps.<service>.main:app --host 0.0.0.0 --port <port>`); the gateway starts nginx, serving the baked-in (or bind-mount-overridden) config.
11. `eval_service` communicates with Postgres via `postgres:5432`, with Redis via `redis:6379`, with Redpanda via `redpanda:9092`, and with Tempo via `tempo:4317` — all resolved through Compose's internal DNS.
12. Data written by Postgres/Redis/Redpanda/ClickHouse/Tempo persists to their respective named volumes on the Docker host's filesystem, surviving container restarts and `docker compose down` (without `-v`).
13. The developer accesses the stack through host-published ports — e.g., `http://localhost:8085` for the gateway (which nginx-proxies onward to the three backend services based on URL path), or directly at `http://localhost:8001`/`:8002`/`:8003` for each service individually, bypassing the gateway.
14. Separately (per the README's actual Quickstart), the developer may instead run the **monolith** (`apps.api.main:app`) and the eval worker directly on the host with `python -m uvicorn`/`python -m apps.api.workers.eval_worker_v2`, using Compose *only* for the infra services (Postgres/Redis/Redpanda/ClickHouse) — this is the more commonly used day-to-day dev loop described in the README, distinct from the fully-containerized microservice stack.

---

## 19. Interview Questions Based on This Project

### Basic

**Q1: Why did you use Docker in this project?**
*Testing:* Fundamental understanding of Docker's purpose.
*Strong answer:* To get a reproducible local dev environment for infrastructure that would otherwise require manually installing and configuring Postgres, Redis, Redpanda (Kafka), and ClickHouse, and to package the FastAPI services into portable images that run unmodified from a laptop (Docker Compose) through to a Kubernetes cluster (k3d/Helm) — same image, different injected environment.
*Follow-up:* "What would break if you didn't use Docker for the infra services?" — Answer: every teammate would need to install and version-match Postgres 16, Redis 7, Redpanda v26.1.11, and ClickHouse 26.3 by hand, and CI would need a different setup process than local dev.
*Do NOT claim:* that Docker is used for hot-reload local development of the app code — it isn't; there's no bind mount or `--reload` flag anywhere.

**Q2: What does your Dockerfile actually do, step by step?**
*Testing:* Whether you actually understand your own build, not just that it "works."
*Strong answer:* Walk through `apps/eval_service/Dockerfile` line by line — `python:3.10-slim` base, `WORKDIR /app`, copy+install `requirements.txt` first for layer caching, then copy `apps/api`, `apps/eval_service`, `agents`, and `config` in that order, `touch apps/__init__.py` to make the package importable, `EXPOSE 8001`, and `CMD` runs uvicorn directly.
*Follow-up:* "Why copy requirements.txt separately before the rest of the code?" — layer caching: pip install is skipped on rebuild unless requirements.txt itself changed.
*Do NOT claim:* that there's a `.dockerignore` — there isn't one in this repo.

**Q3: What's the difference between an image and a container, in the context of your project?**
*Testing:* Basic conceptual clarity.
*Strong answer:* The image (`redline-eval_service:<tag>`) is the built, immutable artifact from the Dockerfile — a stopped, non-running thing. The container is a running instance of that image, with environment variables injected at `docker compose up` time (not baked into the image) and connected to the Compose network.
*Follow-up:* "If you ran the same image twice, would you get two identical containers?" — Only if given different names/ports; in this compose file each service is a single named container (`container_name:`), not scaled.

### Project-specific

**Q4: Why is the build context the repo root and not each service's own subdirectory?**
*Testing:* Understanding of Docker build context mechanics.
*Strong answer:* Because each service's Dockerfile needs to `COPY` from `apps/api` (the shared library) and `config/` (model profiles), which live outside the service's own directory — Docker can only copy files that are inside the build context, so the context has to be the common ancestor, the repo root.
*Follow-up:* "What's the downside of a repo-root build context here?" — No `.dockerignore` means the entire repo (including `.git`, docs, helm charts, tests) is sent to the Docker daemon on every build, slowing builds down even though most of it is never copied into the image.

**Q5: Why does `agent_service`'s Dockerfile not copy the `agents/` directory, but `eval_service`'s does?**
*Testing:* Whether you understand the actual service boundaries, not just copy-pasted the Dockerfile.
*Strong answer:* `eval_service` runs the eval engine, which imports and executes agent code directly via `LocalPythonAdapter`'s `importlib`-based loading — it needs the actual agent source present in the container. `agent_service` only manages the agent *registry* (metadata, versions, eval suites) — it never imports or runs agent code, so it doesn't need that directory.

**Q6: Why is Postgres exposed on host port 5433 instead of the standard 5432?**
*Testing:* Attention to detail / real debugging history.
*Strong answer:* To avoid colliding with a Postgres instance already installed locally on the developer's machine on the default port. `.env.example`'s comments describe a separate, related bug: `127.0.0.1` vs `localhost` resolving differently on a dual-stack machine caused password-auth failures once, which is why `DATABASE_URL` in `.env.example` pins the literal IPv4 address rather than the hostname.

**Q7: Why does the gateway's nginx config get both baked into the image AND bind-mounted at runtime?**
*Testing:* Understanding of image-build-time vs. container-runtime configuration layering.
*Strong answer:* The image bakes in `infra/gateway.nginx.conf` so the image is self-contained and portable to environments without a bind mount (like a Kubernetes pod). Locally, `docker-compose.yml` *also* bind-mounts the same file over the baked-in copy, so editing nginx config and restarting the container picks up changes without a full image rebuild — only the dashboard's static `dist/` build genuinely requires a rebuild.

**Q8: Why does Redpanda declare three separate listeners instead of one?**
*Testing:* Real distributed-systems/networking depth — this is the hardest, most specific question in the repo.
*Strong answer:* Kafka's (and Redpanda's) protocol has clients reconnect to whatever address the broker *advertises* in its metadata, not necessarily the address they first connected to. A single "external" listener advertising `localhost:19092` works fine for a host-run process, but breaks for a pod inside a k3d cluster: that pod resolves `localhost` to itself, not the Mac host, so every call after the initial bootstrap fails with connection refused. The dedicated `k3d://host.k3d.internal:29092` listener gives k3d pods a distinct, correctly-resolvable advertised address, separate from the `internal` (container-to-container within Compose) and `external` (host-process) listeners.
*Follow-up:* "How did you find this bug?" — be honest here: this is documented in the compose file as a confirmed, previously-encountered issue (dated 2026-07-29 in the comment) — good interview material is being able to explain *why* the fix works, even if you're citing the documented reasoning rather than having debugged it live yourself in this conversation.

### Debugging

**Q9: A container exits immediately after `docker compose up`. What do you check first?**
*Strong answer:* `docker compose logs <service>` first, since there's no hot-reload — an immediate exit is almost always an import-time error (missing dependency, bad path in a `COPY`, or — a real documented bug in this repo — a missing `config/model_profiles.yaml` causing `get_profile()` to raise `FileNotFoundError`, though that specific failure actually happens on the *first eval request*, not at container start, since it's a runtime resolve, not an import).

**Q10: The eval_service can't reach Postgres. Walk me through your debugging path.**
*Strong answer:* Check `docker compose ps` for Postgres's healthcheck status; confirm `DATABASE_URL` inside the running container actually resolves to `postgres` as hostname (`docker compose exec eval_service env`), not `localhost`/`127.0.0.1` (which would be correct for a host-run process but wrong inside a container); confirm `.env` actually has `POSTGRES_USER/PASSWORD/DB` set, since Compose silently substitutes empty strings for unset variables rather than failing the build.

**Q11: Works when you run it directly with `python -m uvicorn` but breaks in `docker compose up`. Why?**
*Strong answer:* This project literally has two different runtime configurations by design — the README's host-run path uses `.env.example`'s `localhost`/`127.0.0.1`-oriented values, while `docker-compose.yml` reconstructs `DATABASE_URL`/`REDIS_URL`/etc. to use Compose service names. A host-only fix (e.g., editing `.env`) won't propagate to the containerized environment variables, which live in `docker-compose.yml`'s own `environment:` block.

### Deeper follow-ups

**Q12 (follow-up to Q1):** "If Docker disappeared tomorrow, what would you have to do to keep this project running?" — Manually install and version-pin Postgres 16, Redis 7, Redpanda v26.1.11, ClickHouse 26.3, and PgBouncer locally; the app services themselves could still run directly via `uvicorn` (as the README's own Quickstart already does), so the app layer's Docker dependency is actually the *weaker* one — infra is where Docker earns its keep here.

**Q13 (follow-up to Q6):** "Why not just use `network_mode: host` to avoid the port-mapping complexity entirely?" — Not used in this repo, and for good reason: `host` networking is Linux-only/unsupported on Docker Desktop for macOS (this project's primary dev target, per the Makefile's `k6-load-test` comment explicitly reasoning about this exact tradeoff for a different but related command), so the project correctly uses per-service published ports instead.

**Q14 (follow-up to Q8):** "Is this Redpanda listener setup something you'd call 'good Docker practice' generally, or is it specific to this project's constraints?" — Be honest: it's a project-specific workaround for a k3d-plus-Compose hybrid topology (infra on Compose, apps on k3d), not a generalizable Docker networking pattern — a single-environment deployment (pure Compose, or pure Kubernetes) wouldn't need three listeners.

**Q15:** "Your Trivy and pip-audit scans in CI don't fail the build. Is that a problem?" — Be candid: yes, currently these are report-only, and the workflow's own comments acknowledge this is a deliberate, temporary state pending a vulnerability baseline triage before flipping to a hard gate — a real, in-progress security posture rather than a finished one.

---

## 20. Interview Ammunition

## How I Should Explain My Docker Experience

In this project I used Docker in two connected but distinct ways. First, for local development, Docker Compose stands up the entire infrastructure layer — Postgres, Redis, Redpanda as our Kafka-compatible event bus, ClickHouse for trace analytics, and Grafana Tempo for distributed tracing — so nobody on the team has to install and version-match six different pieces of infrastructure by hand. Second, I built custom Dockerfiles for our three FastAPI microservices and an nginx API gateway, so those services can be built once and run identically whether that's in Docker Compose locally, or as pods in a Kubernetes cluster via Helm — same image, the environment variables just get injected differently depending on where it's running. One thing I paid attention to was never baking secrets into the image layers — the .env file with our JWT secret and API keys is deliberately excluded from every COPY instruction, and instead gets injected at container-start time through Compose's env_file directive or through Kubernetes Secrets in the Helm chart. I also used a multi-stage build for the gateway specifically, because it bakes in a compiled React dashboard — the first stage runs the Node build toolchain, and the final image only keeps the compiled static output on top of nginx, so we're not shipping node_modules or the Node runtime itself into production. In CI, we reuse the exact same docker-compose.yml for integration tests that developers use locally, which keeps CI honest about actually testing the real setup, and then we build, scan, and — on merges to main — push all four images to GitHub Container Registry.

### 30-second version

I used Docker Compose to containerize our infrastructure — Postgres, Redis, Kafka-compatible Redpanda, ClickHouse — so the whole backend stack comes up with one command, and I wrote Dockerfiles for our three FastAPI microservices plus an nginx gateway so the same images run in local Compose and in a Kubernetes cluster via Helm.

### 60-second version

I used Docker in two layers. Compose runs all our infrastructure — Postgres, Redis, Redpanda, ClickHouse, Tempo — so the team never manually installs any of it, and CI reuses that exact same compose file for integration tests instead of maintaining a separate CI-only setup. On top of that, I wrote Dockerfiles for our three FastAPI services and an nginx gateway that bakes in a compiled React dashboard using a multi-stage build — Node builds the static assets in one stage, and only the compiled output ships in the final nginx-based image. Every service communicates over Docker's internal DNS using service names, never localhost, and secrets are never baked into image layers — they're injected at container start via env files locally or Kubernetes secrets in production. CI builds and vulnerability-scans all four images and pushes them to GHCR on merges to main.

### 2-minute deep-dive version

The project has two Docker layers that solve different problems. The infrastructure layer — Postgres, Redis, Redpanda, ClickHouse, Tempo — runs entirely through Docker Compose, all pulled from public images and version-pinned. That solved the "everyone needs identical infra" problem, and importantly, CI reuses that same compose file for integration tests rather than maintaining a parallel CI-only setup, so what gets tested is what actually runs locally.

The application layer is four custom-built images: three FastAPI microservices and an nginx gateway. Each service Dockerfile follows the same pattern — copy and install the requirements file before copying application code, so dependency installation is a cached layer that only reruns when requirements actually change. None of them bake in the .env file; secrets get injected at container-start time instead, through Compose's env_file locally or through Kubernetes Secrets and ConfigMaps when deployed via our Helm chart to a k3d cluster. That's deliberate — image layers are essentially permanent and inspectable, so anything copied in during the build stays there even if a later step tries to remove it.

The gateway is the one place I used a genuine multi-stage build — a Node stage compiles our React dashboard into static files, and the final image is just that static output sitting on top of nginx, so the Node toolchain and node_modules never ship. There's also a real networking wrinkle worth mentioning: Redpanda needs three separate listeners, not one, because Kafka's protocol has clients reconnect to whatever address the broker advertises, and a pod running inside our k3d cluster needs a different advertised address than a container inside Compose or a process running directly on the host — otherwise it reconnects to itself after the initial handshake.

In CI, once tests pass, all four images get built, scanned with Trivy and pip-audit, and — only on merges to main — pushed to GitHub Container Registry with an immutable commit-SHA tag. There's a Helm deploy job wired up after that, though it's currently inert because we haven't provisioned a live Kubernetes cluster with the right secret yet — it's a real, tested path, just not pointed at a live target.

---

## 21. Resume Claim Validation

**Claim: "I used Docker to containerize the application."**

### Safe claims
- "I containerized the backend infrastructure (Postgres, Redis, Redpanda, ClickHouse, Tempo) using Docker Compose for local development and CI."
- "I wrote custom Dockerfiles for three FastAPI microservices and an nginx API gateway."
- "I used a multi-stage Docker build for the gateway image, separating the Node.js build stage from the nginx runtime stage."
- "I used Docker layer caching by copying dependency manifests before application code in every Dockerfile."
- "I ensured secrets are never baked into image layers, using env files and Kubernetes Secrets instead."
- "The same Docker images run in local Docker Compose and in a Kubernetes cluster (k3d) via Helm, with environment-specific configuration injected at runtime rather than build time."
- "CI builds, vulnerability-scans (Trivy, pip-audit), and pushes all Docker images to GitHub Container Registry on merges to main."
- "I reused the same docker-compose.yml for local dev and CI integration tests, rather than maintaining separate configurations."

### Claims requiring qualification
- "The application has hot-reload/live development via Docker" — **not accurate as stated**; only true with the qualifier "for infrastructure services — the FastAPI application services themselves are built once per image, with no bind mount or reload flag; the everyday dev loop actually runs the API server directly on the host, not in a container."
- "Docker is used for production deployment" — qualify: "the Helm/Kubernetes deployment path is built and tested locally via k3d, and the CI pipeline that would push to a live production cluster exists and is functional, but is currently inert because no live cluster/secret has been provisioned yet."
- "The Docker images are security-hardened" — qualify: "vulnerability scanning is wired into CI (Trivy, pip-audit) but is currently report-only, not blocking; none of the custom images use a non-root USER."

### Claims I should NOT make
- "I used Docker for a full CI/CD pipeline to production" — the deploy stage is explicitly inert; there's no evidence of a live production deployment.
- "The Docker setup includes advanced security hardening (non-root users, distroless images, digest pinning)" — none of these are present.
- "I optimized image size with a `.dockerignore`" — there is no `.dockerignore` in the repo at all.
- "Every service in the project runs in Docker" — the monolith app server and eval worker, per the README's actual Quickstart, run directly on the host, not in a container, in the standard dev flow.

---

## 22. Knowledge Gaps / Potential Interview Traps

Being direct: **the Docker implementation here is solid for infrastructure orchestration and reasonably competent for the application images, but it is not advanced.** A senior interviewer could challenge several things:

- **No `.dockerignore` anywhere in the repo.** This is a genuine, easily-checked gap — if asked "what's in your `.dockerignore`?", the honest answer is "there isn't one," not something to paper over.
- **No `USER` instruction in any custom Dockerfile** — every custom-built container runs as root. This is the most likely "gotcha" question from anyone doing a security-focused interview.
- **No hot-reload dev loop for the containerized app services** — if you claim a smooth "edit code, see it reflected immediately" Docker workflow, that's not true for this repo; the actual smooth loop is running the monolith directly on the host.
- **Base images aren't digest-pinned** — only tag-pinned. A sufficiently paranoid interviewer might ask about supply-chain reproducibility; the honest answer is that this repo relies on tag pinning, which is common but not maximally reproducible.
- **The three FastAPI Dockerfiles are nearly copy-pasted** — if asked "how would you reduce duplication here," the honest answer is that a shared base image or parameterized Dockerfile (`ARG SERVICE_NAME`) isn't used, and that's a legitimate, fair critique, not something to defend as intentional.
- **The `deploy` job in CI is inert** — don't accidentally imply in an interview that this project deploys to a live production Kubernetes cluster; it doesn't, currently. It's built and tested, but has no live target.
- **Trivy/pip-audit are non-blocking** — if you say "we scan for vulnerabilities in CI," a good follow-up is "does a critical CVE block the merge?" and the honest answer right now is no.
- **Redis/Postgres/ClickHouse ports are published to the host** with no additional network restriction — fine for a local/CI-only compose file, but worth knowing this wouldn't be safe as-is on a shared or internet-facing host.
- **The compose file conflates two different roles** (local dev infra vs. the "real" microservice architecture) — the README's actual day-to-day workflow doesn't run the containerized `eval_service`/`agent_service`/`gate_service`/`gateway` at all; those exist primarily for the k3d/Helm deployment path and full-stack CI builds. Don't present the containerized microservices as "how the app runs every day for me," because per the README, they're not — the monolith is.

---

## 23. Final One-Page Cheat Sheet

### Project Docker Architecture

```
Developer → docker compose up -d → Docker Compose
   ├── Infra (public images): postgres, pgbouncer, redis, redpanda,
   │   redpanda-console, clickhouse, tempo
   └── App (built here): eval_service, agent_service, gate_service, gateway
All on Compose's default bridge network, service-name DNS, no custom network.
```

### Images
`redline-eval_service`, `redline-agent_service`, `redline-gate_service` (all single-stage, `python:3.10-slim`), `redline-gateway` (multi-stage: `node:20-alpine` → `nginx:1.27-alpine`). Public: `postgres:16-alpine`, `redis:7-alpine`, `redpandadata/redpanda:v26.1.11`, `clickhouse/clickhouse-server:26.3`, `grafana/tempo:2.5.0`, `edoburu/pgbouncer:v1.25.2-p0`, `redpandadata/console:latest`.

### Containers
11 total in `docker-compose.yml`: 7 infra + 4 app. All `restart: unless-stopped`. Most have `healthcheck:`; app services' healthchecks are raw socket-connect checks, not full `/health`-endpoint checks.

### Networks
One — Compose's default bridge network. No custom networks declared.

### Ports
Gateway `8085→8000`; eval/agent/gate services `8001/8002/8003`; Postgres `5433→5432` (nonstandard, avoids local clash); PgBouncer `6432`; Redis `6379`; Redpanda `19092/29092/18082/9644` (3 purpose-specific listeners); ClickHouse `8123/9000`; Tempo `4317/3200`; Redpanda Console `8080`.

### Volumes
6 named volumes, all infra data: `redline_pg_data`, `redline_redis_data`, `redline_redpanda_data`, `redline_ch_data`, `redline_ch_logs`, `redline_tempo_data`. Survive `docker compose down` (no `-v`). No app-service volumes (stateless, disposable containers).

### Environment Variables
`.env` (gitignored) + `.env.example` (committed template). App services get `env_file: .env` plus a reconstructed `environment:` block pointing `DATABASE_URL`/`REDIS_URL`/etc. at Compose service names. No Dockerfile `ENV`/`ARG` used anywhere. No secrets baked into any image.

### Docker Compose
Single `docker-compose.yml` used for local dev AND CI integration tests (same file, no drift). `depends_on` uses `condition: service_healthy` gating. Service-name DNS used correctly everywhere; `localhost` only appears for Redpanda's host-process listener, which is intentional.

### CI/CD
`ci.yml`: builds all 4 images (matrix), runs pip-audit + Trivy (both non-blocking currently), pushes to GHCR on `main` only, then an inert `helm upgrade --atomic` deploy job (no live cluster/secret yet). `agentbench-check.yml`: separate, Docker-free, CLI-only HTTP gate check against a live instance.

### Deployment
Local k3d path is real and working (Makefile: `images-build` → `images-import` → `helm-upgrade`). Cloud production deployment path exists in CI but is currently inert (no `KUBE_CONFIG` secret provisioned).

### Important Dockerfile Decisions
- Dependency files copied before app code (layer caching) in all 4 Dockerfiles.
- `.env` deliberately never copied into any image — documented reasoning in every Dockerfile.
- `config/` copied into every service so `get_profile()` doesn't `FileNotFoundError` at runtime.
- `agent_service` skips copying `agents/` (doesn't execute agent code); `eval_service` includes it (does).
- Gateway is the only multi-stage build; nginx config is both baked in AND bind-mounted (image is portable; local dev doesn't need a rebuild to iterate on nginx config).

### Top 10 Interview Questions
1. Why Docker here — infra reproducibility + portable images across Compose and k3d.
2. Walk through the eval_service Dockerfile line by line.
3. Why is build context the repo root, not the service subdirectory?
4. Why doesn't agent_service copy `agents/` but eval_service does?
5. Why is Postgres on host port 5433, not 5432?
6. Why three Redpanda listeners instead of one?
7. Why bake nginx config into the gateway image AND bind-mount it?
8. What happens to data on `docker compose down`? (survives — named volumes persist without `-v`)
9. Is your vulnerability scanning actually blocking merges? (no — currently report-only)
10. Does your containerized microservice stack match your everyday local dev loop? (no — README's day-to-day flow runs the monolith on the host)

### Biggest Docker Weaknesses / Risks
No `.dockerignore`; no `USER` (all custom containers run root); no digest-pinned base images; near-duplicate Dockerfiles across 3 services; Trivy/pip-audit non-blocking; no hot-reload for containerized app code; `deploy` CI job currently inert (no live target).

### 5 Things I MUST Remember
1. There is **no `.dockerignore`** anywhere in this repo — don't claim one exists.
2. **No Dockerfile uses `USER`** — every custom container runs as root.
3. The **everyday local dev loop runs the monolith directly on the host**, not in Docker — the containerized microservices are for the k3d/Helm path and CI builds.
4. **Vulnerability scanning in CI is non-blocking** (Trivy `exit-code: 0`, pip-audit `|| true`) — don't claim it gates merges.
5. The **production deploy job in CI is real but currently inert** — no live Kubernetes cluster/secret has been provisioned yet.
