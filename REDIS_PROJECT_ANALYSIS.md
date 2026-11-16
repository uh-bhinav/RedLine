# Redis Implementation Analysis — RedLine

Code-first. Every entry below is: **concept → exact file/line → actual code → what it does at runtime**. Theory is not explained — only which concepts are implemented, where, and how. If something wasn't found, it says "Not found in repository" rather than being assumed.

---

## 1. Executive Summary

**Why Redis is used:** RedLine runs multiple processes/pods (KEDA autoscales `eval-worker` on Kafka consumer lag). Three things need cross-process agreement that an in-memory structure can't provide: (1) one rate-limit counter per tenant across API replicas, (2) one LLM-provider quota budget across worker pods, (3) preventing two pods from processing the same at-least-once-delivered Kafka message.

**Components that use it:** `apps/api/main.py` (HTTP middleware), `apps/api/core/llm_rate_limiter.py` (every LLM call path: 3 agents + `embeddings.py` + `llm_judge.py`), `apps/api/core/redpanda_queue.py` (job status cache), `apps/api/workers/eval_worker_v2.py` + `apps/api/workers/load_worker.py` (dedup lock).

**Usage type:** cache + rate limiter (two separate implementations) + distributed lock. Not a primary datastore, not a message broker.

**Critical or optional:** optional by explicit design for one component (`LLMRateLimiter` catches Redis failures and degrades — code in §12); **not handled** for the other three components (`RateLimiter`, `DistributedLock`, `JobStatusCache` — no try/except anywhere around their Redis calls, confirmed by reading every call site).

**Deployment:** `redis:7-alpine` via Docker Compose, single node, no auth configured (§19). No Redis resource in the Helm chart — k3d pods reach the same Compose-run instance via `host.k3d.internal:6379`.

```
Application
     |
     ↓
Redis (single node, redis:7-alpine, :6379, no AUTH)
     |
     ├── Cache          — JobStatusCache
     ├── Rate Limiter 1  — RateLimiter (HTTP middleware, pipeline)
     ├── Rate Limiter 2  — LLMRateLimiter (Lua script)
     └── Distributed Lock — DistributedLock (SET NX EX)
```

---

## 2. Redis Architecture In This Project

```
main.py: rate_limit_middleware ──────────────┐
                                               |
3 agents + embeddings.py + llm_judge.py       |
   └─ get_limiter() → LLMRateLimiter.acquire()┤
                                               |
redpanda_queue.py: publish() / get_status()   |
   └─ JobStatusCache ──────────────────────────┤
                                               |
eval_worker_v2.py / load_worker.py            |
   └─ DistributedLock ─────────────────────────┤
                                               ↓
                                    redis_client.py: get_redis()
                                               |
                                               ↓
                                    redis.ConnectionPool
                                    (one, module-level, built at import)
                                               |
                                               ↓
                                    redis:7-alpine :6379
```

`LLMRateLimiter` does **not** build a second pool — `_default_redis()` (`llm_rate_limiter.py:295-300`) imports and calls `redis_client.get_redis()`, so it draws from the exact same pool as everything else. One pool, one process, all four consumers.

---

## 3. Configuration Chain

| Step | File : Line | Code |
|---|---|---|
| Env var declared (template) | `.env.example` | `REDIS_URL=redis://localhost:6379/0` |
| Loaded into settings | `apps/api/core/config.py:28` | `redis_url: str = "redis://localhost:6379/0"` (pydantic-settings field, `env_file=".env"`) |
| Overridden for containers | `docker-compose.yml` (eval/agent/gate_service `environment:` blocks) | `REDIS_URL: "redis://redis:6379/0"` |
| Overridden for k3d | `helm/redline/values.yaml` | `infra.redisUrl: "redis://host.k3d.internal:6379/0"` → `helm/redline/templates/base/configmap.yaml:9` → `redis-url: {{ .Values.infra.redisUrl | quote }}` |
| Consumed | `apps/api/core/redis_client.py:21-22` | `_settings = get_settings()` / `_pool = redis.ConnectionPool.from_url(_settings.redis_url, ...)` |

**No `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`/`REDIS_DB` anywhere in the repository** — grepped `.env.example`, `config.py`, `docker-compose.yml`, `values.yaml`. Only a single `REDIS_URL` connection string is used throughout. No password appears in any of these values — `redis://localhost:6379/0` and `redis://redis:6379/0` and `redis://host.k3d.internal:6379/0` all carry no credentials. Confirmed against `.env.example` directly — nothing to redact, there's no secret to begin with (see §19).

---

## 5. Important Code — Every Concept, Exact Location

### 5.1 Client Initialization + Connection Pooling

**File:** `apps/api/core/redis_client.py`
**Lines:** 21-26

```python
_settings = get_settings()
_pool = redis.ConnectionPool.from_url(_settings.redis_url, decode_responses=True)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)
```

**Runtime behavior:** `_pool` is built exactly once, when this module is first imported (Python module-level code runs once per process). Every subsequent call to `get_redis()` — from `RateLimiter.__init__`, `DistributedLock.__init__`, `JobStatusCache.__init__`, and `LLMRateLimiter._default_redis()` — constructs a new lightweight `redis.Redis` wrapper object but hands it the **same** `_pool`, so physical TCP connections are shared/reused across every class in this codebase, not opened per-instance. `decode_responses=True` means every value read back is `str`, not `bytes` — this is why `JobStatusCache.get()` (§5.5) can call `json.loads(raw)` directly with no `.decode("utf-8")` step.

**No explicit `max_connections` is set** — `redis.ConnectionPool.from_url(...)` is called with only the URL and `decode_responses`; `redis-py`'s pool defaults to unlimited connections unless capped. Not found: any connection-count ceiling anywhere in this file or its callers.

---

### 5.2 get / set / delete / expire — `JobStatusCache`

**File:** `apps/api/core/redis_client.py`
**Class:** `JobStatusCache`, lines 97-119

```python
class JobStatusCache:
    TTL_SECONDS = 30

    def __init__(self):
        self._r = get_redis()

    def get(self, eval_run_id: uuid.UUID) -> dict | None:
        raw = self._r.get(f"run_status:{eval_run_id}")
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, eval_run_id: uuid.UUID, status_data: dict) -> None:
        self._r.setex(f"run_status:{eval_run_id}", self.TTL_SECONDS, json.dumps(status_data))

    def invalidate(self, eval_run_id: uuid.UUID) -> None:
        self._r.delete(f"run_status:{eval_run_id}")
```

**Operations used:** `GET` (`.get`, line 110), `SETEX` (`.set`, line 116 — combines `SET` + `EXPIRE` into one command), `DEL` (`.invalidate`, line 118). `EXISTS` is **not used anywhere in this class** — the miss check is `raw is None` after a plain `GET`, not a separate `EXISTS` call.

**Serialization:** `json.dumps(status_data)` on write (line 116), `json.loads(raw)` on read (line 113) — plain Python `dict` ↔ JSON string ↔ Redis string value. No `pickle`, no `msgpack`, no Redis Hash (the whole dict is one JSON blob under one string key, not spread across hash fields).

**Runtime behavior:** a miss (`raw is None`) returns `None` from `.get()`, caller must handle the fallback itself (see §5.4 for where that happens) — this class does not fetch from Postgres on its own.

---

### 5.3 Pipeline (batched, non-transactional) — `RateLimiter`

**File:** `apps/api/core/redis_client.py`
**Class:** `RateLimiter`, lines 31-58

```python
def is_allowed(self, tenant_id: uuid.UUID) -> bool:
    key = f"rl:{tenant_id}"
    now = time.time()
    window_start = now - self._window

    pipe = self._r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, self._window + 1)
    _, current_count, _, _ = pipe.execute()

    return current_count < self._max
```

**Operations used:** `ZREMRANGEBYSCORE` (evict entries older than the window), `ZCARD` (count remaining), `ZADD` (record this request), `EXPIRE` (TTL). Batched via `.pipeline()` — four commands, one round trip, results unpacked in call order (`_, current_count, _, _`).

**This is a pipeline, not a Redis transaction (`MULTI`/`EXEC` is not called explicitly, and `redis-py`'s default `pipeline()` executes as a batch but is not guarded against interleaving from other clients the way a Lua script is).** Confirmed: no `.multi()` call, no `WATCH`, anywhere in this file. Contrast directly with §5.6, where the same category of problem (check-then-add) is solved with a Lua script instead — the codebase makes two different atomicity choices for two structurally similar limiters.

**Runtime behavior:** `current_count` reflects the cardinality **before** this call's own `ZADD` (line 54) — read the pipeline order: `ZCARD` runs before `ZADD` within the same batch. `ZADD` still executes even if the request will end up rejected by the Python-level `return current_count < self._max` check on line 58 — the timestamp is written to the sorted set regardless of the outcome.

---

### 5.4 Cache-Aside Read Path — `RedpandaJobQueue.get_status()`

**File:** `apps/api/core/redpanda_queue.py`
**Lines:** 156-165

```python
def get_status(self, job_id: uuid.UUID) -> JobStatus:
    """Cache-first read: Redis → Postgres fallback."""
    cached = self._cache.get(job_id)
    if cached is not None:
        return JobStatus(id=job_id, **cached)

    job = self._db.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    return JobStatus(id=job.id, status=job.status, result=job.result, error=job.error)
}
```
(closing brace above is illustrative of the block end, not literal Python — the actual file has no trailing brace)

**Runtime behavior on a cache hit:** `self._cache.get(job_id)` (calls §5.2's `.get()`) returns a dict → `JobStatus(id=job_id, **cached)` built directly from Redis, Postgres never touched.
**On a cache miss:** falls through to `self._db.get(Job, job_id)` — a Postgres read.
**Important:** this method does **not** call `self._cache.set(...)` after the Postgres fallback — a miss is not repopulated into Redis by the reader. Only writers (`publish()`, `update_status()`, below) ever populate this cache. This is the exact reason §7 classifies this as a hybrid pattern, not textbook cache-aside.

---

### 5.5 Write-Path Cache Population — `RedpandaJobQueue.publish()` and `RedpandaEvalWorker.update_status()`

**File:** `apps/api/core/redpanda_queue.py`

**`publish()` — line 152:**
```python
# Warm the cache so the first poll from the caller is instant.
self._cache.set(job.id, {"status": "pending", "result": None, "error": None})
```

**`update_status()` — lines 275-289:**
```python
def update_status(self, job_id, status, result=None, error=None, db=None):
    """Updates job status in both Postgres and the Redis cache."""
    status_data = {"status": status, "result": result, "error": error}
    self._cache.set(job_id, status_data)
    self._cache.invalidate(job_id)  # force next poll to re-read
    self._cache.set(job_id, status_data)

    if db is not None:
        job = db.get(Job, job_id)
        if job is not None:
            job.status = status
            job.result = result
            job.error = error
            job.updated_at = datetime.utcnow()
```

**Runtime behavior:** three Redis round trips (`SETEX`, `DEL`, `SETEX` again) with **identical `status_data` in both `.set()` calls** — the net state in Redis after this function returns is exactly what a single `.set()` call would have produced. The comment ("force next poll to re-read") describes what `.invalidate()` alone would do; the trailing `.set()` immediately undoes that. Read this exact block if a debugging question comes up — it's a real, pointable redundancy, not a hypothetical one.

---

### 5.6 Lua Script — Atomic Sliding Window + Daily Counter

**File:** `apps/api/core/llm_rate_limiter.py`
**Lines:** 73-98 (script text), 159 (registration), 185-195 (invocation)

**Registration** (constructor, line 159):
```python
self._script = self._redis.register_script(_ACQUIRE_LUA)
```

**Invocation** (`acquire()`, lines 185-195):
```python
status, detail = self._script(
    keys=[self.window_key, self.daily_key],
    args=[
        time.time(),
        self._window,
        self._rpm,
        self._daily_limit if self._daily_limit is not None else -1,
        _seconds_until_utc_midnight(),
        f"{time.time()}:{id(self)}",
    ],
)
```

**The script:**
```lua
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local rpm = tonumber(ARGV[3])
local daily_limit = tonumber(ARGV[4])
local daily_ttl = tonumber(ARGV[5])

local used_today = tonumber(redis.call('GET', KEYS[2]) or '0')
if daily_limit >= 0 and used_today >= daily_limit then
    return {-1, used_today}
end

redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])

if count >= rpm then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {1, tonumber(oldest[2])}
end

redis.call('ZADD', KEYS[1], now, ARGV[6])
redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000) + 1000)
local new_total = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], daily_ttl)
return {0, new_total}
```

**Runtime behavior:** `redis-py`'s `register_script()` returns a `Script` object; calling it (`self._script(keys=..., args=...)`) runs `EVALSHA` (falls back to `EVAL` automatically if the SHA isn't cached server-side yet). The entire check-daily → prune-window → check-window → add → increment-daily sequence executes as one atomic Redis operation — no other client's script invocation can interleave partway through. Three possible return tuples: `{0, new_total}` (acquired), `{-1, used_today}` (daily quota exhausted), `{1, oldest_score}` (per-minute window full, caller must wait until `oldest_score + window`).

**Where this is called from — every LLM-calling path in the repo:**
- `agents/rag_agent/agent.py:60,66` — `_limiter = get_limiter("standard")`, `_embedding_limiter = get_limiter("standard", for_embedding=True)`
- `agents/research_pipeline_agent/agent.py:49,54` — `get_limiter("high_reasoning")` (chat + embedding)
- `agents/stateful_support_agent/agent.py:47,52` — same pattern
- `apps/api/services/embeddings.py:33` — `get_limiter(EMBEDDING_PROFILE_NAME, for_embedding=True)`
- `apps/api/services/scorers/llm_judge.py:51` — `self._limiter = get_limiter("high_reasoning")`

Each of these calls `.acquire()` (which runs the script above) immediately before the actual provider API call.

---

### 5.7 SET NX EX — Distributed Lock

**File:** `apps/api/core/redis_client.py`
**Class:** `DistributedLock`, lines 70-92

```python
def acquire(self, job_id: uuid.UUID) -> bool:
    key = f"lock:job:{job_id}"
    return self._r.set(key, "1", nx=True, ex=self._ttl) is not None

def release(self, job_id: uuid.UUID) -> None:
    self._r.delete(f"lock:job:{job_id}")
```

**Call sites:**
- `apps/api/workers/eval_worker_v2.py:29` — `lock = DistributedLock(ttl_seconds=600)`; line 48 — `if not lock.acquire(job_id):`; line 74 — `lock.release(job_id)`
- `apps/api/workers/load_worker.py:33` — `lock = DistributedLock(ttl_seconds=1800)`; line 51 — `if not lock.acquire(job_id):`; line 74 — `lock.release(job_id)`

**Runtime behavior:** `SET key "1" NX EX ttl` is one atomic command — `nx=True` means "only set if the key doesn't already exist," `ex=self._ttl` sets the expiry in the same call. `redis-py` returns `None` if the `NX` condition failed (key already existed → lock held by someone else); `is not None` is `True` only when this call actually created the key. On the acquire-failure path in both workers, the Kafka offset is still committed (`worker.commit_offset()`) immediately after the failed acquire — read `eval_worker_v2.py` lines 46-51 and `load_worker.py` lines 49-53 together with this code to see the full redelivery-handling logic.

---

### 5.8 Health Check

**Not implemented as an application-level Redis health check.** `apps/api/main.py:22-26`'s `/health` endpoint only checks Postgres (`engine.connect()` + `SELECT 1`) — it never touches Redis. The only Redis health check in the repository is infrastructure-level: `docker-compose.yml`'s `redis` service `healthcheck: test: ["CMD", "redis-cli", "ping"]` — this gates whether **other Compose services** start (via `depends_on: redis: condition: service_healthy`), but the running FastAPI application itself never reports Redis health through its own `/health` endpoint.

**`LLMRateLimiter` does the closest thing to an app-level Redis health check at construction time** — `_default_redis()` (`llm_rate_limiter.py:295-300`) calls `client.ping()` immediately after getting a client, explicitly commented "fail fast at construction rather than on the first `acquire()`." This is a one-time startup check, not a recurring health probe.

---

## 6. Redis Data Flow

### 6.1 HTTP request through the rate-limit middleware

```
Incoming HTTP request
   ↓
apps/api/main.py:31  rate_limit_middleware(request, call_next)
   ↓
path in ("/health","/docs",...)?  → yes → call_next(request), Redis never touched
   ↓ no
lines 37-45: derive tenant_proxy_id from SHA256(bearer token)[:32]
   ↓
line 47: _rate_limiter.is_allowed(tenant_proxy_id)
   ↓
redis_client.py:51-56  pipeline: ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE → execute()
   ↓
current_count < 100?
   ├── NO  → main.py:48-52  429 JSONResponse, request never reaches a router
   └── YES → main.py:53  await call_next(request) → normal router/dependency chain runs
```

### 6.2 Eval-run creation and status polling

```
POST /eval-runs (router not shown here — see the CI/eval-runs router files)
   ↓
RedpandaJobQueue.publish()  redpanda_queue.py:109-154
   ↓
line 112-120: INSERT Job row (Postgres)
line 125-149: produce to Redpanda, flush(timeout=10)
line 152: self._cache.set(job.id, {"status":"pending",...})   ← Redis write
   ↓
returns job.id immediately
   ↓
Caller later calls: RedpandaJobQueue.get_status(job_id)   redpanda_queue.py:156-165
   ↓
self._cache.get(job_id)   ← Redis read
   ├── HIT  → return JobStatus built from cached dict, Postgres never touched
   └── MISS → self._db.get(Job, job_id)   ← Postgres read, NOT written back to cache
```

### 6.3 Worker claiming and processing a job (dedup + status)

```
eval_worker_v2.py: run_worker_loop()
   ↓
worker.consume_one(timeout_seconds=2.0)   — Kafka poll, no Redis yet
   ↓
message received
   ↓
lock.acquire(job_id)   redis_client.py:86-89  → SET NX EX
   ├── False (already locked / redelivery) → worker.commit_offset(); continue loop
   └── True → proceed
        ↓
        worker.update_status(job_id, "in_progress", db=db)   redpanda_queue.py:275-289
           → self._cache.set() / .invalidate() / .set()   ← 3 Redis round trips, §5.5
        ↓
        eval_engine.run_eval(eval_run_id)   — no Redis here (Postgres + ClickHouse only)
        ↓
        worker.update_status(job_id, "completed"/"failed", ...)   ← same 3-call pattern again
        ↓
        lock.release(job_id)   redis_client.py:91-92  → DEL
        ↓
        worker.commit_offset()
```

### 6.4 An LLM call from any agent/scorer

```
agents/rag_agent/agent.py (or research_pipeline_agent / stateful_support_agent /
embeddings.py / llm_judge.py)
   ↓
_limiter.acquire()   llm_rate_limiter.py:174-215
   ↓
self._script(keys=[window_key, daily_key], args=[...])   ← Lua script, one Redis round trip
   ↓
status == 0  → return immediately, proceed to the real Gemini API call
status == -1 → raise DailyQuotaExceeded, caller does NOT call the LLM
status == 1  → time.sleep(wait), loop back to the script call again
```

---

## 7. Cache Behavior — `JobStatusCache`

**What is cached:** an `EvalRun`'s current status snapshot — `{"status": str, "result": dict|None, "error": str|None}`.

**Cache key:** `f"run_status:{eval_run_id}"` — `redis_client.py:110,116,118`. Constructed by f-string interpolation of the `uuid.UUID`, no hashing/namespacing beyond the literal `run_status:` prefix.

**Value + serialization:** the dict is `json.dumps()`'d before `SETEX` and `json.loads()`'d after `GET` (`redis_client.py:113,116`) — plain JSON string, no Hash, no binary format.

**TTL:** `TTL_SECONDS = 30` (`redis_client.py:104`), applied via `SETEX` in `.set()`.

**Invalidation:** two mechanisms — (1) explicit: `.invalidate()` called from `update_status()` (`redpanda_queue.py:279`, though immediately followed by a re-`.set()` that undoes it — §5.5); (2) implicit: the 30s TTL expiring on its own.

**Cache hit behavior:** `get_status()` (§5.4) returns a `JobStatus` built entirely from the cached dict — Postgres is not queried.

**Cache miss behavior:** falls through to `self._db.get(Job, job_id)` — Postgres queried directly. **The result of this Postgres read is not written back into the cache** (confirmed — no `.set()` call anywhere in `get_status()`'s miss branch). This means: after the 30s TTL naturally expires, the *next* poller pays a Postgres read and gets nothing cached; only the *next write* (another `update_status()` call, if one happens) repopulates Redis. If no further status change occurs, every subsequent poll after TTL expiry hits Postgres, forever, for that job.

**Stale data:** bounded by the 30s TTL as a hard ceiling — a cached status can be at most 30 seconds behind Postgres. In practice it's usually far fresher, because `update_status()` invalidates+re-sets on every real status transition (in-progress, completed, failed) — the TTL is a safety net for the case where a worker crashes between transitions, not the primary freshness mechanism.

**Redis unavailable:** `self._cache.get(job_id)` (in `get_status()`, §5.4) has no try/except around it — if Redis is down, this raises rather than falling through to the Postgres branch that visually looks like a "fallback." The fallback-to-Postgres code path only executes on a cache **miss** (`cached is None`), never on a cache **error**.

**Classification, from what the code actually does — not a forced textbook label:** the **write side** is closer to write-through (every writer proactively pushes the new status into Redis at the same time it commits to Postgres — `publish()` line 152, `update_status()` lines 278-281). The **read side** is cache-aside-shaped (check cache first, fall back to source-of-truth on miss) but is **incomplete cache-aside** — a true cache-aside read would repopulate the cache on a miss, and this one doesn't. So: **write-through on writes, partial/non-repopulating cache-aside on reads.** Neither label alone is fully accurate; say both halves if asked.

---

## 8. TTL / Expiration

| Key | TTL | Set at | Why this duration |
|---|---|---|---|
| `run_status:{id}` | 30s (`JobStatusCache.TTL_SECONDS`, `redis_client.py:104`) | Every `.set()` call, via `SETEX` | Safety net bound on staleness if a worker crashes between `update_status()` calls — not the primary invalidation mechanism (explicit `.invalidate()` is) |
| `rl:{tenant_id}` | `window_seconds + 1` = 61s (`redis_client.py:55`) | Every `.is_allowed()` call, via `EXPIRE` | Slightly longer than the 60s window so the key survives exactly one window's worth of inactivity before Redis reclaims it — not load-bearing for correctness (the sorted-set pruning via `ZREMRANGEBYSCORE` does that), purely memory hygiene for idle tenants |
| `lock:job:{id}` | 600s (`eval_worker_v2.py:29`) or 1800s (`load_worker.py:33`) | `DistributedLock.acquire()`, via `SET ... EX` | Longer than the expected max job duration — a crashed worker's lock self-expires instead of permanently orphaning the job; 1800s for load tests because those "can run for minutes" (inline comment, `load_worker.py:33`) vs. 600s for regular evals |
| `ratelimit:llm:{provider}:{model}` | `math.ceil(window * 1000) + 1000` ms (Lua script, `llm_rate_limiter.py:94`) | Every successful `acquire()`, via `PEXPIRE` inside the script | Millisecond precision, one window plus a 1-second cushion — set inside the atomic script itself, not as a separate call |
| `quota:llm:{provider}:{model}:{date}` | rest of the UTC day + 3600s (`_seconds_until_utc_midnight()`, `llm_rate_limiter.py:110-120`) | Every successful `acquire()`, via `EXPIRE` inside the script | The key already encodes the date (`self.daily_key` includes `%Y-%m-%d`, line 169), so the counter "resets" by a new key existing at midnight, not by this TTL — the TTL exists purely to stop old-date keys from accumulating forever, per the docstring at lines 111-116 |

**What happens after expiration:** Redis deletes the key. For `run_status:*` and `lock:job:*`, this means the next read/acquire behaves as if nothing had ever been cached/locked (a cache miss, or a lock free-for-the-taking). For `rl:*` and `ratelimit:llm:*`, an expired-and-gone key means the next request starts a fresh sorted set from zero. For `quota:llm:*:{date}`, expiry only ever removes a *stale* (past) date's key — the *current* date's key is always freshly created by `INCR` on first use each day (`INCR` on a nonexistent key initializes it to 1), so expiry never resets the day currently in progress.

---

## 9. Redis Data Structures Actually Used

### Strings
**Where:** `lock:job:{id}` (`SET NX EX`, `redis_client.py:89`), `run_status:{id}` (`SETEX` with JSON payload, `redis_client.py:116`), `quota:llm:{provider}:{model}:{date}` (`GET`/`INCR` counter, Lua script lines 80,95).
**Example key:** `lock:job:3f9a2c11-...`
**Example value:** `"1"` (the lock) or `'{"status": "completed", "result": null, "error": null}'` (the cache) or `"14"` (the daily counter, stored as a string that `INCR` treats numerically).
**Why appropriate:** a lock only needs existence + TTL, not a value with structure; the daily counter is a single monotonically-incrementing integer per key, which is exactly what Redis `INCR` on a String is for; the job-status cache is one opaque JSON blob per job, and nothing in this codebase ever needs to read/write a single field of it independently — so a String holding the whole serialized dict, not a Hash with per-field access, is the right fit.

### Sorted Sets
**Where:** `rl:{tenant_id}` (`redis_client.py:52-54`), `ratelimit:llm:{provider}:{model}` (Lua script lines 85-93).
**Example key:** `ratelimit:llm:google:gemini-2.5-flash`
**Example value:** members are `"{timestamp}:{id(self)}"` strings (Lua script ARGV[6], `llm_rate_limiter.py:193`) or `str(now)` (`redis_client.py:54`), each scored by the timestamp itself.
**Why appropriate:** both are sliding-window rate limiters — the score-as-timestamp trick lets `ZREMRANGEBYSCORE` prune everything before the window start in one call, and `ZCARD` gives an O(1) count of what remains. This is the standard Redis sliding-window pattern; a plain counter with a fixed-TTL reset (token-bucket-by-TTL) would be simpler but less precise at window boundaries — the `RateLimiter` class docstring (`redis_client.py:36-37`) states this tradeoff explicitly: "more precise than a fixed token bucket at the cost of slightly more memory."

**Not found in repository — do not study these for this project:** Hashes, Lists, plain Sets (`SADD`/`SMEMBERS`), Streams (`XADD`/`XREAD`), Bitmaps, HyperLogLog, Geo commands, pub/sub (`PUBLISH`/`SUBSCRIBE`). None appear anywhere in `redis_client.py`, `llm_rate_limiter.py`, or any call site.

---

## 10. Async Redis

**Not found in repository.** `apps/api/requirements.txt:32` and `pyproject.toml:63` both pin `redis==5.0.8` and import it as plain `import redis` (`redis_client.py:17`, `llm_rate_limiter.py:58`) — never `redis.asyncio`, never `aioredis`. Grepped for both across every `.py` file in the repo: zero matches.

**The one place this matters concretely:** `apps/api/main.py:30-31` declares `rate_limit_middleware` as `async def`, and FastAPI runs it directly on the event loop. Inside it, `_rate_limiter.is_allowed(tenant_proxy_id)` (line 47) is a **synchronous, blocking** call — `redis_client.py`'s `pipe.execute()` (line 56) is a blocking socket round trip via the sync `redis-py` client, not wrapped in `run_in_threadpool`/`asyncio.to_thread`/`await`. This means every single HTTP request through this middleware blocks the FastAPI event loop for the duration of that Redis round trip. See §18 for this flagged as a real, findable issue rather than a hypothetical.

**Why sync Redis was chosen here at all (inferred from the rest of the codebase, not stated explicitly for Redis specifically):** the eval engine, gate engine, and every worker are deliberately synchronous per architecture Rule 1 (no `asyncio` near `eval_engine.py`/`gate_engine.py`/workers, because mixing it with synchronous SQLAlchemy Sessions and `confluent-kafka`'s synchronous C-binding consumer is a documented concurrency trap — see `llm_rate_limiter.py`'s own docstring reasoning for why `ThreadPoolExecutor`, not asyncio, was chosen for load testing). A synchronous Redis client is consistent with that project-wide constraint everywhere **except** the one `async def` middleware in `main.py`, where it's a genuine mismatch.

---

## 11. Connection Pooling

**File:** `apps/api/core/redis_client.py:22`
```python
_pool = redis.ConnectionPool.from_url(_settings.redis_url, decode_responses=True)
```

**Lifecycle:** built once at module import (first time anything does `from apps.api.core.redis_client import ...`), lives for the lifetime of the process, never explicitly closed/recreated anywhere in the codebase (no `_pool.disconnect()` call found).

**Reused by:** every class that calls `get_redis()` — `RateLimiter`, `DistributedLock`, `JobStatusCache` (all three construct their own `Redis` wrapper in `__init__`, all three share this one pool), and `LLMRateLimiter` via `_default_redis()` (`llm_rate_limiter.py:295-300`), **unless** a test or caller explicitly injects a different client (`LLMRateLimiter(..., redis_client=some_other_client)`, used by the unit tests' `_DeadRedis` fake).

**Connection limit:** not configured — `from_url()` is called with no `max_connections` argument, so `redis-py`'s default (effectively unbounded, `2**31` in current `redis-py` versions) applies. Not found: any explicit cap anywhere in this repo.

**Contrast with the DB pool (for interview framing, not because this file implements it):** SQLAlchemy's `engine` (`apps/api/core/db.py`, referenced but not detailed here) is a separately-configured pool with its own settings — the two pools (Postgres via SQLAlchemy, Redis via `redis-py`) are independent, sized and configured independently, and neither references the other.

---

## 12. Error Handling

| Redis call site | Exception handling present? | Behavior on Redis failure |
|---|---|---|
| `RateLimiter.is_allowed()` / `.remaining()` (`redis_client.py:45-65`) | **No** — no try/except in the class or in `main.py`'s middleware around the call | Unhandled exception propagates out of `rate_limit_middleware`, out of FastAPI's middleware stack |
| `DistributedLock.acquire()` / `.release()` (`redis_client.py:86-92`) | **No** | Unhandled exception propagates out of the worker's `run_worker_loop()` at whatever point it's called |
| `JobStatusCache.get()` / `.set()` / `.invalidate()` (`redis_client.py:109-119`) | **No** | Unhandled exception propagates — including from `get_status()`'s "cache-first" read (§5.4), meaning a Redis outage does **not** actually reach the Postgres fallback branch; it raises before getting there |
| `LLMRateLimiter.__init__` (`llm_rate_limiter.py:157-162`) | **Yes** | `try: self._redis = redis_client or _default_redis(); self._script = self._redis.register_script(...) except Exception as exc: self._redis = None; self._enter_degraded(exc)` — construction never raises even if Redis is completely unreachable |
| `LLMRateLimiter.acquire()` (`llm_rate_limiter.py:183-198`) | **Yes** | `try: status, detail = self._script(...) except Exception as exc: self._enter_degraded(exc); return slept + self._acquire_local()` — falls to the in-process fallback window (§13 covers exactly what that means) |
| `LLMRateLimiter.current_usage` / `.used_today` (`llm_rate_limiter.py:217-242`) | **Yes** | Same `try/except Exception as exc: self._enter_degraded(exc)` pattern, returns `0` on failure |

**Retries:** not found as a generic pattern for connection failures (no `retry.Retry`, no `backoff` decorator, no manual retry loop around a Redis call anywhere). The one thing that superficially looks like a retry is `LLMRateLimiter.acquire()`'s `while True:` loop (lines 183-215) — but that loop retries the **Lua script call** when the *window is full* (a legitimate business-logic wait, not a connection-error retry); a genuine Redis connection failure inside that loop is caught by the `except Exception` and routed to `_enter_degraded()`, exiting the loop via the fallback return, not retried.

**Timeouts:** not found as an explicit `socket_timeout`/`socket_connect_timeout` argument anywhere `redis.ConnectionPool.from_url()` or `redis.Redis(...)` is constructed — `redis_client.py:22` passes only `decode_responses=True`. Whatever `redis-py`'s library defaults are apply; the project does not override them.

**Summary — only one of four Redis consumers has any error handling at all**, and it's the one explicitly designed to (`LLMRateLimiter`). Do not claim the whole system gracefully degrades — the code does not support that claim for `RateLimiter`, `DistributedLock`, or `JobStatusCache`.

---

## 13. Redis + Database

```
PostgreSQL (source of truth: Job rows, EvalRun rows, everything durable)
      ↑
      |  db.get(Job, job_id) / db.get(EvalRun, ...) — always available as fallback
      |
Application (redpanda_queue.py: RedpandaJobQueue, RedpandaEvalWorker)
      ↓
      |  self._cache.set(...) on every write (publish, update_status)
      |  self._cache.get(...) checked first on every read (get_status)
      ↓
Redis (JobStatusCache — 30s TTL, explicit invalidate on write)
```

**Source of truth:** Postgres, unambiguously — every `Job`/`EvalRun` row is written there (`redpanda_queue.py:112-120` inserts the `Job` row; `update_status()` lines 283-288 write `job.status`/`job.result`/`job.error` back to the ORM object, which the caller is expected to `db.commit()`). Redis holds a copy with a bounded lifetime, never the only copy.

**Read path:** `get_status()` — Redis first, Postgres on miss (§5.4).

**Write path:** Postgres write and Redis cache write happen from the **same function calls** (`publish()`, `update_status()`) but are **not** a single atomic transaction across the two systems — the Redis `.set()` in `publish()` (line 152) happens after the Postgres `INSERT` (lines 112-120) and after the Redpanda `flush()` (lines 147-149), as a separate, independent operation. If the process crashed between the Postgres commit and the Redis `.set()`, Postgres would have the job but Redis wouldn't yet — a caller polling in that exact window would get a cache miss and correctly fall through to Postgres, so this particular ordering is safe by virtue of the fallback existing, not because the two writes are transactional.

**Consistency implications / possible staleness:** bounded by the 30s TTL as a hard ceiling (§7). Within that bound, `update_status()`'s explicit invalidate-on-write keeps the cache fresher than the TTL alone would guarantee, for the specific job whose status just changed. A job that never gets a Postgres-only lock-holder update (e.g., §5.5's redundant write pattern; or a crash between Postgres write and Redis write) could show slightly stale status in Redis for up to 30 seconds.

---

## 14. Redis + Docker

**File:** `docker-compose.yml`, `redis` service block:
```yaml
redis:
  image: redis:7-alpine
  container_name: redline_redis
  restart: unless-stopped
  ports:
    - "6379:6379"
  volumes:
    - redline_redis_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 5s
    retries: 5
```

No `environment:` block on this service — no `REDIS_PASSWORD`/`requirepass` argument set anywhere (see §19).

**Application connection string inside containers:** `docker-compose.yml`'s `eval_service`/`agent_service`/`gate_service` blocks set `REDIS_URL: "redis://redis:6379/0"` — the hostname is `redis`, the **Compose service name**, not `localhost`. This is required because each service runs in its own container on Compose's default bridge network; `localhost` inside the `eval_service` container refers to that container itself, which has no Redis process running in it — only the separate `redis` container does. Compose's embedded DNS resolves the literal string `redis` to that container's address on the shared network. Confirmed this pattern is used consistently — grepped every `REDIS_URL` value in `docker-compose.yml` and found no `localhost` usage for inter-container communication.

**k3d/Helm path:** `helm/redline/values.yaml`'s `infra.redisUrl: "redis://host.k3d.internal:6379/0"` — pods inside the k3d cluster use `host.k3d.internal`, a k3d-provided DNS name that resolves to the Docker host machine, because the Redis container itself runs via Compose **outside** the k3d cluster, not as a Kubernetes resource. No Redis Deployment/StatefulSet/Service template exists anywhere under `helm/redline/templates/` — confirmed by listing that directory's contents; there is no `redis` subdirectory alongside `eval-service`, `agent-service`, `gate-service`, `gateway`, `worker`, `load-worker`.

---

## 15. Redis + Background Jobs / Queues

**Not implemented in this repository** — in the sense of Redis-as-broker. No Celery, no RQ, no Redis Streams, no `PUBLISH`/`SUBSCRIBE`. Grepped for `celery`, `from rq`, `rq\.` across every `.py` file: zero matches.

**The actual background-job queue is Postgres + Redpanda (Kafka), via the `JobQueue` Protocol** (`apps/api/core/jobqueue.py`, two implementations: `PostgresJobQueue` and `RedpandaJobQueue`) — this is entirely separate from Redis. Redis's only role in the background-job architecture is narrower and supporting, not the queue itself:
- **Deduplication:** `DistributedLock` prevents two workers from both processing the same Kafka-redelivered message (§5.7).
- **Status caching:** `JobStatusCache` speeds up status polling so it doesn't always hit Postgres (§5.2, §5.4).

If asked "is this a Redis queue," the accurate answer is **no** — Redis touches the job lifecycle at exactly two points (lock, cache), but the actual message transport and durable job record are Redpanda and Postgres respectively.

---

## 16. Redis Testing

### Unit — `apps/api/tests/unit/test_llm_rate_limiter.py` (`pytestmark = pytest.mark.unit`)

**No real Redis.** A hand-written fake forces every Redis call to fail:
```python
class _DeadRedis:
    """A Redis handle where everything fails, to force the degraded path."""
    def register_script(self, _script):
        raise ConnectionError("redis is down")
    def __getattr__(self, _name):
        def _boom(*args, **kwargs):
            raise ConnectionError("redis is down")
        return _boom
```
Injected via constructor dependency injection: `LLMRateLimiter(rpm=rpm, redis_client=_DeadRedis(), **kwargs)`. Every test in this file exercises only the degraded/fallback code path (§12's `LLMRateLimiter` row) — key naming, TTL arithmetic, and the local-`deque`-fallback behavior, deliberately never touching a real Redis server. Representative test: `test_unreachable_redis_degrades_instead_of_raising()` (line ~97) asserts `limiter.is_degraded is True` and `limiter.acquire() == 0.0` rather than raising.

### Integration — `apps/api/tests/integration/test_llm_rate_limiter_redis.py` (`pytestmark = pytest.mark.integration`)

**Real Redis required**, skipped otherwise:
```python
@pytest.fixture
def redis_client():
    try:
        from apps.api.core.redis_client import get_redis
        client = get_redis()
        client.ping()
    except Exception as exc:
        pytest.skip(f"redis unavailable: {exc}")
    return client
```
Cleanup fixture scopes deletions to the specific test's keys only:
```python
@pytest.fixture(autouse=True)
def _cleanup(redis_client, model_id):
    yield
    for key in redis_client.scan_iter(match=f"*:llm:test:{model_id}*"):
        redis_client.delete(key)
```
Tests present in this file (verified by reading): acquiring below the limit doesn't sleep; `redis_client.exists(limiter.window_key) == 1` and `zcard(...) == 1` after one `acquire()` — asserting the actual sorted-set key exists in real Redis; the daily counter increments and its real TTL is asserted (`ttl <= 86_400 + 3600 + 5`); and the central claim of the whole class — **two separate `LLMRateLimiter` instances constructed independently share one Redis-backed budget** (`test_two_limiters_share_one_window`) — which is exactly the property that was false under the old in-process implementation this class replaced.

**Not found:** any test file exercising `RateLimiter`, `DistributedLock`, or `JobStatusCache` directly — no `test_redis_client.py` or equivalent exists in `apps/api/tests/unit/` or `apps/api/tests/integration/`. These three classes have no dedicated test coverage found in this repository; only `LLMRateLimiter` does.

### `test_packaging.py` — not a Redis behavior test
`apps/api/tests/unit/test_packaging.py` lists `"redis"` inside a `SERVER_ONLY` set (line ~37) that a packaging-boundary assertion checks against — confirms `redis` is never accidentally declared as a CLI dependency (architecture Rule 7 adjacent). It does not call any Redis command.

### CI wiring
`.github/workflows/ci.yml:80` sets `REDIS_URL: redis://127.0.0.1:6379/0` as a job env var; line 111 runs `docker compose up -d postgres redis redpanda clickhouse` before `pytest -m integration` — this is what makes `test_llm_rate_limiter_redis.py` actually run for real in CI instead of always hitting the `pytest.skip(...)` branch.

---

## 17. Configuration & Environment Variables

| Variable | Defined | Loaded | Consumed | Sensitive? |
|---|---|---|---|---|
| `REDIS_URL` | `.env.example` (template value `redis://localhost:6379/0`) | `apps/api/core/config.py:28`, pydantic-settings `Settings.redis_url`, `env_file=".env"` | `apps/api/core/redis_client.py:21-22` (`ConnectionPool.from_url`) | Not sensitive as configured — no credentials embedded in any value found across `.env.example`, `docker-compose.yml`, or `values.yaml` |

**`REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB`: Not found in repository.** Only the single combined `REDIS_URL` connection string is used — there is no separate-field configuration style for Redis anywhere in this codebase (contrast with ClickHouse, which does use separate `CLICKHOUSE_HOST`/`CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` fields per `.env.example` — Redis configuration is deliberately simpler/flatter).

**Dev vs. "production" behavior:** the repository has no separate production Redis configuration — `docker-compose.yml`'s value and `helm/redline/values.yaml`'s value are the only two environments represented, and both point at the same unauthenticated single-node Redis (§19). Not found: any `.env.production` or equivalent with a different `REDIS_URL` shape (e.g., a managed Redis provider's connection string with `rediss://` TLS scheme or embedded credentials).

---

## 18. Performance Considerations

### ACTUAL ISSUE FOUND

1. **Blocking synchronous Redis call inside an `async def` FastAPI middleware.** `apps/api/main.py:31,47` — `rate_limit_middleware` is `async def`, but `_rate_limiter.is_allowed(...)` (which runs a blocking `pipe.execute()`, `redis_client.py:56`) is called directly, with no `await`, no `run_in_threadpool`, no `asyncio.to_thread`. Every request through this middleware blocks the single event-loop thread for the duration of that Redis round trip. Under concurrent load, this serializes request handling around Redis latency in a way a properly-async or threadpool-offloaded call wouldn't. See §10 for the full framing.

2. **Redundant Redis round trips in `update_status()`.** `apps/api/core/redpanda_queue.py:278-281` — `set()` → `invalidate()` (`DEL`) → `set()` again with identical data. Three network round trips producing the same end state one `SETEX` call would. Called twice per job (once entering `in_progress`, once at completion/failure) — six extra round trips per job's lifecycle that do nothing.

3. **`RateLimiter.is_allowed()`'s pipeline is not fully atomic under concurrent requests from the same tenant.** `redis_client.py:51-56` — a plain `pipeline()`, not a Lua script, not `MULTI`/`WATCH`/`EXEC`. Two concurrent requests can both compute `current_count` before either's `ZADD` lands, permitting a narrow over-admission right at the limit boundary. Contrast directly with `LLMRateLimiter`, which solves the structurally identical problem with a Lua script specifically because this exact race was unacceptable there (§5.6).

### POTENTIAL IMPROVEMENT (not confirmed as causing an actual problem in this codebase)

4. **No `max_connections` set on the shared pool** (`redis_client.py:22`) — relying on `redis-py`'s default. Not confirmed as a bottleneck (no evidence of connection exhaustion anywhere in the repo — no error logs, no incident comments about this, unlike the well-documented `LLMRateLimiter` incident), just an unbounded default worth naming if asked "would you change anything here."

5. **`JobStatusCache`'s read path doesn't repopulate on a Postgres-fallback miss** (§5.4, §7) — every poll after a 30s-TTL expiry with no intervening status change pays a full Postgres read with no chance of a future cache hit until the next real write. Not confirmed as measured-slow anywhere in the repo; a plausible improvement (`get_status()` could `self._cache.set(job_id, ...)` on its own fallback branch) rather than a documented problem.

**Not found:** N+1 Redis call patterns (each Redis-touching function issues a bounded, small number of calls per invocation — no loop found that calls Redis once per row of a larger collection), oversized values (the largest cached value is a small status JSON dict, not a large blob), or missing TTL on any key that should have one (every key in §8's table has a TTL — nothing was found stored in Redis without an expiry).

---

## 19. Security

**Authentication: none configured.** `docker-compose.yml`'s `redis` service has no `environment:` block, no `command: redis-server --requirepass ...`, nothing — confirmed by reading the full service definition. `REDIS_URL` values throughout the repo (`.env.example`, `docker-compose.yml`, `helm/redline/values.yaml`) never include a password segment (`redis://user:password@host:port/db` — none of the three actual URLs found in this repo use that form; all are `redis://host:port/db` with no credential component). This means: **any client that can reach port 6379 can issue any Redis command, with no authentication check at all.**

**TLS: not found.** No `rediss://` scheme anywhere, no TLS-related configuration for the Redis connection in `redis_client.py` or `llm_rate_limiter.py`.

**Network exposure:** `docker-compose.yml` publishes `"6379:6379"` — bound to all host interfaces by default (no `127.0.0.1:6379:6379` restriction found), meaning Redis is reachable from outside the Docker host's own network interface if that host is itself reachable, not just from other containers on the Compose network.

**Why this is fine for this repo as it stands, and why it would not be fine elsewhere:** every environment this repository actually targets is local development or CI (`docker-compose.yml` run on a developer's machine or a GitHub Actions runner) — both are already trust boundaries where an attacker reaching port 6379 implies a much larger compromise has already happened. **If this exact configuration were deployed to a real internet-facing host**, no-auth-no-TLS Redis on an exposed port would be a serious, immediately exploitable gap (unauthenticated Redis instances are a well-known real-world attack vector for exactly this reason). The repository shows no evidence of a production deployment target that would actually expose this (per the separate Docker analysis, the CI/CD `deploy` job is currently inert, no live cluster provisioned) — so as of right now, this is a **latent** gap, not an active one, but it is a real gap in the configuration as written, not a hypothetical.

**Secrets in Redis values:** not found — every value stored in Redis (lock markers, JSON status dicts, sorted-set timestamps, integer counters) is operational/ephemeral data, never a credential, token, or password. No JWT, no API key, no `DATABASE_URL` fragment, ever gets written into Redis anywhere in this codebase.

---

## 20. Interview Questions From This Project

1. Your `RateLimiter` uses a pipeline; your `LLMRateLimiter` uses a Lua script. Both solve a sliding-window rate limit — why the different approach? *(`redis_client.py:51-56` vs. `llm_rate_limiter.py:73-98` — the Lua script closes a real check-then-add race that the pipeline doesn't; the stakes differ, see §5.6.)*
2. Walk me through what happens, in Redis terms, from `LLMRateLimiter.acquire()` being called to the actual Gemini API call happening. *(§6.4, cite `llm_rate_limiter.py:174-215`.)*
3. What's stored under `run_status:{eval_run_id}`, and what invalidates it? *(§7 — `JobStatusCache`, TTL + explicit invalidate in `update_status()`, though note the redundancy in §5.5.)*
4. Is your job-status cache read-through, cache-aside, or write-through? *(§7's answer: write-through on the write side, incomplete/non-repopulating cache-aside on the read side — justify from `get_status()`'s code directly, not from memory.)*
5. What Redis data structure backs your rate limiters, and why that one? *(§9 — Sorted Sets, score-as-timestamp, cite the `RateLimiter` docstring's own stated tradeoff vs. a token bucket.)*
6. How does your FastAPI app connect to Redis — is the client async? *(§10 — no, `redis-py` sync client throughout; and be ready for the follow-up below.)*
7. Follow-up: if it's sync, and one of your middleware functions is `async def`, is there a problem? *(Yes — §10/§18 point 1: `main.py`'s rate-limit middleware blocks the event loop on every request. This is a real, findable issue in the current code, not a trick question with no answer.)*
8. How does your connection pool work? *(§11 — one module-level `ConnectionPool` built at import, shared by every consumer including `LLMRateLimiter`, no explicit `max_connections` cap.)*
9. What happens if Redis goes down right now? *(§12 — depends which consumer: `LLMRateLimiter` degrades gracefully with a logged fallback; `RateLimiter`, `DistributedLock`, and `JobStatusCache` have no exception handling and would raise. Name this inconsistency directly.)*
10. Is Redis your source of truth for job status? *(§13 — no, Postgres is; Redis is a bounded-TTL cache populated by writers, not written back to by the reader on a miss.)*
11. How do you prevent two Kafka consumers from double-processing the same job? *(§5.7/§6.3 — `DistributedLock.acquire()` via `SET NX EX`; both the win and lose paths still commit the Kafka offset.)*
12. Is your distributed lock Redlock? *(No — a single-node `SET NX EX`; the class's own docstring says to switch to `redlock-py` for a Redis cluster. §5.7.)*
13. Why does the daily LLM quota key include the date in the key name instead of just using a longer TTL? *(§8 — `self.daily_key` embeds `%Y-%m-%d`; the counter "resets" by a new key coming into existence at midnight, and the TTL only exists to clean up old dates, not to define the reset boundary — `llm_rate_limiter.py:166-170`, docstring lines 111-116.)*
14. How is Redis secured in this project? *(§19 — it isn't: no `requirepass`, no TLS, port published to all host interfaces. Say this plainly if asked; then state why it's currently latent, not active, given the deployment targets that actually exist.)*
15. Show me a place in your Redis code you'd change if you were doing a cleanup pass. *(§5.5/§18 point 2 — the redundant `set → invalidate → set` in `update_status()`; or §7/§18 point 5 — `get_status()`'s non-repopulating cache miss.)*

---

## 21. Interview-Ready Explanation (60-90 seconds)

"Redis in this project isn't the source of truth for anything — Postgres and Kafka own that. It's specifically there to coordinate across multiple processes, because the eval workers autoscale based on Kafka consumer lag, so at any point there can be several worker pods running at once. There are really three separate uses. First, a per-tenant HTTP rate limiter in the FastAPI middleware — that's a sorted set per tenant, timestamps as both the member and the score, so I can prune anything outside the window with one command and count what's left with another, all batched into one pipeline call. Second, and the one I'm most confident explaining in depth, is the LLM rate limiter — every agent and every LLM-calling scorer goes through it before hitting the actual provider API. That one had a real bug behind it: the original version kept its rate-limit window in an in-process deque, which was fine when there was exactly one worker, but once autoscaling kicked in, every pod independently enforced its own limit against one shared provider quota — so N pods effectively multiplied the real limit by N. The fix moves the state into Redis and does the whole check-then-increment as a single Lua script, so it's genuinely atomic across processes, not just batched. It also tracks a separate daily quota counter in the same script call, keyed by date, because the thing that actually broke in practice wasn't the per-minute limit, it was burning through a daily free-tier quota. And if Redis itself goes down, that limiter deliberately falls back to the old in-process window rather than blocking every LLM call — it logs a warning and keeps going, because losing precise coordination is a smaller problem than a total outage. Third, a distributed lock — just a SET with NX and an expiry — that stops two worker pods from both processing the same Kafka message when at-least-once delivery redelivers something. If Redis were unavailable there, honestly, that path isn't protected the same way the LLM limiter is — it would just raise, which is something I'd want to fix."

---

## 22. Redis Study Map

| Redis Concept | Used? | File | Function/Class | Important Code | Importance |
|---|---|---|---|---|---|
| Client init / connection pool | Yes | `redis_client.py:21-26` | module-level `_pool`, `get_redis()` | `ConnectionPool.from_url(...)` | 🔥 |
| `GET`/`SETEX`/`DEL` | Yes | `redis_client.py:97-119` | `JobStatusCache` | §5.2 | 🔥 |
| Pipeline (batched, non-atomic) | Yes | `redis_client.py:31-58` | `RateLimiter.is_allowed()` | §5.3 | 🔥 |
| Lua script (atomic) | Yes | `llm_rate_limiter.py:73-98,159,185-195` | `LLMRateLimiter` | §5.6 | 🔥 |
| `SET NX EX` (lock) | Yes | `redis_client.py:70-92` | `DistributedLock` | §5.7 | 🔥 |
| Sorted Sets | Yes | `redis_client.py:52-54`; Lua script lines 85-93 | `RateLimiter`, `LLMRateLimiter` | §9 | 🔥 |
| Strings (as counter, `INCR`) | Yes | Lua script line 95 | `LLMRateLimiter` (daily quota) | §9 | ⭐⭐ |
| TTL / expiration | Yes | Every class — see §8's table | all four classes | §8 | 🔥 |
| Cache-aside (partial) | Yes | `redpanda_queue.py:156-165` | `RedpandaJobQueue.get_status()` | §5.4, §7 | ⭐⭐ |
| Write-through-shaped writes | Yes | `redpanda_queue.py:109-154,275-289` | `publish()`, `update_status()` | §5.5, §7 | ⭐⭐ |
| JSON serialization | Yes | `redis_client.py:113,116` | `JobStatusCache` | §5.2 | ⭐⭐ |
| Distributed coordination (multi-worker) | Yes | `llm_rate_limiter.py` whole file; `eval_worker_v2.py`, `load_worker.py` | `LLMRateLimiter`, `DistributedLock` | §5.6, §5.7 | 🔥 |
| Error handling / graceful degradation | Partially | `llm_rate_limiter.py:157-162,183-198,217-242` | `LLMRateLimiter` only | §12 | 🔥 |
| Connection pooling limits | Not configured | `redis_client.py:22` | — | §11 | ⭐ |
| Async Redis (`redis.asyncio`) | **Not found** | — | — | §10 | ⭐⭐ (worth knowing it's absent, and why the one `async def` caller is a real mismatch) |
| Hashes | **Not found** | — | — | §9 | ⭐ |
| Lists | **Not found** | — | — | §9 | ⭐ |
| Plain Sets | **Not found** | — | — | §9 | ⭐ |
| Streams | **Not found** | — | — | §9, §15 | ⭐ |
| Pub/Sub | **Not found** | — | — | §9 | ⭐ |
| Celery/RQ (Redis-as-broker) | **Not found** | — | — | §15 | ⭐ |
| Health check (app-level) | **Not found** | — | `/health` only checks Postgres | §5.8 | ⭐⭐ |
| Auth / TLS | **Not configured** | `docker-compose.yml` redis service | — | §19 | 🔥 (for the security question specifically) |
| Redis unit tests | Yes (one component only) | `test_llm_rate_limiter.py` | `_DeadRedis` fake | §16 | ⭐⭐ |
| Redis integration tests | Yes (one component only) | `test_llm_rate_limiter_redis.py` | real Redis, cross-instance sharing test | §16 | ⭐⭐ |
