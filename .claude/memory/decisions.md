# RedLine Decisions — Quick Reference

Fast lookup for architecture decisions. Use this during in-context work to recall "what did we decide and why."

---

## D1: `confluent-kafka` (not `aiokafka`)

- **Why:** Eval engine is synchronous. `aiokafka` requires asyncio event loop — mixing would require rewriting the entire eval pipeline.
- **Never do:** `import aiokafka` or `async def` in the eval engine path
- **Review trigger:** If eval engine is fully rewritten to async (Phase 4+)

---

## D2: Postgres Password Must Match Volume Init

- **Why:** Docker Postgres ignores `POSTGRES_PASSWORD` if the data volume already exists with a different password.
- **Never do:** Change `POSTGRES_PASSWORD` in `docker-compose.yml` without destroying the volume (`docker compose down -v`) or running `ALTER USER redline WITH PASSWORD '...'` inside the container.
- **Port is 5433, not 5432.** Local Postgres occupies 5432. Always use `psql -p 5433`.
- **Review trigger:** If secrets management (Vault) is added in Phase 4

---

## D3: KEDA Consumer Lag for Workers, CPU HPA for Services

- **Why:** Worker is I/O-bound on Gemini API calls — CPU stays <10% even at full load. CPU HPA never triggers. Consumer lag is the real backlog signal.
- **Never do:** Set `spec.replicas` in the eval worker Deployment YAML — KEDA owns replicas.
- **Never do:** Use CPU HPA for the eval worker.
- **eval-service and agent-service use CPU HPA** (they're stateless request handlers — CPU is the right signal).
- **Review trigger:** If eval engine becomes CPU-bound (e.g., local embedding inference replaces Gemini)

---

## D4: Model Profiles, Not Hardcoded Model Names

- **Why:** Eval suites must be provider-agnostic. `model_profile: standard` in a suite YAML continues to work if the underlying model changes in `config/model_profiles.yaml`.
- **Never do:** Write `"gemini-2.5-flash"` directly in agent code or scorer code.
- **Always do:** `get_profile("standard")` → `profile.model_name`
- **LLM judge always uses `high_reasoning` profile** regardless of which profile the agent under test uses.
- **Review trigger:** When adding a new provider — add a profile in `model_profiles.yaml`, not a code change.

---

## D5: In-Process Rate Limiter (Phase 2), Redis Rate Limiter (Phase 3)

- **Why:** Phase 2 has exactly one worker process. A Redis distributed lock adds infra complexity with zero benefit for single-worker.
- **`LLMRateLimiter`** uses a sliding window `deque[float]` of timestamps. `acquire()` blocks (sleeps) until a slot is available.
- **Never do:** Skip `rate_limiter.acquire()` before a Gemini API call — you'll get 429s.
- **Phase 3 action:** Replace `LLMRateLimiter` with Redis sorted set implementation. Calling code (`acquire()`) does not change.
- **Review trigger:** When multiple eval worker pods run concurrently in k3d (Phase 3)

---

## Quick Decision Table

| Situation | Decision | Never Do |
|---|---|---|
| Need Kafka client | confluent-kafka | aiokafka |
| Changed DB password | `down -v` + reinit or `ALTER USER` | Edit .env only |
| Worker autoscaling | KEDA consumer lag | CPU HPA for workers |
| Reference a model | `get_profile("standard")` | `"gemini-2.5-flash"` |
| Rate limiting (Phase 2) | In-process deque | Redis (Phase 2 only) |
| Store an API key | SHA256(raw).hexdigest() | Store raw key |
| Store a password | bcrypt via passlib | MD5, SHA1, plaintext |
| Refresh token reuse | Revoke ALL sessions for user | Revoke only replayed token |
| Add a scorer | Return ScorerResult | Return raw bool |
| ClickHouse failure | Log warning, continue | Raise or fail the eval run |
| New worker replica count | Let KEDA manage | Set spec.replicas manually |
| CLI needs API data | httpx via api_client.py | Import from apps.api.models |
