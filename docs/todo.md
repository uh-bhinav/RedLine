# RedLine — TODO

**Repository:** `uh-bhinav/RedLine`
**Current Phase:** Phase 4 complete + Phase 4.5 cleanup pass done — Phase 5 next. See `docs/architecture-roadmap.md`
**Last updated:** 2026-07-29

> Phase ordering was corrected on 2026-07-29. Phase 3 is now a **thin** infrastructure slice —
> only items a Phase 4 novelty feature has a hard dependency on. Everything else moved to Phase 5.
> Read §0 of `docs/architecture-roadmap.md` for the reasoning.

---

## ✅ Phase 3.1 — Real Tenant Scoping + Dashboard Auth (DONE 2026-07-29)

*Blocked: all of Phase 4. Now unblocked.*

- [x] `TenantContext` + `get_tenant_context()` + `require_tenant_role()` in `apps/api/core/security.py`
- [x] `db.query(Tenant).first()` removed from `routers/dashboard.py` (both sites) and `routers/eval_runs.py`
- [x] All `/dashboard` routes require auth; any role (they are read-only)
- [x] `POST /eval-runs` requires admin/developer — it spends the tenant's LLM budget
- [x] Single-object lookups (`agent_detail`, `run_detail`, `get_eval_run`) verify tenant ownership;
      foreign resources 404 rather than 403 so UUID probing cannot confirm existence
- [x] `apps/api/tests/integration/test_tenant_isolation.py` — 11 tests, all passing
- [x] Negative control verified: reintroducing the missing ownership check makes 2 tests fail
- [x] Grep gate: `grep -rn "query(Tenant)" apps/api/routers apps/api/core` returns only doc comments
- [x] v1 dashboard given `src/api.js` + `src/TokenGate.jsx` so it survives the auth change
      (ADR-006 follow-up; not a login flow — replaced wholesale in Phase 5)

**Follow-up opened by this work:**
- [x] `apps/api/scripts/{create_api_key,register_agent_version,push_suite}.py` still use
      `db.query(Tenant).first()`. They are operator bootstrap tools, not request paths, so this is
      not a leak — but they need a `--tenant` argument before a second tenant is real.
      **(DONE 2026-07-29, Phase 4.5 cleanup):** added `apps/api/scripts/_tenant.py`'s
      `resolve_tenant()` (UUID or exact-name lookup, clear errors for zero/ambiguous tenants) and a
      `--tenant` CLI flag to all three scripts. Grep gate: zero `query(Tenant).first()` left in
      `apps/api/scripts/`. 6 new integration tests in `test_tenant_resolution.py` (4 passed, 2
      honestly skipped — the single-tenant-no-arg case can't be constructed without deleting the
      real seeded tenant in a shared dev DB).

---

## ✅ Test Suite Integrity (DONE 2026-07-29)

Found while verifying 3.1: `pytest -m unit` was running **39** tests, not the 58 the docs claimed.

- [x] `test_scorers.py` (15 tests) had no `pytestmark` — silently excluded from `-m unit`.
      These are the scorer tests the project's own contributing rules require. Marked `unit`.
- [x] `test_local_python_adapter.py` (4 tests) — same. Marked `unit`.
- [x] `test_jobqueue.py` — no marker, and opens real `SessionLocal` connections to test SKIP LOCKED.
      It is an integration test; moved to `tests/integration/` and marked `integration`.
- [x] `test_llm_judge_scorer.py` — no marker despite making real LLM calls. Marked `integration`.
- [x] `pytest -m unit` now genuinely runs **58 passing tests**. The docs' claim is true for the
      first time. **Stale as of 2026-07-29 (Phase 4.5 cleanup):** the real count is now
      **214 passing, 74 deselected** — grown across every Phase 4 feature built since. Verify with
      `pytest -m unit -q | tail -3` rather than trusting either number going forward.
- [x] Add a CI check that fails on any test file lacking a `pytestmark`, so this cannot silently
      recur. **(DONE 2026-07-29, Phase 4.5 cleanup):** `apps/api/scripts/check_pytestmark.py` — AST-based
      (no test-module imports, no infra needed), walks every `test_*.py` for a module-level
      `pytestmark` referencing `pytest.mark.unit`/`.integration`. Wired into a new
      `.github/workflows/test-suite-integrity.yml`, runs on every PR. Verified against the real
      (clean) tree and via negative control (stripped `test_scorers.py`'s marker, confirmed the
      check fails and names the file, restored it).

---

## ✅ Phase 3.2 — HTTPAdapter for External Agents (DONE 2026-07-29)

*Blocked: 4.3 Chaos, 4.4 Load Testing, and every open-source user. Now unblocked.*

- [x] `apps/api/services/adapters/http_adapter.py` — implements the `AgentAdapter` Protocol
- [x] POST `{"session_state": ..., "user_message": ...}` → parse `AgentTurnResult`
- [x] `build_adapter()` in `adapters/__init__.py` selects by entrypoint shape:
      `module:function` → `LocalPythonAdapter`, `http(s)://…` → `HTTPAdapter`. No migration needed.
- [x] `session_state` written back **in place** (clear + update, not rebind) — the eval engine
      holds one dict across every turn of a case, so rebinding would silently drop multi-turn state
- [x] Latency is the observed round-trip, not agent-self-reported — the gate asserts what a user
      experiences, which for a deployed agent includes the network
- [x] Narrow retry policy: connect errors and 502/503/504 only. **Read timeouts are never
      retried** — the turn may have been processed, and retrying would make the platform cause the
      duplicate-side-effect incidents it exists to catch
- [x] `docs/http-agent-contract.md` — the agent-side contract for outside users
- [x] `examples/http-agent/server.py` — runnable reference agent (also the contract's worked example)
- [x] `apps/api/tests/unit/test_http_adapter.py` — 23 tests, `httpx.MockTransport`, no network
- [x] `apps/api/tests/integration/test_http_adapter_end_to_end.py` — 4 tests running the **real**
      eval engine against the **real** reference agent over HTTP; asserts case results, multi-turn
      state round-trip, gate verdict, and that an unreachable agent fails the run
- [x] Verified via Redpanda: `publish()` completes in ~70ms with the bounded flush; the earlier
      hang is resolved and `RedpandaJobQueue` is restored in `routers/eval_runs.py`

**Honest note on the STABLE CONTRACT:** `eval_engine.py` is *not* byte-for-byte unchanged — one
construction line became `build_adapter(agent_version.entrypoint)` and the `_run_case` type hint
widened to `AgentAdapter`. The contract that held is the one that matters: the per-turn calling
code (`adapter.run_turn(...)`), every scorer, and the gate engine are untouched, and the engine
still cannot tell a local agent from a remote one.

**Follow-up opened by this work:**
- [x] `apps/api/services/scorers/llm_judge.py:21` has `JUDGE_MODEL = "gemini-2.5-flash"` hardcoded.
      Same violation of architectural rule #3 as Bug 3, in a second file. Fold into the Bug 3 fix.
      **(DONE, folded into Bug 3):** now `_JUDGE_PROFILE = get_profile("high_reasoning")`, no
      hardcoded model name — verified by grep, zero literal `"gemini-` strings left in `llm_judge.py`.
- [x] `ConsoleSpanExporter` writes to stdout after pytest closes it, producing a noisy
      `ValueError: I/O operation on closed file` at teardown. Harmless, and another argument for
      Phase 5.1 (OTLP → Tempo). **(DONE 2026-07-29, Phase 4.5 cleanup):** root-caused —
      `BatchSpanProcessor`'s `daemon=True` export thread holds a reference to whatever `sys.stdout`
      was at import time (pytest's capture proxy), and fires on its own schedule, sometimes after
      pytest tears that buffer down. Fixed with a `pytest_sessionfinish` hook in the new
      `apps/api/tests/conftest.py` that explicitly shuts the tracer provider down (flushes + joins
      the thread) while capture is still live. Verified: 3 clean unit runs + 2 clean integration
      runs with the fix; negative control (removed the hook) reproduced the noise reliably on 2/2
      tries, restored and reconfirmed clean.

---

## ✅ Phase 3.3 — Redis-Backed LLM Rate Limiter + Daily Quota (DONE 2026-07-29)

*Blocked: 4.2 Behavioral Diff, 4.4 Load Testing, and the Level 3/4 gate verdicts. Now unblocked.*

- [x] Redis sorted-set sliding window, key `ratelimit:llm:{provider}:{model}`
- [x] Daily counter `quota:llm:{provider}:{model}:{YYYY-MM-DD}`, TTL = rest of UTC day + 1h slack,
      checked **before** the per-minute window so an exhausted quota short-circuits instead of
      making the caller sit through a minute-long wait only to then be refused
- [x] `daily_limit` added to `config/model_profiles.yaml` + `ModelProfile`
      — ⚠️ **values are estimates; verify against current provider docs**
- [x] `acquire()` signature unchanged (STABLE CONTRACT)
- [x] **Lua script for check-and-add.** A pipeline is a race: two workers can both read
      `count = rpm-1` and both proceed. Since the entire point of moving to Redis is coordination
      between workers, the check and the add must be one atomic operation
- [x] `DailyQuotaExceeded` **raises rather than blocks** — the quota resets at midnight UTC, so
      sleeping would hold a worker for hours
- [x] Graceful degradation to the per-process window when Redis is unreachable, warned **once**
      per limiter, not per call. Deliberately the lenient failure: refusing all LLM calls because
      Redis is down would turn a cache outage into a total platform outage
- [x] `tests/unit/test_llm_rate_limiter.py` — 18 tests (keys, TTL arithmetic incl. month/year end,
      degraded fallback, profile wiring). No Redis needed
- [x] `tests/integration/test_llm_rate_limiter_redis.py` — 12 tests against **real Redis**, because
      a fake cannot prove script atomicity. Includes the multi-worker claim and an 8-thread
      concurrency test asserting the limit is never overshot
- [x] Verified live: two limiters sharing a budget, and a real `docker compose stop redis`
      confirming degradation logs and keeps working

**Bugs found and fixed in `eval_engine.py`'s error handler while wiring the quota failure path:**
- [x] `span.record_exception(Exception())` recorded a **blank** exception, discarding the only
      diagnostic the failure span carried. Now records the real one.
- [x] Failure traces were emitted with `tenant_id=uuid.uuid4()` — a **random** tenant. Since the
      ClickHouse traces table is `ORDER BY (tenant_id, eval_run_id, created_at)`, every failed run
      was invisible to any per-tenant query. Failures were the one thing you would look for. Now
      uses the run's real tenant and includes the exception message in `detail`.

**Test isolation bug found and fixed:**
- [x] `test_worker_restart.py` asserted `claim_next_job()` returns `None`, which assumes a globally
      empty queue. `claim_next_job` is scoped by job_type only, so any unrelated pending job makes
      it fail — it passed alone and failed in a full run. It was order-dependent before this work;
      moving `test_jobqueue.py` into `integration/` exposed it. Now asserts the narrower invariant
      that actually matters (the in_progress job is never handed out again) and releases anything
      unrelated it claimed.

**Follow-up opened by this work:**
- [x] Callers currently let `DailyQuotaExceeded` propagate, which fails the run with a clear reason
      in the trace. Consider surfacing it on `EvalRun` itself — the table has no `error` column, so
      the dashboard shows "failed" with no explanation. **(DONE 2026-07-29, Phase 4.5 cleanup):**
      added `EvalRun.error` (migration `0009`), `eval_engine.py`'s failure handler now sets
      `failed_run.error = f"{type(exc).__name__}: {exc}"[:2000]`, threaded through
      `EvalRunResponse`/`EvalRunSummary`/`RunDetailResponse` and the CLI's failure message. Verified
      end-to-end with a real failed run (dead HTTP endpoint) through the actual API (not just the
      DB row) via `test_eval_run_error_field.py`, plus a negative control (reverted the one-line
      fix, 3/4 new tests correctly failed, restored). Also caught **live**, for real, days later
      during the Level 3/4 verdict work: a genuine Gemini 503 and a genuine internal daily-quota
      exhaustion both surfaced correctly through this exact field via the CLI.
- [x] Verify the `daily_limit` values in `config/model_profiles.yaml` against current Gemini
      free-tier documentation before relying on them. **(DONE 2026-07-29, Phase 4.5 cleanup)** —
      turned out to be a much bigger finding than a stale number. See `config/model_profiles.yaml`'s
      header comment for the full account: `gemini-2.0-flash`/`gemini-2.0-flash-lite` (the previous
      `standard`/`cheap` models) are **shut down** by Google outright — every call would have failed,
      not just miscounted a quota. Remapped to `gemini-2.5-flash` / `gemini-3.5-flash` /
      `gemini-3.5-flash-lite`. `standard`'s `daily_limit` is now **ground truth** (20/day, read
      directly off a real 429's quota-metering body during the Level 3/4 verdict work), not a
      blog guess. Also found live: `gemini-2.5-flash-lite` 404s as "no longer available to new
      users" on this project's actual key, despite still being documented as stable.

**New bug found during Phase 4.5 cleanup (not previously tracked anywhere in this doc):**
- [x] **`get_limiter(profile_name)` was keyed to `profile.chat_model` unconditionally, cached by
      `profile_name` alone.** `apps/api/services/embeddings.py` calls `get_limiter("standard")` for
      **embedding** calls — the exact same call agents make for **chat** calls on the same profile —
      so both got the same cached limiter, tracked in Redis against the chat model's name even
      though the embedding calls actually hit a different model (`gemini-embedding-001`) on the
      provider's side. Every embedding call this platform has ever made (`diff_engine`, `mining`) was
      silently sharing `rag_agent`'s real chat rate/quota bucket, under the wrong model's name. The
      same exact bug existed independently in all three benchmark agents (`rag_agent`,
      `stateful_support_agent`, `research_pipeline_agent`) — one shared `_limiter` for both purposes.
      Fixed: `get_limiter(profile_name, *, for_embedding: bool = False)`, cache keyed on
      `(profile_name, "embedding"|"chat")`, resolves `profile.embedding_model` vs `profile.chat_model`
      accordingly. All three agents and `embeddings.py` updated to acquire the correct limiter for
      each call type. Verified live: a real Redis key
      `quota:llm:gemini:gemini-embedding-001:<date>` now increments independently of
      `gemini-2.0-flash`'s (at the time). 4 new unit tests added; negative control confirmed 2/4 fail
      when the fix is reverted.

---

## ✅ Phase 3.4 — Installable `agentbench` CLI (DONE 2026-07-29)

*Blocked: 4.2/4.3/4.4, which all ship as CLI verbs. Now unblocked.*

- [x] `pyproject.toml` with console script `agentbench = "apps.cli.main:app"`
- [x] Dependency split: base = 7 CLI packages; `[api]` extra carries the server tree; `[dev]` carries pytest
- [x] `[tool.setuptools] packages` is explicit, not auto-discovered — auto-discovery would sweep in
      `agents/` (fixtures under test, not library code) and `apps.api`
- [x] **Verified in a clean venv**: `pip install .` pulls 20 packages, **zero** server dependencies
      (no psycopg2, sqlalchemy, confluent-kafka, clickhouse-driver, fastapi, redis, numpy, google-genai)
- [x] **Verified `agentbench --help` and all 6 subcommands run from outside the repo** (`/tmp`)
- [x] `[api]` extra resolves (pip dry-run, 70 packages)
- [x] `.github/workflows/agentbench-check.yml` install step is now `pip install .`, and the
      `python -m apps.cli.main` invocations are now `agentbench`
- [x] Dropped the workflow's `.env` shim — it existed only so a `Settings` import would not crash,
      and the CLI does not import `apps.api` at all
- [x] Dropped `GEMINI_API_KEY` from the workflow — the CLI never calls an LLM, so the CI job was
      holding a provider key it had no use for
- [x] `tests/unit/test_packaging.py` — 8 tests: no server packages in base deps, no `apps.api`
      imports anywhere in `apps/cli/` (rule #6 as a test), pyproject `[api]` and
      `requirements.txt` agree, everything pinned, rule #10's
      `prometheus-fastapi-instrumentator` still absent
- [x] Stale CLI help text ("RedLine Phase 1") replaced

**Bugs found and fixed while packaging:**
- [x] `register_version.py` could not register HTTP agents at all — `_compute_content_hash` did
      `rsplit(":", 1)` on the entrypoint, so `https://host/turn` became module `https` and raised
      `ModuleNotFoundError`. Everything shipped in Phase 3.2 was unreachable from the CLI. Now
      hashes the URL for HTTP agents (honest: we cannot see their source) and accepts
      `--content-hash <git-sha>` to give Phase 4.2's diff engine a real code axis.
- [x] `register_version.py` had `--model` defaulting to a hardcoded `"gemini-2.5-flash"` —
      architectural rule #3, third occurrence. Now a required option.
- [x] **All three Dockerfiles omitted `COPY config ./config`.** `model_profiles.py` resolves
      `config/model_profiles.yaml` relative to the repo root, so every containerised service would
      raise `FileNotFoundError` on the first `get_profile()` call. The images built and started
      fine and failed on first eval. Verified fixed: rebuilt `eval_service` now resolves
      `standard -> gemini-2.0-flash, rpm=15, daily_limit=200` and its limiter reaches Redis
      (`degraded = False`) from inside the container. **`standard`'s model is stale as of
      2026-07-29** — `gemini-2.0-flash` has since been shut down by Google; see the Phase 3.3
      follow-up below for the remap to `gemini-2.5-flash`.

**Follow-up opened by this work:**
- [x] ⚠️ **Security:** all three Dockerfiles `COPY .env .env`, baking secrets into the image.
      Foundational document §10.10 explicitly forbids this ("never committed to Git, never baked
      into images"). Every layer of those images carries the Gemini key and JWT secret, and anyone
      who pulls the image can read them. Should come from ConfigMap/Secret only. Not fixed here
      because removing it requires confirming compose + Helm supply every variable, and a wrong
      move breaks the running stack. **Phase 5.2 security pass, or sooner.**
      **(DONE 2026-07-29, Phase 4.5 cleanup):** removed `COPY .env .env` from all three Dockerfiles;
      confirmed both paths that need env vars are unaffected — docker-compose's own `env_file: .env`
      directive, and Helm's Secret/ConfigMap injection via `_helpers.tpl`'s `commonEnv`. Verified
      live: rebuilt all three images, confirmed `.env` genuinely absent inside each
      (`docker run --rm --entrypoint sh <image> -c 'test -f /app/.env && echo FOUND_BAD || echo
      absent_good'` → `absent_good` for all three), restarted the stack, confirmed all three
      `/health` endpoints still healthy and `Settings()` still resolves every secret correctly from
      the running containers.
- [x] Rebuild `gate_service` and `agent_service` images to pick up the `config/` fix
      (only `eval_service` was rebuilt and verified). **(DONE, same pass as the `.env` fix above —
      all three rebuilt together.)**

---

## ✅ Phase 3.5 — Open-Source Scaffolding + Repo Hygiene (DONE 2026-07-29)

*Required by the stated goal: open-source contributions. Phase 3 is now complete.*

- [x] `README.md` — positioning vs LangSmith/Braintrust/Arize, architecture diagram, verified
      quickstart (every command checked against the real CLI signatures), "bring your own agent"
      section, and an honest state-of-the-project table (0/5 novelty features, stated plainly)
- [x] `LICENSE` — Apache-2.0, unmodified canonical text (verified against apache.org so GitHub's
      license detector recognizes it)
- [x] `CONTRIBUTING.md` — dev setup, test conventions, the 10 architectural rules condensed with
      rationale, ADR process, points to `.claude/rules/architecture.md` for full detail
- [x] `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- [x] `.github/ISSUE_TEMPLATE/bug_report.md`, `feature_request.md`, `.github/PULL_REQUEST_TEMPLATE.md`
      — the PR template's checklist mirrors the architectural rules so a reviewer doesn't have to
      hold all 10 in their head
- [x] Deleted `run.log` (57KB), `CI_TEST.md`, `CI_TEST1.md` via `git rm`; deleted all 15 `.DS_Store`
      files from disk (already gitignored, so untracked — just clutter)
- [x] `.gitignore`: added `*.log`, `*.egg-info/`, `build/`
- [x] **Bug 1** — removed the debug `print()` calls and dead commented-out prints from
      `_load_chunks()` / `_ensure_knowledge_base_indexed()` in `agents/rag_agent/agent.py`
- [x] **Bug 3** — `agents/rag_agent/agent.py`'s `CHAT_MODEL = "gemini-2.5-flash"` replaced with
      `get_profile("standard")` + `get_limiter("standard").acquire()` on both the embed and generate
      calls. Verified: `PROFILE.chat_model == "gemini-2.0-flash"`, limiter wired.

**A second and third hardcoded-model instance found and fixed while closing Bug 3** (the todo
already flagged the first as a Phase 3.2 follow-up):
- [x] `apps/api/services/scorers/llm_judge.py` had `JUDGE_MODEL = "gemini-2.5-flash"` **and made
      zero rate-limiter calls at all** — every judge call was unmetered against both the per-minute
      window and the Phase 3.3 daily quota. Since the judge is called once per case with a
      `judge_rubric` (the baseline rag-agent suite uses one on 2 of 3 cases), this silently
      undermined the entire reason 3.3 was built. Fixed: uses `get_profile("high_reasoning")` +
      `get_limiter("high_reasoning").acquire()`. **Verified against real Gemini, not mocked**: ran
      `test_llm_judge_scorer.py` live, confirmed the Redis daily counter
      (`quota:llm:gemini:gemini-2.5-flash:<date>`) incremented by exactly 2 — matching the 2 tests
      that reach the API call (the third short-circuits on no rubric).
- [x] `apps/cli/commands/register_version.py` — `_compute_content_hash` could not register an HTTP
      agent at all: it did `entrypoint.rsplit(":", 1)` unconditionally, so `https://host/turn` was
      parsed as module `https`, raising `ModuleNotFoundError`. **Every HTTP agent shipped in Phase
      3.2 was unreachable from the CLI** until this fix. Now hashes the URL for HTTP agents (honest:
      the source is genuinely unknown) and accepts `--content-hash <git-sha>` so Phase 4.2's
      behavioural diff engine gets a real code axis instead of a URL hash that never changes.
      `--model` was also a hardcoded-default option; now required.

**Infrastructure bugs found and fixed while verifying all of the above against a real stack:**
- [x] **All three Dockerfiles baked `.env` secrets into the image via `COPY .env .env`** —
      discovered while confirming the `config/` fix (below) didn't paper over a bigger problem. This
      violates §10.10 of the foundational document explicitly. **Not fixed** — see the open item
      below; this needs Helm/compose variable coverage confirmed first, and a wrong move here breaks
      the running stack.
- [x] All three Dockerfiles omitted `COPY config ./config` — `model_profiles.py` resolves
      `config/model_profiles.yaml` relative to the repo root, so every containerised service raised
      `FileNotFoundError` on the first `get_profile()` call. Images built and started fine; failed on
      first eval. **Verified fixed in all three**, rebuilt: `eval_service`, `gate_service`,
      `agent_service` each confirmed to have `config/` present and `get_profile("standard")` /
      `get_limiter("standard")` resolving correctly from inside the container.
- [x] **A stray `DATABASE_URL` in the user's local Claude Code harness config
      (`.claude/settings.local.json`, gitignored/personal) had a different password than the repo's
      `.env`** and was silently overriding it in every shell command this session, because
      pydantic-settings prioritizes real environment variables over `.env` file values by design.
      This caused ~15 minutes of intermittent, hard-to-reproduce `password authentication failed`
      errors across integration test runs that had nothing to do with any code change. **Not
      something I can fix from a repo file** — flagged to the user directly rather than silently
      edited, since it's personal harness configuration, not project code.
- [x] Independent of the above: `.env` / `.env.example` changed `DATABASE_URL`'s host from
      `localhost` to `127.0.0.1`. On this machine `localhost` sometimes resolves to `::1`, and
      Postgres's `pg_hba.conf` has separate rules per loopback address — pinning to the literal IPv4
      address removes that ambiguity for every future contributor on a dual-stack machine,
      independent of the harness-config issue above.
- [x] `test_worker_restart.py` — see the note under Phase 3.3; still holds after this round of fixes
      (verified: 33/33 integration tests pass together, not just individually)

**Final verification (this round, real Postgres + Redis + Redpanda + ClickHouse + live Gemini):**
`pytest -m unit`: **107 passed**. `pytest -m integration` (all files together, excluding the
LLM-cost-heavy `test_eval_end_to_end.py`): **33 passed**. `test_llm_judge_scorer.py` run standalone
against live Gemini: **3 passed**, Redis quota counter confirmed incrementing correctly.

**Open items from this phase:**
- [x] ⚠️ Fix the `COPY .env .env` secret-baking in all three Dockerfiles (flagged in 3.4, confirmed
      still present). Needs compose/Helm variable coverage verified first — Phase 5.2 security pass,
      or sooner if you want it done now. **(DONE 2026-07-29, Phase 4.5 cleanup — see the Phase 3.4
      follow-up above for the full verification.)**
- [x] Only `eval_service`, `gate_service`, `agent_service` images were rebuilt with the `config/`
      fix — if any other image-building path exists (CI, a registry push), rebuild there too.
      **(No other image-building path exists yet** — confirmed by inspection: no CI workflow builds
      or pushes images, the only build paths are `docker compose build` and the Makefile's
      `images-build`, both exercised during this cleanup pass.)
- [ ] `docs/todo.md`'s own claim about a `.claude/settings.local.json` `DATABASE_URL` mismatch
      should be corrected by hand once you decide what that file should actually contain — it's
      gitignored, so this is a one-person fix, not something a PR can carry. **Still unresolved** —
      still true as of 2026-07-29 (confirmed the shell's `DATABASE_URL`/`CLICKHOUSE_PORT` still don't
      match `.env`, worked around with `env -u` throughout this session's verification, same as
      before). Genuinely a one-person fix; not something I can act on.

---

## 🟡 Carried Over — Not Phase-Blocking

- [x] **Bug 2** — k3d eval-service Redpanda connectivity: add
      `REDPANDA_BOOTSTRAP_SERVERS: "192.168.65.254:19092"` to the `eval_service` environment block
      in `docker-compose.yml` / `helm/redline/templates/base/configmap.yaml`, then `make helm-upgrade`
      **(DONE 2026-07-29, Phase 4.5 cleanup — and the original proposed fix above was itself
      incomplete):** confirmed via a live k3d cluster that the static Helm wiring
      (`host.k3d.internal:19092` in the ConfigMap → pod env) was already correct, but pods still
      failed with `Connection refused` on every call past the initial bootstrap. Root cause: Kafka's
      client protocol reconnects using the broker's *advertised* listener address from metadata, not
      the address you originally dialed. Redpanda's external listener advertised `localhost:19092`
      (correct for a Mac-host client) — from inside a k3d pod, "localhost" is the pod itself, so
      every post-bootstrap call failed. A single external listener cannot correctly serve both a
      host-machine client and in-cluster pods at once. Fixed by adding a **third, dedicated `k3d`
      listener** to Redpanda (`docker-compose.yml`, port 29092) that advertises
      `host.k3d.internal:29092`, and pointing Helm's `redpandaBootstrapServers` at it instead.
      Verified end-to-end: registered a real agent/suite through the k3d gateway, created a real
      eval run, watched the k3d `eval-worker` pod consume it from Redpanda and complete it with a
      passing gate verdict — status `completed`, `gate_result.passed: true`. Regression-checked the
      original Mac-host listener still works unchanged. Also found and fixed in the same pass: the
      Helm chart hard-failed `helm install` on a cluster without Prometheus Operator CRDs installed
      (`ServiceMonitor` had no capability guard) — added
      `{{- if .Capabilities.APIVersions.Has "monitoring.coreos.com/v1/ServiceMonitor" }}`.
- [x] Run Level 3 gate verdict: `python -m apps.cli.main run --suite stateful-support-agent-baseline`
      *(unblocked once 3.3 daily quota tracking lands)* **Attempted 2026-07-29 — blocked, honestly,
      by real infrastructure, not a bug:** `stateful-support-agent` uses the `high_reasoning` profile
      (`gemini-3.5-flash`). Two independent real provider issues hit in sequence during this same
      session: (1) `gemini-3.5-flash` returned a genuine, extended Google-side 503 "high demand"
      outage; (2) RedLine's own internal daily quota for `high_reasoning` (100/day, keyed to the
      *configured* model regardless of any runtime substitution) was then exhausted by the retries
      and by the Level 4 run below — and `DailyQuotaExceeded` was correctly caught and surfaced
      through `EvalRun.error` (see the 3.3 follow-up above), proving that exact mechanism works
      end-to-end under real load. Resets at UTC midnight; not something to force past today.
      **Not yet re-attempted after reset — retry `agentbench run --suite
      stateful-support-agent-baseline` once the daily window turns over.**
- [x] Run Level 4 gate verdict: `python -m apps.cli.main run --suite research-pipeline-agent-baseline`
      **DONE 2026-07-29 — real completed verdict obtained: FAILED.** `research-pipeline-agent` was
      registered fresh (it didn't exist yet) via `agentbench init`/`push-suite`/`register-version`
      against the live docker-compose stack. Hit the same `gemini-3.5-flash` 503 outage as Level 3;
      completed the run with a temporary, in-process-only model substitution (`gemini-3.1-flash-lite`,
      confirmed compatible with the agent's exact `thinking_config`) rather than touching the
      committed `high_reasoning` profile over what its own error called a temporary spike. Result:
      `status: completed`, `gate.passed: False` — pass_rate 0.50 vs the 0.90 required, plus an ARS
      error-budget breach. 2 of 6 cases (`basic_coordination`, `sub_query_distinctness`,
      `verifier_catches_gaps`) failed on real scorer findings, not infra flakiness. This is a
      genuine, real gate verdict for a newly-built agent — a failing one, which is a legitimate
      outcome, not a blocker.
- [x] Verify actual unit test count (`pytest -m unit -q | tail -3`); docs claim 58 **— re-verified
      2026-07-29: 214 passed, 74 deselected** (grown since the 58 count was last true; see the Test
      Suite Integrity section above).

---

## 🎯 Phase 4 — Research-Grade Novelty (the differentiator)

None of these exist today. `_SCORERS` is `[ContainsMatch, Cost, Latency, LLMJudge]`.
Full design in `docs/architecture-roadmap.md` Phase 4.

### ✅ 4.1 Agent Reliability Score + SLO / Error Budget (DONE 2026-07-29)

- [x] `SafetyScorer` (`apps/api/services/scorers/safety.py`) — always-on retrieval-groundedness
      check (a retrieval-shaped tool call returning empty must be paired with an honesty phrase,
      or it's a hallucination-without-grounding — the exact failure mode `rag_agent`'s own docstring
      names as its reason for existing) + optional `safety_rubric` LLM-judge escape hatch, parallel
      to `judge_rubric`. Deliberately does **not** attempt prompt-injection detection as a generic
      heuristic — that's honestly Phase 4.3's job (`ChaosAdapter` injects real controlled faults;
      a keyword guess here would give false confidence in either direction)
- [x] `_compute_ars()` — pure function, same discipline as `_compute_gate_result()`. Weights
      (0.4/0.2/0.2/0.2) sum-to-one verified by test. Each sub-score is `passed/total` for the
      scorer(s) that measure that dimension (correctness = ContainsMatch AND LLMJudge; safety =
      SafetyScorer; latency = LatencyScorer; cost = CostScorer) — read from each case's already-
      stored `scorer_results`, no re-scoring
- [x] `compute_error_budget()` — pure function, the actual SRE mechanic: breach rate over a
      window vs an allowed budget, `exhausted` when breach rate exceeds the allowance
- [x] Tables `slo_policies`, `ars_snapshots` + migration `0005`, applied and verified against real
      Postgres (`\d slo_policies`, `\d ars_snapshots` both confirmed)
- [x] `GatePolicy.min_ars` + ARS threshold folded into `_compute_gate_result()`, staying pure
      (verified: every pre-existing gate test still passes unchanged, since `ars`/`min_ars` default
      to `None`)
- [x] Error-budget freeze wired into `gate_engine.evaluate()` — deliberately **not** part of the
      pure function (it's a statement about history, not this run's numbers). **Verified end to
      end**: a run scoring a perfect ARS of 1.0 still fails the gate when the agent's recent history
      has burned its error budget — proven with a negative control (temporarily disabled the check,
      confirmed the test catches it, restored)
- [x] `ars_engine.evaluate_ars()` computes + persists **once**, at run completion inside
      `eval_engine.run_eval()` (non-fatal, like `emit_trace()`) — **not** inside
      `gate_engine.evaluate()`, which is a read path called on every dashboard load and must not
      also be a write path
- [x] `apps/api/tests/unit/test_ars_engine.py` (18 tests) + `test_gate_engine.py` ARS extensions
      (5 tests) + `test_scorers.py` SafetyScorer extensions (10 tests) — all pure, no DB
- [x] `apps/api/tests/integration/test_ars_end_to_end.py` (7 tests) — **real** eval engine, **real**
      Postgres, zero-LLM-cost `dummy_agent` fixture: snapshot persistence, upsert-not-duplicate,
      min_ars threshold, and the error-budget freeze proven live
- [x] `ExpectationsYAML` gained `safety_rubric: str | None` — without it, `model_dump(exclude_none=True)`
      silently drops the key before it ever reaches the DB (verified against `eval_suites.py`'s and
      `push_suite.py`'s actual conversion code, not assumed)

**Bugs found and fixed while building this:**
- [x] **Real regression**: the earlier Bug 3 fix (Phase 3.5) removed `rag_agent.CHAT_MODEL`, but
      `test_eval_end_to_end.py` still monkeypatched that exact attribute name to swap in a cheap
      test model. Excluded from every regression run since it's LLM-cost-heavy, so this went
      unnoticed until now. Fixed: patches `rag_agent.PROFILE.chat_model` in place instead (`ModelProfile`
      is a plain, non-frozen dataclass). Verified the patch/restore cycle mechanically; a full live
      run hit a **genuine** Gemini daily-quota 429 for `gemini-2.0-flash` and skipped cleanly — real
      resource exhaustion, not a bug, and exactly what Phase 3.3's quota tracking exists to surface
      instead of an opaque crash.
- [x] **`ars_snapshots` FKs to `eval_runs`, and `test_http_adapter_end_to_end.py`'s fixture deleted
      `EvalRun` rows in teardown without deleting the now-automatically-created `ars_snapshots` row
      first** — `IntegrityError` on `ars_snapshots_eval_run_id_fkey`. Fixed the teardown order.
      Audited every other integration test that both runs a real eval AND tears down `EvalRun` rows
      (`test_eval_end_to_end.py` doesn't delete; `test_ars_end_to_end.py` was already ordered
      correctly by design) — confirmed no other fixture has this gap.
- [x] **`SafetyScorer` caught a genuine ungrounded answer in `examples/http-agent/server.py`'s own
      multi-turn fallback** ("Following up on your earlier question: ..." on a turn where retrieval
      found nothing new) — this is real scorer behavior working as intended, not a false positive.
      Fixed the reference agent to be honest about it ("I don't have new information on that, but
      earlier I said: ...") rather than papering over the finding — a reference implementation
      should model the correct behavior its own scorer checks for.

**Verification, this section:** `pytest -m unit`: **139 passed**. `pytest -m integration`
(non-LLM-cost files): **37 passed**, confirmed twice in a row for determinism.

### ✅ 4.2 Behavioral Diff Engine (DONE 2026-07-29)

- [x] Embed final assistant messages per shared case_key, compute per-case cosine similarity
      (real Gemini embedding calls — a separate quota metric from `generate_content`, confirmed
      still available even while `generate_content` was daily-quota-exhausted)
- [x] Four-quadrant classification via pure `_classify_diff()` — `apps/api/services/diff_engine.py`
- [x] Table `behavior_diffs` + migration `0006`. Append-only (unlike `ars_snapshots`) — each
      computation is its own historical record, not upserted
- [x] `POST /diff-runs` + `GET /diff-runs/{id}`, owned by `eval_service` (diffing is eval-logic
      territory — reads `eval_case_results`, calls an embedding model — not registry or gate-policy
      territory). Route ownership table in `.claude/rules/architecture.md` updated
- [x] `agentbench diff <version-a> <version-b> [--suite]` — exits nonzero on `silent_drift` so a CI
      pipeline can gate on it like any other check
- [x] Wired into `drift/runner.py` on every scheduled tick — subsumes the old "behavior drift" item

**A real design bug found via the integration test, not a test-setup mistake:**
`agent_versions` has `UNIQUE(agent_id, content_hash)`, so **any two distinct registered versions
are guaranteed to have different content_hash** — meaning `code_changed` would be `True` on every
comparison between two different version IDs, making `SILENT_DRIFT` and `NO_OP` **structurally
unreachable** through the API as first designed. Caught when the integration test's attempt to
register two versions sharing one content_hash hit the unique constraint directly.

**Fix — split into two DB-backed entry points over one shared primitive:**
- `compute_diff(eval_run_a_id, eval_run_b_id)` — the real primitive, takes eval run ids directly
  (not version ids), which is what makes comparing a version **against its own history** possible
- `compute_diff_for_versions(version_a_id, version_b_id, suite_id)` — the `agentbench diff` /
  `POST /diff-runs` path. Two distinct versions always differ in hash, so only `SAFE_REFACTOR` /
  `EXPECTED_CHANGE` are reachable here — correct, since this answers "was the version bump safe,"
  not "did this version drift on its own"
- `compute_diff_over_time(agent_version_id, suite_id)` — compares a version's two most recent
  completed runs against **itself**. Same row, same content_hash, `code_changed` always `False` —
  only `NO_OP` / `SILENT_DRIFT` are reachable. **This is the actual alarm the scheduler calls**,
  and the only construction that can represent "nobody touched the code" at all
- `drift/runner.py._check_behavior_diff()` rewritten to call `compute_diff_over_time()` instead of
  diffing against the previous registered version, which could never have shown real drift

**Verified for real, not fabricated:** built a third fixture agent
(`tests/unit/fixtures/dummy_agent_drifting.py`) whose output is controlled by a module-level flag
the test flips between two eval runs of the **same** registered `AgentVersion` row — simulating
"the provider changed the model underneath an unchanged agent" honestly, without needing live LLM
non-determinism. `compute_diff_over_time()` on that version's two runs, with real embedding calls
on the two genuinely different sentences, correctly classified `SILENT_DRIFT`. **Negative control**:
hardcoded `behavior_changed = False`, watched 5 tests fail across both the unit and integration
suites, restored, watched them all pass again.

**Bugs found and fixed while verifying (same class as Phase 4.1's, this time in a new file):**
- [x] The `test_diff_engine_end_to_end.py` fixture's teardown deleted `EvalRun` rows without first
      deleting the `ars_snapshots` rows `eval_engine.run_eval()` now creates automatically, **and**
      without checking `behavior_diffs.eval_run_b_id` (only `eval_run_a_id` was filtered) — a
      `compute_diff_over_time()` result can reference either run as `eval_run_b_id`. Both fixed.
      `test_ars_end_to_end.py` and `test_http_adapter_end_to_end.py` audited again — neither creates
      `BehaviorDiff` rows, so neither needed this second fix.

**Tests:** `test_diff_engine.py` (17, pure — cosine similarity + all four quadrants + threshold
boundary), `test_diff_engine_end_to_end.py` (7, real Postgres + real eval engine + real Gemini
embeddings, zero `generate_content` cost).

### ✅ 4.3 Agent Chaos Engineering (DONE 2026-07-29)

- [x] `ChaosAdapter` (`apps/api/services/adapters/chaos_adapter.py`) — satisfies `AgentAdapter`
      **and** wraps one. **Not** zero `eval_engine.py` changes, corrected up front this time (see
      below) rather than discovered later.
- [x] Fault modes: `timeout`, `connection_reset` (total-failure family — real adapter never
      called, session_state left byte-for-byte untouched), `malformed_response`, `plausible_wrong`,
      `latency_injection` (calls-through family — the agent runs for real, only what the eval
      engine sees afterward is altered)
- [x] `chaos:` block in `ExpectationsYAML` (validated `mode`/`probability` at suite-push time, not
      discovered mid-eval-run), plus `recovery_rubric` alongside `judge_rubric`/`safety_rubric`
- [x] `RecoveryScorer` (`apps/api/services/scorers/recovery.py`) — deterministic core (does the
      session keep producing non-empty responses after the last injected fault?) + optional
      `recovery_rubric` LLM-judge escape hatch for the genuinely nuanced "graceful vs confidently
      hallucinated" judgment, which a keyword heuristic can't honestly make either direction
- [x] Reserved marker tool call (`__chaos_fault__`) lets `RecoveryScorer` (and a future dashboard)
      identify chaos-affected turns without text-sniffing, without widening the
      `AgentTurnResult`/`ToolCall` STABLE CONTRACT models

**Corrected the "zero eval_engine.py changes" framing before writing code, not after:** thought
through, before implementing, whether ChaosAdapter could truly avoid touching `eval_engine.py`.
It can't — `ChaosAdapter` must be constructed **per case** (only some cases in a suite configure
chaos), while `build_adapter()` builds one adapter per **run**. Added `_build_case_adapter()` and a
one-line call-site change in the per-case loop. What genuinely doesn't change: the STABLE
CONTRACT — `_run_case()` and every scorer remain unaware whether the adapter they were handed is
wrapped.

**A design question worked through explicitly, not glossed over:** RedLine's `AgentAdapter` is a
deliberate black box (Section 8.1's framework-agnostic architecture) — the eval engine has never
seen inside an agent's own tool-calling logic, and reaching in would mean framework-specific
instrumentation. So ChaosAdapter injects faults at the one boundary RedLine actually controls: the
whole `run_turn()` call. For an `HTTPAdapter`-wrapped deployed agent that boundary is a **real**
dependency (the network) — for a `LocalPythonAdapter`-wrapped local agent there is no real network
to fail, so a fault there is **synthetic**: it still exercises the eval engine's and
`RecoveryScorer`'s handling honestly, but isn't simulating real infrastructure failure for that
agent. Documented as a disclosed scope limitation in `chaos_adapter.py`'s docstring, not left
implicit.

**Tests:** `test_chaos_adapter.py` (17, pure — every fault mode's exact effect, deterministic
`target_turn_indices` selection, seeded-RNG reproducibility for probability-based selection,
session-state-untouched proof), `test_scorers.py` `RecoveryScorer` extensions (6, pure),
`test_chaos_end_to_end.py` (6, real Postgres + real eval engine + zero-cost `dummy_agent`, no LLM
cost needed for the deterministic-core proof). **Negative control**: disabled the
`_build_case_adapter()` call site directly (chaos wrapping skipped entirely), watched 3 of 6
end-to-end tests fail, restored, watched all pass. The session-state-untouched claim is proven
**concretely** in the end-to-end test, not just asserted in `ChaosAdapter`'s own unit tests in
isolation: `dummy_agent` embeds `session_state['turn_count']` in its reply, so the real second turn
reading `turn_count=1` (not `2`) directly demonstrates the faulted first turn never touched state.

### ✅ 4.4 Agent Load Testing (DONE 2026-07-29)

- [x] New topic `load.requested` + `load_worker.py` (separate resource profile from eval runner —
      reuses `RedpandaEvalWorker` with a `topics` param rather than duplicating a parallel consumer
      class, since its consume/commit/status logic was already topic-agnostic)
- [x] p50/p95/p99 latency (nearest-rank, pure `_percentile()`), error rate, cost per hour, throughput
      — all in pure `_compute_load_stats()`, same discipline as every other Phase 4 engine
- [x] **Cost per hour at concurrency** — extrapolated from the actual measured window, not assumed
- [x] ClickHouse `load_samples` table + batched `emit_load_samples()` (one INSERT per run, not per
      sample — a load test can produce thousands of samples, unlike an eval run's ~20 trace events)
- [x] `agentbench load <version-id> --users N --duration Ns` — async job-queue pattern (create row,
      publish, return immediately; CLI polls), matching `agentbench run`, not synchronous like
      `agentbench diff` — a load test can run for minutes, too long to block a request on
- [x] `POST/GET /load-runs`, owned by `eval_service`
- [x] Concurrency via `ThreadPoolExecutor`, **not** asyncio — real OS-thread concurrency without
      violating architectural rule #1. Each virtual-user thread owns its own `session_state`,
      confirmed thread-safe by construction
- [x] Helm `load-worker/` deployment + `ScaledObject` on `load.requested` lag, `minReplicaCount: 0`
      (unlike eval-worker — no reason to hold a pod when no load test is queued). **Not verified
      against a live k3d cluster this session** — flagged honestly below, matching how every other
      Helm addition in this project states its verification status plainly

**A second real bug in existing infrastructure, found because this was the first feature to ever
need it:** `RedpandaJobQueue.publish(tenant_id, job_type, payload)` **always produced to
`topic_eval_requested`, completely ignoring the `job_type` argument.** Every call site before load
testing happened to pass `job_type="eval.requested"` — the one value that coincidentally matched
the hardcoded topic — so this was never caught. `job_type` values were already topic-shaped strings
(`"eval.requested"` is literally the topic name), meaning the parameter was clearly *meant* to
select the topic and simply never did. Fixed with a small `_KNOWN_TOPICS` registry mapping
`job_type` to topic and a `_resolve_topic()` validator that rejects unregistered job types loudly
instead of silently producing to an arbitrary string. `RedpandaEvalWorker` gained a `topics`
parameter (default unchanged, so `eval_worker_v2.py` needed zero edits) rather than a duplicated
consumer class for `load_worker.py` to use.

**Verified for real:**
- Real `ThreadPoolExecutor` concurrency against the real reference HTTP agent: 5 concurrent virtual
  users produced far more than 5 total requests in ~2 seconds, positively confirming the concurrency
  is genuine, not sequential.
- **10,307 real samples** landed in ClickHouse across this session's test runs (confirmed by direct
  query) — found and worked around a **second** instance of the `.claude/settings.local.json`
  env-shadowing issue first discovered in Phase 3.5 (`DATABASE_URL`): the harness also injects
  `CLICKHOUSE_PORT=8123` (the HTTP port) instead of `.env`'s correct `9000` (native protocol port),
  which had been silently breaking every `emit_trace()`/`emit_load_samples()` call all session,
  swallowed non-fatally by design (rule #4) as the harmless-looking `"[trace] write failed
  (non-fatal): ... Unexpected packet from server localhost:8123"` messages visible throughout this
  session's test output. See `docs/status.md`'s Environment Note for the full write-up — this is
  not a code bug and was not touched, since it's personal harness config, not project code.
- The `job_type`→topic routing fix verified against real Redpanda: published to `load.requested`,
  consumed by a worker subscribed **only** to `load.requested` (not `eval.requested`), confirmed the
  existing `eval.requested` path still routes correctly afterward.
- **Negative control**: replaced `_percentile()` with a stub always returning the minimum value,
  watched 2 tests fail (`p50`/`p99` no longer distinct from the minimum), restored, confirmed clean.
- An unreachable agent under load correctly reports `error_rate=1.0` with the run marked
  `"completed"` (not `"failed"`) — the engine only raises for genuine configuration problems, not for
  every virtual user individually failing to reach a dead endpoint.

**Tests:** `test_load_engine.py` (15, pure), `test_load_engine_end_to_end.py` (5, real Postgres +
real Redpanda + real ThreadPoolExecutor concurrency + real HTTP + real ClickHouse writes).

**Follow-up opened by this work:**
- [x] Helm `load-worker` templates are unverified against a live k3d cluster — run `make
      images-build && make helm-upgrade` and confirm the pod actually schedules and scales before
      relying on them in Phase 5's deployment work. **(DONE 2026-07-29, Phase 4.5 cleanup):**
      started the (previously-stopped) local k3d cluster — its loadbalancer port conflicted with an
      unrelated container on this machine, recreated on port 8090 (`Makefile`'s `cluster-up`
      updated). Ran `helm-install`/`images-build`/`images-import`, confirmed `load-worker` schedules,
      reaches `Running`, and its `load-worker-scaledobject` KEDA `ScaledObject` reports `READY: True`
      with a live Kafka trigger actually querying consumer lag (not just rendering — this needed the
      Bug 2 Redpanda fix above to work at all, since KEDA's trigger has to reach the same broker).
- [x] `docs/http-agent-contract.md` doesn't yet mention that a deployed agent under load testing
      needs to handle real concurrent requests safely (thread-safety on the agent's own side) —
      worth a short addition once a real third-party agent actually gets load-tested.
      **(DONE 2026-07-29, Phase 4.5 cleanup):** added a "Concurrency and thread-safety" section
      covering `ThreadPoolExecutor`-based real concurrency, shared-mutable-state hazards, and why an
      accidentally-single-threaded agent framework will silently serialize through a load test
      rather than error.

### ✅ 4.5 Production Failure Mining (DONE 2026-07-29)

*The fifth and final novelty feature — all five are now built.*

- [x] `mine_failures()` embeds every completed eval result's final assistant message across an
      agent's **entire** history (every suite, every version — not just one suite's cases) and
      clusters via **scikit-learn's DBSCAN** on a precomputed cosine-distance matrix. Chosen
      deliberately over a hand-rolled clustering routine: this is explicitly "the actual machine
      learning component of the platform" per the foundational doc, and hand-rolling the math for a
      feature whose entire point is being real unsupervised ML would undercut the claim. DBSCAN also
      naturally produces a noise label (-1) for outliers, unlike k-means, which matters when you
      don't know the number of failure modes in advance.
- [x] Correlate clusters with bad outcomes — a case result's own `passed` field (every configured
      scorer's AND), the same signal the gate engine already uses for pass_rate. Pure
      `_identify_significant_clusters()` filters to clusters meeting both a minimum size (a real
      recurring pattern, not two coincidentally similar responses) and a minimum bad-outcome rate (a
      genuine failure mode, not just a common topic that mostly passes)
- [x] Each significant cluster becomes one `CandidateCase` — a `judge_rubric` naming the pattern and
      the representative bad response, copied `turns` from the representative case — status
      `pending`, never auto-trusted into a real suite
- [x] `POST /mining/{agent_id}/run`, `GET /mining/candidates`, `POST .../approve`,
      `POST .../reject` — approving promotes a candidate into a genuine `EvalCase` in an
      auto-created `mined-failures` suite, closing the loop the foundational document names:
      "production traffic makes the test suite smarter over time," approval as a deliberate,
      separate action, never a side effect of mining itself
- [x] `agentbench mine <agent-id>`, `candidates-list/-approve/-reject`
- [x] Tables `failure_clusters` (append-only, like `drift_snapshots`/`behavior_diffs`) and
      `candidate_cases` (migration `0008`)
- [x] Added `scikit-learn==1.7.2` to both `apps/api/requirements.txt` and `pyproject.toml`'s
      `[api]` extra — the packaging test (`test_packaging.py`) that keeps these two in sync stays
      green, confirming the CLI's dependency footprint is untouched

**Refactor done along the way, not scope creep:** `diff_engine.py`'s `_embed_texts()` was about to
become a *third* copy of the same embedding-call logic. Extracted to
`apps/api/services/embeddings.py` (`embed_texts()`), used by both `diff_engine.py` and
`mining/engine.py`. Re-verified `diff_engine`'s existing live-embedding integration tests still pass
unchanged after the extraction — behavior preserved exactly, duplication removed.

**A real bug caught by the integration test, not by inspection:** `mine_failures()` originally
returned `list[FailureCluster]` — **raw ORM objects** — breaking the pattern every other Phase 4
engine follows (pure dataclass/Pydantic results, never ORM instances). The function's own
`finally: db.close()` runs before the value reaches the caller, so any attribute access after
return raised `DetachedInstanceError`. Fixed with a new `MinedCluster` dataclass, its fields
captured as plain values before the session closes — exactly the discipline `ars_engine`,
`diff_engine`, and `load_engine` already followed, which this one had briefly missed.

**Verified for real, not by construction:** four genuinely different sentences ("I'm sorry, we
cannot process a refund...", "Unfortunately, refunds are not possible...", etc. — not identical
strings) expressing the *same* recurring failure were correctly clustered together by real Gemini
embeddings + real DBSCAN, while three unrelated, mutually dissimilar passing responses were correctly
excluded. **Negative control**: hardcoded `bad_outcome_rate = 1.0` regardless of actual outcomes,
watched 3 unit tests fail, restored, confirmed clean.

**Tests:** `test_mining_engine.py` (16, pure — DBSCAN behavior on synthetic vectors, significance
filtering on synthetic labels), `test_mining_engine_end_to_end.py` (5, real Postgres + real Gemini
embeddings + real clustering + the approve workflow promoting a real `EvalCase`).

**Follow-up opened by this work:**
- [ ] "Production traces" is honestly scoped to *eval-run* traces — there is no live
      production-traffic ingestion pipeline yet. A real one (ingesting actual deployed-agent
      traffic, not just eval runs) is Phase 5+ work; `mine_failures()` mines what already exists.
- [ ] `DEFAULT_DBSCAN_EPS = 0.15` and `DEFAULT_MIN_BAD_OUTCOME_RATE = 0.5` are starting defaults,
      not empirically calibrated — same honesty as `diff_engine.DEFAULT_SIMILARITY_THRESHOLD`. No
      labeled corpus of "genuinely the same failure" vs. "coincidentally similar wording" exists yet
      to tune against.

---

## 🔮 Phase 5 — Hardening, Deployment & Launch

### Deferred infrastructure (was old Phase 3)

**Phase 5.1 (infra hardening, local-only) — DONE 2026-08-02, see `docs/infra-hardening.md`:**
- [x] Grafana Tempo — `OTLPSpanExporter` replaces `ConsoleSpanExporter` (`apps/api/core/telemetry.py`),
      new `tempo` docker-compose service, verified live with a real span landing in Tempo's query API
- [x] Dead-letter queue for repeatedly-failing eval jobs — `RedpandaEvalWorker.retry_or_dead_letter()`,
      retry-count in the message envelope (not a `Job` column), `<topic>.dead-letter` topics, 5 unit
      tests, wired into both `eval_worker_v2.py` and `load_worker.py`
- [x] PgBouncer — opt-in (`DB_USE_EXTERNAL_POOLER`), `NullPool` when active, verified live via psql
      through the pooler and via SQLAlchemy with a real query
- [x] ClickHouse least-privilege user — `redline_app` (SELECT/INSERT only) replaces `default`
      (superuser) as the app-runtime identity; verified live that SELECT succeeds and CREATE TABLE
      is denied; required a real container config fix (`access_management` grant for bootstrap
      `default`) discovered while implementing, not just asserted
- [x] `JWT_SECRET_KEY` rotation procedure, documented (runbook only, no code change — verified the
      refresh-token path never calls `jwt.decode`, so rotation blast radius is access-tokens-only)
- [ ] mTLS between services — explicitly deferred to Phase 5.4 (public deployment), documented gap
      in `docs/infra-hardening.md`, not silently dropped

**Still deferred (not part of this pass):**
- [ ] Async workers v3 — `eval_worker_v3.py` **alongside** v2, never replacing it
      (rule #2: justify why sync is insufficient first — 4.4 load testing will produce the answer)
- [ ] Google OIDC — `POST /auth/google/callback`; token issuance/rotation/RBAC unchanged
- [ ] Suite registry — `agentbench pull <suite-name>`

### Platform CI/CD (§10.8) — DONE 2026-08-02

- [x] push → unit + integration tests → build image → **Trivy scan** → GHCR with immutable tag →
      `helm upgrade` → health check → automated rollback — `.github/workflows/ci.yml`, 4 jobs
      (`unit-tests`, `integration-tests`, `build-scan`, `deploy`). Prerequisite fix: all 5 Helm
      deployment templates hardcoded `image: "redline-<svc>:latest"`, ignoring `values.yaml`'s
      already-present `image.registry`/`image.tag` — now templated
      (`{{ .Values.image.registry }}redline-<svc>:{{ .Values.image.tag }}`), verified via
      `helm template` with both default and `--set image.tag=...` overrides rendering correctly.
      `--atomic` added to `make helm-install`/`helm-upgrade` (Helm's built-in rollback-on-failed-wait,
      safer than a hand-rolled `helm rollback` step). `deploy` job is correct and complete but
      **inert until a `KUBE_CONFIG` secret + reachable cluster exist** (Phase 5.4, deferred) —
      stated plainly in the workflow's own header comment.
- [x] `pip-audit` for dependency CVEs — wired into `build-scan`, non-blocking initially (`|| true`);
      verified live: correctly surfaces 17 known findings across 5 packages (`python-jose`,
      `starlette`, `pytest`, `click`, `ecdsa`) already present in this codebase, confirming the
      non-blocking-until-triaged design was the right call rather than immediately gating merges
      on pre-existing, known findings.

**Verified live (this machine, real Docker/Postgres/Redis/Redpanda/ClickHouse, not just YAML
syntax review):** `pip install -e ".[api,dev]"` in a fresh venv, `pytest -m unit -q` in that same
fresh venv (219 passed), a real `docker build` of `eval_service` with the container then confirmed
to import `apps.api.core.telemetry` correctly, and the exact integration-job command sequence
(`alembic upgrade head` → `init_topics` → `init_clickhouse` → `push_suite` →
`register_agent_version`) run against real local infra with the workflow's exact env vars — this is
also what caught a real bug before it reached CI: the integration job's env block was missing
`CLICKHOUSE_ADMIN_USER`/`CLICKHOUSE_ADMIN_PASSWORD`, which `init_clickhouse()` now requires
separately from the app's `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` (Phase 5.1's least-privilege
change) — fixed and re-verified.

### Dashboard v2 — one high-quality rewrite (ADR-006)
- [ ] Vite + React + TypeScript + TanStack Query + Tailwind + shadcn/ui + Recharts
- [ ] `openapi-typescript` codegen in CI — a backend response-model change breaks the frontend build
- [ ] Auth (login + refresh rotation), replacing today's unauthenticated `fetch()`
- [ ] Pages: ARS trend, behavioural diff viewer, chaos results, load report, failure clusters,
      drift alerts, ClickHouse trace viewer
- [ ] Retire the current 546-line JS app

### Public deployment (ADR-005)
- [ ] Helm chart deploys unchanged to k3d **and** to the public cluster — no application changes
- [ ] Primary: Oracle Cloud always-free ARM VM + k3s. Fallback: managed Kubernetes
- [ ] Provider selected **after** Phase 4, once the load-runner/trace-worker resource profile is known

### Proof of value (§12, §14) — DONE 2026-08-02

- [x] Manual vs RedLine failure-count comparison across the three benchmark agents, real numbers —
      `docs/proof-of-value.md`. Level 1: pass_rate 0.67, gate FAIL. Level 4: pass_rate 0.50, gate
      FAIL, 3/6 cases failed on real scorer findings + an ARS error-budget breach. Level 3:
      re-attempted live 2026-08-02, still genuinely blocked on a real Gemini free-tier daily quota
      (20 req/day for `gemini-3.5-flash`) — reported honestly, not forced past.
- [x] `EXPLAIN ANALYZE` index before/after on `(tenant_id, created_at)` — migration `0010`,
      `docs/explain-analyze-eval-runs-index.md`. Real captured output at 150,000 rows (synthetic,
      cleaned up after capture): Seq Scan 62.4ms → Index Scan Backward 0.6ms, ~102x.
- [x] k6 load test of RedLine's own API — p95 under N concurrent eval triggers —
      `scripts/k6/eval_trigger_load.js`, `make k6-load-test`. Real result at 10 VUs/30s: 4,032
      requests, 0.00% error rate, p95=116.8ms, 134.1 req/s. Unplanned but honestly disclosed finding:
      a live k3d `eval-worker` pod picked up the queued jobs this generated (shares the same
      Redpanda broker) and attempted real processing rather than leaving them harmlessly pending —
      noted in `docs/proof-of-value.md` rather than silently cleaned up and unmentioned.
- [x] Recorded demo: a PR actually blocked by the gate, with the gate's reasoning visible —
      `docs/ci-demo.md` gained a new section quoting the real, post-Phase-4 Level 4 gate verdict
      (ARS/error-budget-aware reasoning, not available when the original PR #2 transcript was
      captured). **The written walkthrough is done; an actual screen recording is a remaining
      manual user action** — see `docs/ci-demo.md` for the ~2-minute instructions.

---

## ✅ Completed (Phase 1 + Phase 2)

- [x] Core eval loop (`run_eval` → scorers → `gate_engine`)
- [x] STABLE CONTRACT (`publish`/`get_status`) across Postgres and Redpanda implementations
- [x] JWT + API key dual auth with RBAC
- [x] Refresh token rotation with reuse detection
- [x] Level 1 RAG agent (TrailLight Gear) with 3 eval cases
- [x] LLM judge scorer (Gemini-as-judge)
- [x] Gate engine with pure `_compute_gate_result()`
- [x] GitHub Actions CI blocking PR merge on gate failure (PR #2)
- [x] React dashboard v1 (3 pages, gate verdict banner) — to be replaced in Phase 5
- [x] Unit + integration test suites
- [x] Redis rate limiting, distributed locks, job status cache
- [x] Redpanda event bus with consumer-group worker
- [x] ClickHouse trace analytics (`emit_trace`, non-fatal)
- [x] OTel spans wrapping eval runs and cases
- [x] Prometheus metrics
- [x] APScheduler drift detection (model drift only)
- [x] k3d Kubernetes deployment with Helm chart
- [x] KEDA `ScaledObject` on Redpanda consumer lag
- [x] Level 3 + Level 4 agents BUILT (not yet gate-verified)
- [x] Model profiles (`config/model_profiles.yaml`) — rag_agent still non-compliant, see Bug 3
- [x] ADRs 001, 003 documented; 005, 006 added 2026-07-29
- [x] ~~Bug 4 — verify `enable.auto.commit`~~ **Not a bug.** Verified 2026-07-29:
      `redpanda_queue.py:60` sets `"enable.auto.commit": False`; `eval_worker_v2.py:60` commits only
      after processing. At-least-once semantics are correct as built.
