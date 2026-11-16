# RedLine Architecture Decisions

All five architecture decisions that shaped the Phase 2 build. Each entry includes the rejected alternative and the trigger that would prompt re-evaluation.

---

## Decision 1: `confluent-kafka` Over `aiokafka`

**Context:** Phase 2 added Redpanda as the event bus. Two Python Kafka clients were candidates: `confluent-kafka` (synchronous, librdkafka C binding) and `aiokafka` (async, pure Python).

**Decision:** Use `confluent-kafka 2.14.2`.

**Reasoning:**
- The eval engine is **synchronous** by design. `run_eval()`, all scorers, the gate engine, and SQLAlchemy sessions are all synchronous.
- Mixing `aiokafka` (which requires an asyncio event loop) with a synchronous eval engine would require either: (a) running the event loop in a separate thread, introducing race conditions around the SQLAlchemy Session, or (b) making the entire eval pipeline async, which would require rewriting `run_eval()`, all scorers, and the ORM access layer.
- `confluent-kafka` is backed by `librdkafka` — battle-tested in production Kafka systems at scale, not a pure-Python reimplementation.
- Redpanda is Kafka-compatible, so `confluent-kafka` works against it without modification.

**Rejected alternative:** `aiokafka` — would require async eval engine and AsyncSession, a rewrite of the core loop.

**Review trigger:** If Phase 3 or Phase 4 requires a fully async microservice model and the eval engine is rewritten to async. At that point, `aiokafka` becomes viable. Do not make this change until the eval engine is fully async.

---

## Decision 2: Postgres Password Must Match Volume Initialization

**Context:** During Phase 2 infra setup, `docker compose up` started Postgres successfully but `alembic upgrade head` failed with `authentication failed for user "redline"`.

**Root cause:** Docker Postgres initializes the `POSTGRES_PASSWORD` from the environment variable on **first container start only**. If the data volume already exists with a different password from a previous `docker compose up`, the new `POSTGRES_PASSWORD` value in `docker-compose.yml` is ignored. The volume retains the original password.

**Decision:** When changing `POSTGRES_PASSWORD`, always destroy the data volume and reinitialize:

```bash
docker compose down -v      # -v destroys named volumes
docker compose up -d
alembic upgrade head
python -m apps.api.scripts.seed
```

Alternatively, use `ALTER USER` without destroying the volume:

```bash
docker exec -it redline_postgres psql -U postgres -c "ALTER USER redline WITH PASSWORD 'new_password';"
```

Then update `DATABASE_URL` in `.env` to match.

**Rejected alternative:** Accepting a broken auth state and patching config files to match an unknown volume password — creates drift between what the codebase documents and what's running.

**Review trigger:** If a secrets management system (Vault, AWS Secrets Manager) is integrated in Phase 4, Postgres credentials will be rotated dynamically. At that point, the volume-initialization issue is moot. Until then, this manual procedure applies.

---

## Decision 3: KEDA Consumer Lag Over CPU HPA for Workers

**Context:** Phase 2 deployed the eval worker to k3d and needed an autoscaling strategy. Two options: CPU-based HPA (scale when CPU > X%) or KEDA ScaledObject on Redpanda consumer lag.

**Decision:** Use KEDA with `kafkaLag` trigger on `eval-jobs` topic, `eval-worker-group` consumer group.

**Reasoning:**
- The eval worker is **I/O-bound**, not CPU-bound. A worker running 5 concurrent Gemini API calls (each with a 2–5s latency) uses <10% CPU even at full capacity. CPU HPA would never trigger scaling.
- Consumer lag directly measures the work backlog — if 100 eval runs are queued, consumer lag = 100. This is the correct signal for scaling.
- KEDA can scale to **0 replicas** when lag = 0 (no pending jobs). CPU HPA cannot scale to 0.
- The eval-service and agent-service pods are stateless API handlers. They ARE CPU-bound (request parsing, auth, DB queries). Those use CPU HPA.

**Configuration in `helm/redline/templates/worker/scaledobject.yaml`:**

```yaml
triggers:
  - type: kafka
    metadata:
      bootstrapServers: host.k3d.internal:19092
      consumerGroup: eval-worker-group
      topic: eval-jobs
      lagThreshold: "5"    # Scale up when 5+ unprocessed jobs per replica
```

**Important:** Never set `spec.replicas` in the eval worker Deployment YAML. KEDA owns replica count. Setting it manually will fight KEDA.

**Rejected alternative:** CPU HPA for workers — useless for I/O-bound workloads, would never trigger.

**Review trigger:** If the eval engine becomes CPU-bound (e.g., heavy local embedding computation replaces Gemini API calls), revisit CPU HPA. Until then, consumer lag is the correct metric.

---

## Decision 4: Model Profiles Over Provider-Coupled Rate Limiting

**Context:** Phase 2 added rate limiting for Gemini API calls. Initial approach: hardcode rate limits per provider (`gemini_rpm = 15`, `openai_rpm = 60`). Rejected.

**Decision:** Use a model profile system (`config/model_profiles.yaml`) where each profile declares its own `rpm` limit. Agents request a profile name, never a model name.

```yaml
# config/model_profiles.yaml
profiles:
  standard:
    model_name: gemini-2.0-flash
    provider: google
    rpm: 15
  high_reasoning:
    model_name: gemini-2.5-flash
    provider: google
    rpm: 10
  cheap:
    model_name: gemini-2.0-flash-lite
    provider: google
    rpm: 30
```

**Reasoning:**
- Eval suites must be **provider-agnostic**. A suite declaring `model_profile: standard` continues to work if `standard` is remapped to `claude-sonnet-4-6` in `model_profiles.yaml`. Zero changes to eval suite YAML or agent code.
- Rate limits are per-model (not per-provider). Different models from the same provider have different RPM limits. Provider-level rate limiting is too coarse.
- The LLM judge scorer always uses `gemini-2.5-flash` (via `high_reasoning` profile) regardless of the agent under test. This decouples judge cost from agent model cost.

**Rejected alternative:** Hardcoding model names in agent files and provider-level rate limits — creates coupling between eval suites and provider, requires code changes to switch models.

**Review trigger:** When a new provider is added (OpenAI, Anthropic). Add a new profile in `config/model_profiles.yaml`. No Python code changes needed if the `LLMRateLimiter` and agent code are already using `get_profile()`.

---

## Decision 5: In-Process Rate Limiter Over Redis for Phase 2

**Context:** Phase 2 has a single eval worker process. Multiple simultaneous Gemini API calls from a single worker need to be rate-limited. Two approaches: in-process sliding window (deque) or Redis sorted set (distributed).

**Decision:** Use `LLMRateLimiter` — an in-process sliding window deque in `apps/api/core/llm_rate_limiter.py`.

```python
class LLMRateLimiter:
    def __init__(self, rpm: int):
        self._rpm = rpm
        self._requests: deque[float] = deque()  # timestamps of recent requests
    
    def acquire(self):
        now = time.time()
        window = 60.0
        # Remove timestamps older than 60 seconds
        while self._requests and self._requests[0] < now - window:
            self._requests.popleft()
        if len(self._requests) >= self._rpm:
            sleep_time = self._requests[0] + window - now
            time.sleep(sleep_time)
        self._requests.append(time.time())
```

**Reasoning:**
- Phase 2 runs **exactly one worker process**. A distributed Redis lock adds infrastructure complexity (Redis round-trips, potential lock expiry bugs) with zero benefit when there's only one process.
- The in-process deque is deterministic, has zero latency overhead, and needs no external dependency.
- The Phase 2 eval worker is sequential (one eval run at a time) — concurrency within a single process is limited.

**Rejected alternative:** Redis sorted set rate limiting — correct for Phase 3 multi-worker deployment, but over-engineered for single-worker Phase 2.

**Review trigger:** **Phase 3.** When multiple eval worker pods run in k3d, each with its own process, the in-process deque cannot coordinate across processes. Multiple workers will independently hit Gemini at full RPM, causing 429s. At Phase 3, replace `LLMRateLimiter` with a Redis-backed implementation. The calling code (`acquire()` before every LLM call) does not change — only the implementation.
