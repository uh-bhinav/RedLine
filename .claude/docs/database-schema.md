# RedLine Database Schema Reference

Complete schema for all 13 tables. Use this to reconstruct the schema from scratch or to verify migrations are correct.

---

## Migration History

| Migration | File | What It Added |
|-----------|------|---------------|
| 0001 | `0001_initial_schema.py` | Core 10 tables: tenants, users, api_keys, agents, agent_versions, eval_suites, eval_cases, eval_runs, eval_case_results, gate_policies, jobs |
| 0002 | `0002_add_entrypoint_col.py` | `entrypoint TEXT NOT NULL` column on `agent_versions` — added post-Phase-1 to support `LocalPythonAdapter` importlib resolution |
| 0003 | `0003_add_refresh_tokens.py` | `refresh_tokens` table for JWT refresh token rotation (Phase 2 auth hardening) |
| 0004 | `0004_add_drift_tables.py` | `drift_snapshots` and `drift_alerts` tables for Phase 2 drift detection |

Apply all migrations:

```bash
alembic upgrade head
```

Check current state:

```bash
alembic current
alembic history
```

---

## Storage Architecture Decision

**Postgres** stores all relational metadata: tenants, users, agents, eval runs, results, policies, jobs. Postgres is chosen because:
- The data is highly relational (eval_cases → eval_runs → eval_case_results are FK-linked)
- `SKIP LOCKED` on the jobs table enables correct multi-worker job dispatch without a lock manager
- Single source of truth for all gate decisions and CI check outcomes

**ClickHouse** stores all trace events emitted during eval runs. ClickHouse is chosen because:
- Trace data is append-only (never updated, never deleted in normal operation)
- High cardinality columns (run_id, case_key, event_type, timestamps) benefit from ClickHouse's column-oriented compression
- Postgres would choke at scale on millions of trace rows per day
- ClickHouse queries on traces are analytic (GROUP BY, aggregation) not transactional
- Trace write failures are non-fatal — ClickHouse's eventual consistency model is acceptable here

---

## Table 1: `tenants`

```sql
CREATE TABLE tenants (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Notes:** Every other table has a `tenant_id FK` referencing this table. Phase 1 has one seeded tenant. Multi-tenancy enforcement is Phase 3.

**Seeded value:** `c1caeaf6-d6ab-4f93-99d8-25907cfebd6d` (name: "RedLine Dev")

---

## Table 2: `users`

```sql
CREATE TABLE users (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL REFERENCES tenants(id),
    email            TEXT        NOT NULL UNIQUE,
    hashed_password  TEXT        NOT NULL,
    role             TEXT        NOT NULL CHECK (role IN ('admin', 'developer', 'viewer')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_users_email ON users(email);
```

**Constraints:**
- `email` is globally unique (UNIQUE constraint)
- `role` must be one of `admin`, `developer`, `viewer` — enforced at DB level
- `hashed_password` is always bcrypt via `passlib.CryptContext(schemes=["bcrypt"])`

**Seeded value:** `admin@redline.local` / `ChangeMe123!` (role: `admin`)

---

## Table 3: `api_keys`

```sql
CREATE TABLE api_keys (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id),
    name        TEXT        NOT NULL,
    key_hash    TEXT        NOT NULL UNIQUE,
    role        TEXT        NOT NULL CHECK (role IN ('admin', 'developer', 'viewer')),
    revoked_at  TIMESTAMPTZ NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Constraints:**
- `key_hash` is `SHA256(raw_key)` in hex — the raw key (prefixed `rl_live_`) is shown once and never stored
- `revoked_at` is NULL for active keys; set to a timestamp to revoke

**Generation pattern:**

```python
import secrets, hashlib
raw_key = "rl_live_" + secrets.token_urlsafe(32)
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
```

---

## Table 4: `refresh_tokens`

*(Added in migration 0003)*

```sql
CREATE TABLE refresh_tokens (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id),
    token_hash  TEXT        NOT NULL UNIQUE,
    role        TEXT        NOT NULL CHECK (role IN ('admin', 'developer', 'viewer')),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens(user_id);
```

**Constraints:**
- `token_hash` is `SHA256(raw_token)` — raw token is returned to client once
- `revoked_at` nullable — NULL means active, non-NULL means revoked
- On refresh token reuse detection: ALL tokens for that `user_id` are revoked immediately (not just the replayed one)
- Token lifetime: 7 days (`expires_at = now() + timedelta(days=7)`)

---

## Table 5: `agents`

```sql
CREATE TABLE agents (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id),
    name        TEXT        NOT NULL,
    description TEXT        NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
```

**Seeded value:** `b8003a26-f601-4c32-a4f3-7ac4fe502cad` (name: "rag-agent")

---

## Table 6: `agent_versions`

```sql
CREATE TABLE agent_versions (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id       UUID        NOT NULL REFERENCES agents(id),
    version_label  TEXT        NOT NULL,
    model_name     TEXT        NOT NULL,
    content_hash   TEXT        NOT NULL,
    entrypoint     TEXT        NOT NULL,  -- Added in migration 0002
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, content_hash)
);
```

**Constraints:**
- `content_hash` is `SHA256(source_file_bytes)` — 64-character hex string
- `UNIQUE (agent_id, content_hash)` prevents duplicate versions from accidental re-registration
- `entrypoint` is a Python import path: `agents.rag_agent.agent:run_turn`

**Seeded values:**
- Version v1 ID: `a259d9c5-9a89-4cbf-9060-edea9d29b325`
- Content hash: `842a7a049760e678715704267b94307ce0812ba43b15dbb3127891849f9f5280`

---

## Table 7: `eval_suites`

```sql
CREATE TABLE eval_suites (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    UUID        NOT NULL REFERENCES agents(id),
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, name)
);
```

**Seeded value:** `b2d571f2-d350-48fd-b485-7fc4273dc743` (name: "baseline", agent: rag-agent)

---

## Table 8: `eval_cases`

```sql
CREATE TABLE eval_cases (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    suite_id     UUID        NOT NULL REFERENCES eval_suites(id),
    case_key     TEXT        NOT NULL,
    description  TEXT        NOT NULL,
    turns        JSONB       NOT NULL,
    expectations JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (suite_id, case_key)
);
```

**`turns` JSONB schema:**

```json
[
  {"role": "user", "content": "How many days to return?"},
  {"role": "user", "content": "Does that apply internationally?"}
]
```

**`expectations` JSONB schema:**

```json
{
  "contains": ["30 days"],
  "must_not_contain": ["+1", "phone:"],
  "judge_rubric": "The agent must decline politely...",
  "max_cost_usd": 0.01,
  "max_latency_ms": 5000
}
```

All fields optional — only scorers whose key appears in `expectations` are run for that case.

---

## Table 9: `eval_runs`

```sql
CREATE TABLE eval_runs (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID        NOT NULL REFERENCES tenants(id),
    agent_version_id  UUID        NOT NULL REFERENCES agent_versions(id),
    suite_id          UUID        NOT NULL REFERENCES eval_suites(id),
    status            TEXT        NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    triggered_by      TEXT        NOT NULL CHECK (triggered_by IN ('manual', 'ci')),
    started_at        TIMESTAMPTZ NULL,
    completed_at      TIMESTAMPTZ NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_eval_runs_status ON eval_runs(status);
CREATE INDEX ix_eval_runs_agent_version_id ON eval_runs(agent_version_id);
```

**Status transitions:** `pending` → `running` → `completed` or `failed`. No backwards transitions.

---

## Table 10: `eval_case_results`

```sql
CREATE TABLE eval_case_results (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_run_id     UUID        NOT NULL REFERENCES eval_runs(id),
    case_id         UUID        NOT NULL REFERENCES eval_cases(id),
    passed          BOOLEAN     NOT NULL,
    metrics         JSONB       NOT NULL,
    transcript      JSONB       NOT NULL,
    scorer_results  JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_eval_case_results_eval_run_id ON eval_case_results(eval_run_id);
```

**`metrics` JSONB schema:**

```json
{"latency_ms": 1842, "cost_usd": 0.0034, "turns_count": 2, "tool_calls_count": 1}
```

**`scorer_results` JSONB schema:**

```json
{
  "contains_match": {"passed": true, "detail": "Found '30 days' in response"},
  "cost": {"passed": true, "detail": "0.0034 <= 0.01"},
  "llm_judge": {"passed": false, "detail": "Response did not address international shipping"}
}
```

---

## Table 11: `gate_policies`

```sql
CREATE TABLE gate_policies (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID        NOT NULL REFERENCES agents(id) UNIQUE,
    min_pass_rate       FLOAT       NOT NULL DEFAULT 0.9,
    max_avg_cost_usd    FLOAT       NULL,
    max_avg_latency_ms  FLOAT       NULL
);
```

**Constraints:**
- `UNIQUE (agent_id)` — one policy per agent
- A missing `GatePolicy` for an agent defaults to `min_pass_rate=0.9` in the gate engine (never auto-passes)
- `max_avg_cost_usd` and `max_avg_latency_ms` being NULL means "no check for this threshold"

---

## Table 12: `jobs`

```sql
CREATE TABLE jobs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id),
    job_type    TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    result      JSONB       NULL,
    error       TEXT        NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_jobs_status ON jobs(status);
```

**Worker query uses `SKIP LOCKED`:**

```sql
SELECT * FROM jobs
WHERE status = 'pending' AND job_type = 'eval.requested'
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

This prevents two worker processes from claiming the same job simultaneously.

---

## Table 13: `drift_snapshots`

*(Added in migration 0004)*

```sql
CREATE TABLE drift_snapshots (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_version_id  UUID        NOT NULL REFERENCES agent_versions(id),
    suite_id          UUID        NOT NULL REFERENCES eval_suites(id),
    eval_run_id       UUID        NOT NULL REFERENCES eval_runs(id),
    pass_rate         FLOAT       NOT NULL,
    total_cases       INT         NOT NULL,
    passed_cases      INT         NOT NULL,
    avg_cost_usd      FLOAT       NOT NULL,
    avg_latency_ms    FLOAT       NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_drift_snapshots_agent_version ON drift_snapshots(agent_version_id, created_at DESC);
```

---

## Table 14: `drift_alerts`

*(Added in migration 0004)*

```sql
CREATE TABLE drift_alerts (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_version_id  UUID        NOT NULL REFERENCES agent_versions(id),
    suite_id          UUID        NOT NULL REFERENCES eval_suites(id),
    drift_type        TEXT        NOT NULL CHECK (drift_type IN ('model', 'behavior', 'rag')),
    baseline_pass_rate FLOAT      NOT NULL,
    current_pass_rate  FLOAT      NOT NULL,
    delta             FLOAT       NOT NULL,
    threshold         FLOAT       NOT NULL,
    detail            TEXT        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**`drift_type` values:**
- `model` — pass rate degraded beyond threshold (model version changed upstream)
- `behavior` — cost or latency regressed significantly
- `rag` — retrieval quality degraded (RAG-specific metrics)

---

## ClickHouse Schema

Database: `redline`, Table: `traces`

```sql
CREATE TABLE IF NOT EXISTS redline.traces (
    run_id      String,
    case_key    String,
    event_type  String,
    data        String,   -- JSON blob
    created_at  DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (run_id, created_at);
```

Created by: `python -m apps.api.scripts.init_clickhouse`

**Why MergeTree:** Append-only workload with high-throughput inserts. Sorted by `(run_id, created_at)` for efficient per-run trace retrieval.
