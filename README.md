# RedLine — Agent Reliability Engineering

RedLine (the AgentBench Cloud platform) treats AI agents like real software systems
that need real software engineering discipline: automated evaluation, CI/CD
deployment gates, and — starting in Phase 4 — reliability scoring, behavioural diff
detection, chaos engineering, and load testing borrowed directly from Site
Reliability Engineering.

The gap it fills: tools like LangSmith, Langfuse, and Braintrust answer "what
happened?" and "did this score well?" Very few of them **physically block** a bad
agent from shipping the way a failing CI check blocks a bad commit. That's what
RedLine does — and unlike LLM output, an agent is non-deterministic, multi-step, and
its behaviour can drift silently underneath you when a provider updates a model.
Manual spot-checking doesn't catch that. An enforced gate does.

See [`AgentBench_Cloud_Foundational_Document-2.md`](AgentBench_Cloud_Foundational_Document-2.md)
for the full thesis, and [`docs/architecture-roadmap.md`](docs/architecture-roadmap.md)
for what's built versus what's next.

---

## What exists today

| Phase | Status | What it means |
|---|---|---|
| 1 — Core eval loop | ✅ Complete | `run_eval()` → scorers → gate, single-machine |
| 2 — Distributed infrastructure | ✅ Complete | Redpanda, Redis, ClickHouse, k3d + KEDA, OTel |
| 3 — Foundation close-out | ✅ Complete | Real tenant isolation, `HTTPAdapter`, Redis-backed rate limiter, installable CLI |
| **4 — Reliability engineering** | ✅ **COMPLETE** | **ARS, behavioural diff, chaos engineering, load testing, failure mining** |
| 5 — Hardening & launch | ⏳ Not started | Async workers, OIDC, public deployment, dashboard v2 |

**What makes RedLine different from LangSmith/Braintrust is now fully implemented:**

1. **Agent Reliability Score (ARS)** — Composite reliability metric (0.4×correctness + 0.2×safety + 0.2×latency + 0.2×cost) with SLO/error-budget tracking that gates deployments
2. **Behavioral Diff Engine** — Semantic embedding comparison that detects "silent drift" when models change but code doesn't
3. **Production Failure Mining** — DBSCAN clustering auto-generates regression tests from production failures
4. **Agent Chaos Engineering** — Fault injection (timeouts, malformed responses, wrong data) to test resilience
5. **Agent Load Testing** — Concurrent user simulation with p50/p95/p99 latency and cost-per-hour metrics

See [`DEPLOYMENT_AND_DEMO_GUIDE.md`](DEPLOYMENT_AND_DEMO_GUIDE.md) for complete setup instructions and demos of all 5 features.

---

## Architecture

```
                         ┌──────────────────────────────────┐
                         │  nginx gateway (8085 / k3d :8000) │
                         └──────┬──────────┬──────────┬──────┘
                                │          │          │
               ┌────────────────▼──┐  ┌────▼──────┐  ┌▼──────────────┐
               │  eval_service     │  │agent_svc  │  │gate_service   │
               │  :8001            │  │:8002      │  │:8003          │
               │  /eval-runs /ci   │  │/agents    │  │/dashboard     │
               │  /auth            │  │/eval-suites│ └───────────────┘
               └────────┬──────────┘  └─────┬─────┘
                        │                   │
               ┌────────▼───────────────────▼────────────────┐
               │              PostgreSQL :5433                │
               │   tenants · agents · eval_runs · gate_policies│
               └────────┬───────────────────┬──────────────────┘
                        │                   │
               ┌────────▼────────┐  ┌───────▼────────┐
               │  Redpanda :19092│  │  Redis :6379   │
               │  eval.requested │  │  rate limits,  │
               │  consumer group │  │  locks, cache  │
               └────────┬────────┘  └────────────────┘
                        │
               ┌────────▼────────┐  ┌────────────────┐
               │  eval_worker_v2 │  │  ClickHouse    │
               │  (KEDA-scaled)  │  │  :8123 traces  │
               └─────────────────┘  └────────────────┘
```

Three benchmark agents exercise the platform end to end:

- **Level 1 — `rag-agent`**: retrieval-augmented customer support, tests grounded
  answers and honest "I don't know" refusal over hallucination.
- **Level 3 — `stateful-support-agent`**: multi-turn memory across 7 failure
  categories (entity, preference, constraint, correction, repeated-question,
  context accumulation, topic continuity).
- **Level 4 — `research-pipeline-agent`**: a multi-agent workflow, where one agent's
  small error compounds across the chain.

An agent under test can be **either** a Python function RedLine imports directly, or
a deployed HTTP endpoint — see [`docs/http-agent-contract.md`](docs/http-agent-contract.md)
and the runnable reference implementation at
[`examples/http-agent/server.py`](examples/http-agent/server.py). RedLine never needs
your source code; it needs one endpoint.

---

## Quickstart

**Requirements:** Docker, Python 3.10+, Node 18+ (dashboard only).

```bash
# 1. Infrastructure
docker compose up -d

# 2. Schema, seed data, topics, ClickHouse schema
alembic upgrade head
python -m apps.api.scripts.seed
python -m apps.api.scripts.create_api_key        # save the printed key as $API_KEY
python -m apps.api.scripts.init_topics
python -m apps.api.scripts.init_clickhouse

# 3. API server (Terminal 1)
python -m uvicorn apps.api.main:app --port 8000

# 4. Eval worker (Terminal 2)
python -m apps.api.workers.eval_worker_v2

# 5. Install the CLI (talks to the API over HTTP only — no DB driver required)
pip install -e .
```

```bash
# 6. Point RedLine at an agent and run it
agentbench login --base-url http://localhost:8000 --api-key "$API_KEY"
agentbench init --agent rag-agent --entrypoint agents.rag_agent.agent:run_turn
agentbench push-suite eval-suites/rag-agent/baseline.yaml
agentbench register-version --version-label v1 --model gemini-2.0-flash
agentbench run --suite baseline
```

That last command runs the eval suite, computes pass/fail per case, and evaluates the
agent's gate policy — the same mechanism that blocks a pull request in CI. See
[`docs/ci-demo.md`](docs/ci-demo.md) for the recorded example of a PR actually blocked
by a failing gate.

**Full setup, including k3d/Helm and the monitoring stack:** [`checkpoint.md`](checkpoint.md).

---

## Bring your own agent

You do not need to write Python or import any RedLine code. Stand up one HTTP
endpoint matching the contract in
[`docs/http-agent-contract.md`](docs/http-agent-contract.md):

```bash
python examples/http-agent/server.py     # reference implementation, listens on :9100

agentbench register-version \
    --version-label v1 --model my-model \
    --entrypoint http://localhost:9100/turn \
    --content-hash "$(git rev-parse HEAD)"
```

RedLine selects the HTTP adapter automatically from the URL scheme — the eval engine,
every scorer, and the gate never know the difference between a local agent and a
remote one.

---

## Running the tests

```bash
pytest -m unit           # ~100 tests, no external services, seconds
pytest -m integration     # needs docker compose (Postgres, Redis, Redpanda)
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the architectural rules every change is
checked against, and for how to file an ADR when a decision is worth recording.

---

## Project layout

```
apps/
  api/            control-plane: routers, models, services, migrations, tests
  cli/            the `agentbench` CLI — talks to the API over HTTP only
  eval_service/   eval_service    the routers/agent_service/gate_service Dockerfiles
  agent_service/  agent_service   (service decomposition, Phase 2)
  gate_service/   gate_service
  dashboard/      React dashboard (v1 — see ADR-006 for the planned rewrite)
agents/           benchmark agents under test (rag-agent, stateful-support, research-pipeline)
config/           model_profiles.yaml — the only place model names are declared
eval-suites/      YAML eval suites per benchmark agent
examples/         reference HTTP agent implementation
docs/             architecture roadmap, ADRs, status, the HTTP agent contract
helm/             Kubernetes deployment (k3d locally, the same chart in production)
```

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
