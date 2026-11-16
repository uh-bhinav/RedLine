# Infra Hardening (Phase 5.1)

**Status:** Tempo tracing, dead-letter queue, PgBouncer, and ClickHouse least-privilege user are
all shipped and verified against real infrastructure. JWT rotation is a documented runbook, no
code change. mTLS between services is explicitly deferred — see the last section.

This doc is the single reference for all of Phase 5.1's operational procedures.

---

## Tempo tracing

`apps/api/core/telemetry.py` now exports spans via `OTLPSpanExporter` to Grafana Tempo instead of
`ConsoleSpanExporter`. Tempo runs as a new `tempo` service in `docker-compose.yml`, listening on
`:4317` (OTLP gRPC receiver) and `:3200` (query API).

### Starting it

```bash
docker compose up -d tempo
```

Tracing is never load-bearing — `tempo`'s `depends_on` entries on `eval_service`/`agent_service`/
`gate_service` use `condition: service_started`, not `service_healthy`, so a slow or absent Tempo
never blocks API startup. The exporter itself has a bounded `timeout=5` (seconds) so an
unreachable Tempo fails an export attempt fast rather than hanging.

### Verifying traces are landing

```bash
# Trigger any eval run, then:
curl "http://localhost:3200/api/search?tags=service.name%3Dredline&limit=5"
```

Should return at least one trace once an eval run or any code path calling `tracer` has executed.

### Viewing traces in Grafana

No automated datasource provisioning is wired up (the existing `make monitoring-install` has no
values-file/provisioning pattern to extend, and building that from scratch was out of proportion
to this pass). One-time manual step:

1. `make monitoring-port-forward` (or however you're reaching Grafana — port 3000 by default).
2. In Grafana: Connections → Data sources → Add data source → Tempo.
3. URL: `http://host.k3d.internal:3200` (k3d) or `http://localhost:3200` (docker-compose only).

---

## Dead-letter queue

A job that fails is no longer permanently terminal on its first failure. `eval_worker_v2.py` and
`load_worker.py` now call `RedpandaEvalWorker.retry_or_dead_letter()` on exception: the message is
republished to the same topic with an incremented `retry_count` if under `max_job_retries`
(default 3), or to `<topic>.dead-letter` once exhausted.

### Inspecting a dead-letter topic

```bash
# Via the Redpanda container:
docker exec redline_redpanda rpk topic consume eval.requested.dead-letter --brokers localhost:9092

# Or via the Redpanda Console UI already running at:
http://localhost:8080
```

Each dead-lettered message's JSON body includes `retry_count` (how many times it was retried) and
`final_error` (the last exception's text).

### Manual requeue

There is no automated replay tool in this pass — that's a larger feature. To manually requeue a
dead-lettered job, re-publish its `payload` via a fresh API call (e.g. `POST /eval-runs` with the
same `agent_version_id`/`suite_id` for an eval job) after fixing whatever caused the original
failures.

### Tuning the retry limit

`MAX_JOB_RETRIES` env var (default 3, see `apps/api/core/config.py`).

---

## PgBouncer (opt-in)

PgBouncer runs as a new `pgbouncer` service in `docker-compose.yml`, listening on host port
`6432`, transaction-pooling mode, pointed at the existing `postgres` container.

**Not the default.** Every service's `DATABASE_URL` still points directly at Postgres (`:5433`
host / `:5432` in-container) unless you opt in. This is a blast-radius decision, not an oversight —
changing the default DB path for every service has no benefit yet at current local-dev scale, and
becomes worthwhile only when a real deployment's connection count actually needs the relief
(Phase 5.4, deferred).

### Switching on

1. Point `DATABASE_URL` at PgBouncer instead of Postgres directly:
   ```
   DATABASE_URL=postgresql+psycopg2://redline:redline_dev_password@127.0.0.1:6432/redline
   ```
2. Set `DB_USE_EXTERNAL_POOLER=true`.

This flips `apps/api/core/db.py`'s SQLAlchemy engine to `poolclass=NullPool` — required, because
PgBouncer's own transaction-mode pool underneath a second, independent `QueuePool` would
double-pool, defeating the point of adding a pooler in the first place. With `NullPool`, every
checkout is a fresh connection *to PgBouncer*, which is exactly what PgBouncer is designed to pool
on the Postgres side.

### Verifying

```bash
docker compose up -d pgbouncer
psql postgresql://redline:redline_dev_password@localhost:6432/redline -c "SELECT 1;"
```

---

## ClickHouse least-privilege user

`init_clickhouse()` now creates a `redline_app` user (`SELECT, INSERT` only) instead of every
service running as the ClickHouse superuser (`default`). DDL (`CREATE DATABASE`/`CREATE TABLE`)
and the `CREATE USER`/`GRANT` statements all run via a separate admin client — never via
`get_clickhouse()`, which is the request-path client every service actually uses.

### Bootstrap credentials vs. app credentials

Two separate credential pairs, both read from settings:

| Setting | Purpose | Default |
|---|---|---|
| `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` | App-runtime identity (`emit_trace`, `emit_load_samples`, dashboard reads) | `redline_app` |
| `CLICKHOUSE_ADMIN_USER` / `CLICKHOUSE_ADMIN_PASSWORD` | Bootstrap-only, used solely by `init_clickhouse()` | `default` (the container's own superuser) |

Helm-deployed pods only ever get the app credentials (`values.yaml`'s `infra.clickhouseUser`/
`clickhousePassword`) — admin credentials never reach the cluster, since deployed pods never run
`init_clickhouse()`.

### One-time container config change required

The container's bootstrap `default` user does **not** have `access_management` rights by default
(confirmed: `CREATE USER` fails with "Not enough privileges" against a stock container). A new
`<users><default><access_management>1</access_management>` block was added to
`infra/clickhouse-users.xml` (which already existed for a memory-profile override, and is now also
mounted at `/etc/clickhouse-server/users.d/init-users.xml`). This is required for `init_clickhouse()`
to run `CREATE USER`/`GRANT` at all — restart the ClickHouse container after pulling this change if
your existing container predates it:

```bash
docker compose up -d clickhouse --force-recreate
```

### Running the migration

```bash
python -m apps.api.scripts.init_clickhouse
```

Idempotent — safe to re-run. Prints a confirmation line once the least-privilege user is ready.

### Verifying least-privilege actually holds

```bash
# Should succeed (SELECT):
clickhouse-client --user redline_app --password <pw> --query "SELECT 1 FROM redline.traces LIMIT 1"

# Should FAIL with ACCESS_DENIED (no CREATE right):
clickhouse-client --user redline_app --password <pw> --query "CREATE TABLE redline.foo (x Int32) ENGINE=Memory"
```

---

## JWT_SECRET_KEY rotation

**No code change — this is a runbook.** The blast radius was verified before deciding scope:
`rotate_refresh_token()` in `apps/api/core/auth.py` validates refresh tokens purely via SHA-256
hash lookup in Postgres (`RefreshToken.token_hash`) — it never calls `jwt.decode`, so **refresh
tokens are entirely unaffected by a signing-key rotation.** Only access tokens
(`ACCESS_TOKEN_EXPIRE_MINUTES = 15`) are affected. The CLI and CI authenticate via API key, not
JWT, so they're unaffected too — the only JWT consumer is dashboard v1's paste-a-token flow
(ADR-006), where rotation just means re-fetching a token via `/auth/login`.

### Routine rotation

1. Generate a new secret:
   ```bash
   openssl rand -hex 32
   ```
2. **Local (docker-compose):** update `.env`'s `JWT_SECRET_KEY`, then:
   ```bash
   docker compose restart eval_service agent_service gate_service
   ```
3. **k3d/Helm:** Kubernetes does not auto-restart pods on a Secret change, so both steps are
   required:
   ```bash
   JWT_SECRET_KEY=<new-secret> make helm-upgrade
   kubectl rollout restart deployment/eval-service deployment/agent-service deployment/gate-service -n redline
   ```
4. Confirm: a pre-rotation access token now 401s; `/auth/refresh` with a pre-rotation refresh
   token still succeeds (proves the refresh flow is genuinely unaffected, as expected).

### Incident response (suspected leak, not routine rotation)

A leaked signing key lets an attacker mint arbitrary *access* tokens (not refresh tokens) until
rotation completes. In addition to the routine steps above, revoke all outstanding refresh tokens
so a compromised refresh token can't mint further access tokens post-rotation either:

```sql
UPDATE refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL;
```

This forces every user to log in again — appropriate for a suspected-leak scenario, not for
routine rotation.

---

## mTLS between services — explicitly deferred

Confirmed via `grep -r "cert-manager\|mtls\|tls" helm/ apps/` (excluding the plain-HTTP nginx
gateway config, which isn't TLS): there is genuinely zero existing TLS/service-mesh infrastructure
anywhere in this repository.

**Out of scope for this pass.** mTLS needs either a service mesh (Istio/Linkerd) or cert-manager
plus manual cert rotation — both are deployment-topology decisions properly deferred to Phase 5.4
(public deployment), since a local k3d cluster gains little from mTLS while a real multi-node
deployment target does. Tracked as future work, not silently dropped.
