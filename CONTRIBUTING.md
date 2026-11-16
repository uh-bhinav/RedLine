# Contributing to RedLine

Thanks for considering a contribution. This document covers dev setup, the testing
convention, and — most importantly — the architectural rules that keep the platform
coherent as it grows. Read the rules section before opening a PR that touches
`apps/api/`; several of them are non-obvious and exist because an earlier version of
this codebase got them wrong once.

## Dev setup

```bash
git clone https://github.com/uh-bhinav/RedLine.git
cd RedLine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"     # everything: server + CLI + test deps
cp .env.example .env             # fill in a GEMINI_API_KEY for integration tests
docker compose up -d postgres redis redpanda clickhouse
alembic upgrade head
python -m apps.api.scripts.seed
```

If you're only working on the CLI (`apps/cli/`), you don't need any of the above —
`pip install -e .` (no extras) installs the CLI's 7 dependencies and nothing else.
That's deliberate; see Rule 6 below.

## Running tests

```bash
pytest -m unit           # no external services, seconds
pytest -m integration    # needs docker compose services running
```

Every new test file needs a `pytestmark = pytest.mark.unit` or
`pytestmark = pytest.mark.integration` at module level. A file with neither is
silently excluded from `pytest -m unit` and will not be counted — this genuinely
happened once (three test files ran zero times under `-m unit` while the docs
claimed a passing count that included them) and `tests/unit/test_packaging.py`
exists partly so packaging drift gets caught the same way test-marker drift did.

- **Unit**: pure logic — a scorer, `_compute_gate_result()`, key naming, TTL
  arithmetic. No Postgres, no Redis, no LLM call, no network.
- **Integration**: needs a real dependency — Postgres for tenant scoping, Redis for
  rate-limiter atomicity (a fake can't prove a Lua script is atomic), a live HTTP
  server for the adapter contract. If your test starts a real server or hits a real
  database, it's integration even if it also asserts pure logic along the way.
- **LLM-calling tests**: wrap the call in `try/except` and `pytest.skip()` on a 429 —
  quota exhaustion is not a test failure.

## The architectural rules

These aren't style preferences. Code that violates them gets asked to change before
merge, and the reasoning is usually "we already tried the other way and it broke."

1. **The eval engine is synchronous.** `eval_engine.py`, every scorer, `gate_engine.py`,
   and both workers are synchronous Python — no `async def`, no `await`, no
   `AsyncSession`. `confluent-kafka` is a synchronous C binding; mixing it with
   asyncio and synchronous SQLAlchemy is a deadlock trap, not a performance win. If
   you think the sync model is the bottleneck, say so and we'll look at the actual
   numbers — Phase 5 has a specific home for that migration (`eval_worker_v3.py`,
   built *alongside* v2, never replacing it).

2. **STABLE CONTRACTs never change their signature.**
   `JobQueue.publish(tenant_id, job_type, payload) -> job_id`,
   `JobQueue.get_status(job_id) -> JobStatus`, and
   `AgentAdapter.run_turn(session_state, user_message) -> AgentTurnResult` are the
   seams that let a transport or an execution target be swapped (Postgres →
   Redpanda; local Python → HTTP) with zero calling-code changes. A new
   implementation is welcome. A new required parameter on an existing one is not.

3. **Model names live in `config/model_profiles.yaml` and nowhere else.** Agents and
   scorers call `get_profile("standard")` / `get_profile("high_reasoning")`, never a
   literal string like `"gemini-2.0-flash"`. This has been violated three times in
   this codebase's history (the RAG agent, the LLM judge scorer, a CLI default) and
   caught each time by grepping for provider model name strings outside this file.

4. **`emit_trace()` calls are always wrapped in `try/except`.** ClickHouse is an
   analytics store; a write failure there must never fail an eval run or corrupt a
   gate decision.

5. **`_compute_gate_result()` (and its Phase 4 sibling, `_compute_ars()`) take
   numbers and return a result — no DB access, no I/O.** `evaluate()` is the
   DB-backed wrapper that resolves the policy and calls the pure function. This is
   what makes gate logic unit-testable without a database.

6. **The CLI never imports from `apps.api`.** It talks to the API over `httpx`, full
   stop. If you're tempted to import a model or a DB helper into a CLI command,
   that's a sign an API endpoint is missing — add the endpoint instead.
   `tests/unit/test_packaging.py` enforces this by grepping `apps/cli/` for
   `apps.api` imports, and separately proves the CLI's base dependencies exclude
   every server-only package (Postgres driver, Kafka client, etc.) — a clean
   `pip install agentbench` must never require a database driver.

7. **Job offsets commit after processing, never before.** `eval_worker_v2.py` calls
   `commit_offset()` only once `run_eval()` has succeeded or definitively failed —
   this is what gives at-least-once delivery its actual guarantee.

8. **Secrets are never stored raw.** API keys and refresh tokens are SHA-256 hashed
   before they touch the database; the raw value is shown exactly once, at creation.

9. **KEDA owns worker replica counts.** The eval-worker Deployment YAML has no
   `spec.replicas` — a `ScaledObject` manages it based on consumer lag. Adding a
   static replica count re-introduces the exact CPU-based scaling this project
   deliberately moved away from.

10. **Never add `prometheus-fastapi-instrumentator`.** It requires
    `starlette>=1.0.0`; this project's FastAPI version ships `starlette` 0.41.x.
    Direct `prometheus-client` usage is the way metrics are exposed here.

The full, longer-form version of these — with rationale and verification commands —
lives in [`.claude/rules/architecture.md`](.claude/rules/architecture.md).

## Recording a decision (ADRs)

If you're proposing something that would be expensive to reverse later (a new
datastore, a deployment target, a frontend framework, a scaling model), write an ADR
in `docs/adr/` before implementing it — see the existing ones for the format. An ADR
states the context, the decision, the consequences (including the ones you don't
love), and the alternatives you rejected and why. `docs/architecture-roadmap.md` §0
is itself an example of correcting course in writing rather than silently diverging
from an earlier plan.

## Where things are (and aren't) yet

`docs/status.md` is the current, unvarnished state — including what's broken and
what's unbuilt. `docs/todo.md` is the active work queue, organized by phase.
`docs/architecture-roadmap.md` explains *why* the phases are ordered the way they
are, including a section (`§0`) on a real correction to that ordering. Read
`docs/status.md` before assuming a feature exists; the five features that make
RedLine different from a generic eval tool (reliability scoring, behavioural diff,
chaos engineering, load testing, failure mining) are Phase 4 and none of them are
built yet.

## Commit style

Keep the "why" in the message, not just the "what" — `git log` should read as a
decision log a future contributor can learn from, not a change log a diff already
tells them. If you touch a router, confirm it's in the service that owns that route
prefix (see the table in `.claude/rules/architecture.md`).
