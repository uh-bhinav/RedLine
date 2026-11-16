## AgentBench Cloud

## An Agent Reliability Engineering Platform

## Foundational Project Document — v1.0

Purpose of this document: This is the single source of truth for the project. Every design decision, every "why," every phase, every missing piece of technical depth lives here. If you forget why you built something a certain way six months from now, this

document should answer it.

## 1. Executive Summary (Abstract)

AI agents — software that uses LLMs to reason, call tools, retrieve data, and take multi-step actions — are moving from demos into production. But the tooling to make them production-safe has not caught up. Teams ship agents the way web developers shipped code in the 1990s: manually, with a handful of eyeballed test cases, and a prayer that the next prompt change doesn't break something three steps downstream. AgentBench Cloud is a cloud-native platform that treats AI agents like real software systems that need real software engineering discipline: automated testing, CI/CD deployment gates, load testing, production monitoring, and — critically — a feedback loop where real-world failures automatically become new regression tests. The closest existing tools (LangSmith, Langfuse, Braintrust, Arize, Confident AI, Agent CI, Azure AI Foundry) are strong at observability ("what happened?") and evaluation ("did this score well?"). AgentBench's differentiation is borrowing directly from Site Reliability Engineering (SRE) — the discipline that runs Google, Netflix, and every serious cloud company — and applying it natively to agents: SLOs, error budgets, chaos engineering, canary releases, and hard deployment gates that physically block a bad agent from shipping. This document is both a pitch (why this is worth building) and a blueprint (exactly how to build it, and why each technical choice was made), written so that someone with zero prior context can read

it and understand the entire system.

## 2. Problem Statement

## 2.1 The core problem

LLM-based agents are non-deterministic, multi-step, and compounding. A single agent call

might:

- 1. Receive a user message

- 2. Decide which tool to call

- 3. Call that tool (which might fail, time out, or return unexpected data)


- 4. Reason about the result 5. Decide whether to call another tool 6. Generate a final response

Each of these six steps can independently fail or drift in subtle ways. Traditional software testing assumes determinism: same input → same output. Agents break that assumption. A prompt change, a model version bump, or a tool's API contract changing can silently degrade agent behavior in ways that unit tests never catch — because there usually are no unit tests for "did the

agent reason correctly."

## 2.2 Why this is getting worse, not better

- Companies are shipping agents into customer support, coding assistants, financial workflows, and operations — domains where a bad output has real cost (refunding the wrong amount, leaking data, giving wrong medical/legal-adjacent advice).

- Models update underneath teams (a new GPT/Claude/Gemini version can change agent behavior without anyone touching the agent's code).

- Multi-agent systems (agents calling agents) multiply the failure surface - one agent's small error compounds across the chain.

- Most teams currently catch these failures in production, from angry users, not before deployment.

## 2.3 The specific gap

The existing tools listed above (covered in detail in Section 4) are mostly post-hoc observability and scoring tools. They tell you what happened after it happened, or give you a quality score if you

remember to run an eval. Very few:

- Physically block a deployment the way a failing CI pipeline blocks a bad commit.

- Treat production failures as a source of new tests automatically (failure mining), instead of a human writing new test cases by hand.

- Apply chaos engineering - deliberately breaking a dependency to see if the agent degrades gracefully.

- Give agents an SLO/error-budget model the way SRE teams run infrastructure.

- Load-test an agent the way k6/JMeter load-test an API, with agent-specific metrics (cost per request under load, tool failure rate under concurrency, not just latency).

That gap — agent reliability engineering, not just agent evaluation — is what AgentBench Cloud exists to fill.

## 3. Vision

Long-term vision: AgentBench Cloud becomes the GitHub-Actions-plus-Datadog equivalent for AI agents — the default layer every team installs between "agent code"


and "agent in production," regardless of which framework (LangChain, LangGraph,

CrewAI, raw API calls) they built it with.

Near-term vision (yours, concretely): Build a working, open-source, framework-agnostic platform

that:

- 1. You can run entirely on your Mac M2 during development. 2. Demonstrates real distributed-systems engineering (not a toy CRUD app) — this is the

- resume/portfolio differentiator. 3. Is good enough, real enough, and documented enough that other developers would actually install it on their own agents. 4. Can be deployed cheaply (free-tier cloud) once you want public users, without a rewrite.

The guiding design principle throughout this document: build for production-grade enterprise usability from day one, even while running it locally as a simulation. That means we don't take shortcuts that would later require a rewrite (e.g., no hardcoded single-tenant assumptions, no skipping auth "for now"). We can run a smaller, lighter version of each technology locally (this is explained component by component in Section 9), but the architecture and contracts stay enterprise-shaped from the start.

## 4. Research: Existing Systems & Gap Analysis

This space is moving fast (2025–2026), driven by the industry-wide shift from "LLM apps" to "autonomous agents." Below is a survey of the closest existing systems, what they're good at, and

where they stop short of full agent reliability engineering.

Tool

LangSmith (LangChain)

Execution tracing, dataset- based evals, comparing prompt/model versions, cost & latency tracking

Langfuse

Open-source tracing, sessions, prompt management, framework-agnostic

Braintrust

Strong CI/CD integration (GitHub Actions, PR comments, score-based gates), custom scorers, experiments

Arize AI (+ Phoenix OSS)

OTEL-based tracing, agent session evals, drift detection, enterprise scale

What it's actually good at

Where it stops

Mostly "what happened" visibility; quality decisions stay manual; no hard deployment gate or infra-style blocking; tightly coupled to

LangChain/LangGraph

Observability-first; CI integration is partial; no deployment gating or agent- specific load testing

Closest competitor on the CI/CD side, but lighter on infra depth (no Kubernetes-native scaling, no chaos engineering, no agent load testing as a primitive)

Evaluation/observability- centric; CI exists but isn't built around hard deployment


| Tool | What it's actually good at | Where it stops |
| --- | --- | --- |
|   |   | blocking |
| Confident AI (DeepEval) | Research-backed eval metrics | Lighter on full production |
|   | (G-Eval etc.), pytest-style CI | platform (tracing/monitoring |
|   | integration, red-teaming | secondary); not infrastructure- |
|   |   | heavy |
| Agent CI | Explicit "CI for agents" — Git- | Conceptually closest match to |
|   | style versioning, automated | AgentBench; less mature; |
|   | eval gates, branch protection | unclear depth on multi-tenant |
|   |   | production architecture |
| Microsoft Azure AI Foundry | Enterprise-grade lifecycle | Locked into Azure's ecosystem; |
| (Agent Service) | management, CI/CD via | not framework- or cloud- |
|   | GitHub Actions/Azure DevOps | agnostic |
| MLflow, Phoenix OSS, generic | Useful building blocks | None of them combine |
| GitHub-Actions-plus-evals |   | reliability engineering + |
| setups |   | deployment gating + production |
|   |   | feedback loops as a single |
|   |   | product |

## 4.1 What the gap actually is

Almost every tool above does tracing + evaluation + some CI reasonably well. Very few do, as first-class primitives:

- Hard deployment gates (not "here's a score," but "this build is physically blocked from shipping")

- Kubernetes-native, queue-based horizontal scaling for evaluation workloads

- Agent-specific load testing (concurrent users hammering an agent, not just an API)

- Automatic production  test feedback loops (mining real failures into new regression tests, without a human writing them)

- Multi-tenant, enterprise-shaped architecture as a foundation, not an afterthought

## 4.2 Conclusion of the research

AgentBench Cloud is not inventing a new category from nothing — it's correctly positioned as the SRE layer for agents, sitting one level below evaluation tools (which answer "did this score well") and one level above raw observability tools (which answer "what happened"). The validated niche is: continuous reliability validation + enforced deployment safety + closed-loop production learning, applied specifically to the non-deterministic, multi-step nature of agents.

## 5. Novelty — What Makes This Different

Five features, in order of how differentiating they are, each explained with why it matters and how it would work:


## 5.1 Agent Reliability Score (ARS) + SLO/Error-Budget Model

Why: Borrowed directly from SRE. Instead of a vague "is this agent good," you get one composite, trackable number, plus the SRE concept of an error budget — a quota for how much unreliability is acceptable before you freeze deployments and force a fix.

ARS = 0.4(correctness) + 0.2(safety) + 0.2(latency) + 0.2(cost)

Each sub-score is itself measurable (correctness from eval datasets, safety from guardrail violations, latency/cost from traced runs). The point isn't the exact formula — it's that reliability becomes one number you can gate a deployment on, the same way "99.9% uptime" gates infrastructure

decisions.

## 5.2 Behavioral Diff Engine

Why: git diff shows you code changed. It tells you nothing about whether the agent's behavior changed. A prompt edit that looks like one word can flip "refund: approved" to "refund: denied." How: Run the same test suite against the old and new agent version, embed both sets of outputs, and compute semantic distance — surfacing behavioral diffs even when the code diff looks trivial, and catching cases where code changed but behavior is identical (safe) vs. code didn't

change but behavior drifted (e.g., underlying model was silently upgraded).

- 5.3 Production Failure Mining

Why: Today, new test cases come from a human noticing a bug. That doesn't scale, and it's reactive. How: Continuously embed production traces, cluster them (unsupervised clustering on embeddings), and flag clusters that correlate with bad outcomes (low user ratings, retries, escalations, guardrail trips). Each significant cluster becomes a candidate regression test automatically. This is the actual machine-learning component of the platform, not just LLM-as-

judge scoring.

## 5.4 Agent Chaos Engineering

Why: Netflix's Chaos Monkey proved that deliberately breaking things in a controlled way is the only honest way to know if a system is actually resilient. Agents depend on tools, APIs, retrieval systems, and memory — all of which fail in production constantly, and almost no one tests how the agent behaves when they do. How: A controlled fault-injection layer that can, on command, make a tool API time out, return malformed data, or return a plausible-but-wrong result — then score the agent's recovery behavior (does it retry sensibly, degrade gracefully, or hallucinate a confident wrong answer?).

## 5.5 Agent Load Testing

Why: k6/JMeter load-test APIs on latency and error rate. Nobody load-tests agent cost and tool- failure rate under concurrency — and cost is often the metric that kills an agent in production (an agent that's fine at 10 users can become financially unviable at 10,000). How: agentbench load --users 10000 spins up simulated concurrent sessions against the agent and reports p50/p95 latency, failure rate, and cost per hour at that concurrency — a metric none of the competitor tools surface as a first-class number.


## 6. Objectives

- 1. Build a framework-agnostic platform that can wrap any agent (LangChain, LangGraph, CrewAI, raw OpenAI/Anthropic SDK calls) without requiring the agent to be rewritten.

- 2. Provide automated, repeatable evaluation that runs the same way every time (solving the "it worked when I tried it manually" problem).

- 3. Provide a real CI/CD integration that can block a deployment based on quality, cost, and safety thresholds — not just report a score.

- 4. Demonstrate genuine distributed-systems engineering: an event-driven, horizontally- scalable, multi-tenant architecture — not a single FastAPI monolith with a database.

- 5. Close the loop: production traffic should make the test suite smarter over time, automatically.

- 6. Ship something real enough to open-source, document well enough that strangers can adopt it, and deployable cheaply enough that you can actually host a public demo.

## 7. Deliverables

- CLI tool (agentbench) - init project, run evals locally, run load tests, trigger CI checks.

- Control plane API - project/tenant management, policy/gate configuration, experiment tracking.

- Distributed worker fleet  evaluation runners, LLM-judge workers, load-test runners, trace processors.

- Dashboard (web UI) - see eval results, behavioral diffs, ARS trend over time, production failure clusters.

- CI/CD integration (GitHub Actions first) - a check that goes green/red on a pull request based on configured gates.

- Three benchmark agents (RAG chatbot, single tool-calling agent, multi-agent workflow) used to prove the platform actually catches real regressions, with a documented before/after (e.g., "manual testing found 5 failures; AgentBench found 47").

- This document, kept up to date, as the living architecture record.

- Public docs / README good enough for outside contributors, once open-sourced.

## 8. Scope

## 8.1 In scope (the actual platform)

- Agent-agnostic evaluation engine (works via SDK/API instrumentation, not framework- specific hooks)

- Deployment gating tied into CI


- Multi-tenant control plane

- Event-driven, horizontally scalable evaluation/load-testing workers

- Observability stack (metrics, logs, traces)

- The five novelty features in Section 5

- Local-first development on Mac M2, with a clear, non-rewrite path to cloud deployment

## 8.2 Out of scope (at least for v1)

- Building your own LLM or fine-tuning models - AgentBench evaluates agents, it doesn't build them.

- A no-code agent builder - there are already many of those; AgentBench is the reliability layer that sits next to whatever builds the agent.

- Supporting every agent framework on day one  start framework-agnostic at the SDK/API level (any agent that can be called via HTTP or Python function), add deeper native integrations (e.g., LangGraph-specific tracing) later.

- Full enterprise SSO/SAML on day one ‐ start with OAuth2/OIDC + JWT + RBAC (Section 10.2), which is the 90% case; SAML/enterprise IdP integration is a later add-on once there's real enterprise demand.

## 9. System Architecture

## 9.1 Why not a monolith

A single FastAPI app with one database is the easy answer, but it teaches you almost nothing about how production systems at scale actually work, and it won't survive the workload pattern this product has: bursty, parallel, long-running evaluation jobs that need to scale independently from the lightweight API that triggers them. The architecture below is deliberately a real (if appropriately small) microservices system.

## 9.2 High-level diagram


- 9.3 Component-by-component explanation (the "why" for each)

API Gateway — single entry point; handles auth, rate limiting, and routing to control-plane services. Why: you never want every internal service individually exposed to the internet; the gateway is the one thing that's public. Control Plane services (Project, Policy/Gate, Eval, User/Auth, Experiment) — each is a separate, independently deployable service responsible for one thing (classic microservices "single responsibility"). Why separate them: Policy/Gate logic changes far less often than Eval logic; you don't want to redeploy your entire backend every time you tweak an evaluation metric. It also means each can scale independently — the Eval Service might need many replicas under load; the User/Auth Service rarely does. Event Bus (Kafka-compatible) — when a developer triggers "run eval suite," that request shouldn't make the API wait 10 minutes for results. Instead, the API publishes an event (eval.requested) and immediately returns a job ID. Why Kafka-style (not just a simple queue): you get consumer groups (multiple worker types can independently subscribe to the same event stream), partitioning (so a noisy tenant doesn't block another tenant's jobs from being picked up), and replay (you can reprocess events if a worker bug is fixed later) — none of which a basic queue gives you. Worker Pools (Eval Runner, Load Runner, Trace Worker, LLM-Judge Worker) — these consume events and do the actual heavy lifting (calling the agent under test, scoring outputs, simulating concurrent load, processing trace data). Why separate worker types rather than one generic worker: an LLM-judge call (waiting on another LLM's response) has a completely different resource profile than a load-test worker (needs to fire many concurrent requests) — separating them means each can be scaled and tuned independently, and a slow judge call never blocks load-test throughput. Storage layer (Postgres + ClickHouse + Redis) — three different databases because they solve three different problems (explained fully in Section 10.6: Database Engineering). Short version: Postgres for relational, transactional metadata (tenants, users, configs); ClickHouse for the firehose of trace/event data (millions of rows, analytical queries); Redis for anything that needs to be fast and ephemeral (cache, locks, rate-limit counters, live job status). Observability stack — without this, you cannot debug a distributed system. The three pillars (metrics, logs, traces) are industry standard for a reason: metrics tell you something is wrong (latency spiked), traces tell you where (which service, which span), logs tell you why (the actual

error message).


## 9.4 Scaling model: horizontal vs vertical vs replication

This project intentionally uses all three, in the right place, because that distinction is itself a core

learning objective:

- Horizontal scaling (add more identical instances) - used for the API Gateway, all worker pools, and the control-plane services. These handle independent, parallelizable units of work (one API request, one eval job), so adding more pods directly adds capacity. This is also exactly how Kubernetes' Horizontal Pod Autoscaler (HPA) is meant to be used — e.g., scale Eval Runner pods based on Kafka consumer-lag/queue depth, not just CPU.

- Vertical scaling (bigger machine) - used first for Postgres, because relational databases don't horizontally scale writes easily; you give it more CPU/RAM/disk before you reach for anything fancier.

- Replication (multiple copies for availability, not just throughput) - Kafka brokers replicate topic partitions so a broker dying doesn't lose data; Postgres can later add read replicas (separate from vertical scaling — replicas handle read traffic, not more write capacity); Redis runs as a cluster for the same reason. Kubernetes' own replicas: N for a deployment is simultaneously horizontal scaling and replication (availability) — those two ideas overlap, but they answer different interview questions ("why scale" vs. "why does this survive a pod crash").

## 10. The Technical Depth Layers (closing every gap)

This section exists specifically so nothing gets skipped. Each "missing layer" below is addressed with what it is, why this project needs it specifically, and how it's implemented.

## 10.1 Multi-Tenancy

Why it matters here: AgentBench is a B2B-style platform — every customer (company) using it has their own agents, their own eval results, their own usage. Without tenant isolation, this is a toy, not a platform. Design:

- v1 (build this first): shared database, tenant-aware schema - every table carries a tenant_id, every query is filtered by it at the ORM/query-builder level (never trust the client to supply it; derive it from the authenticated JWT). This is the standard SaaS starting point — cheaper to build and operate, and what most real B2B platforms run on for years.

- Future path (document now, build later if/when a customer needs it): schema-per-tenant or database-per-tenant for enterprise customers who require hard data isolation for compliance reasons.

- Noisy-neighbor protection: per-tenant rate limits (Redis-backed token buckets) and per- tenant Kafka partitioning/quotas, so one tenant firing 1 million eval requests cannot starve another tenant's queue. This directly answers the classic interview question: "What happens if one customer sends a million requests?" — Answer: they hit their tenant quota, get rate- limited with a clear error, and their jobs queue in their own partition without touching anyone else's throughput.


## 10.2 Authentication & Authorization

Why "JWT login" alone isn't enough: real platforms need to support both human users (via SSO-

style login) and machine clients (CI pipelines calling the API with no human present). Design:

- OAuth2 / OIDC login flow for the dashboard: user  identity provider (start with Google as the OIDC provider, since it's free and well-documented) → backend receives and verifies the ID token → issues its own short-lived access token + longer-lived refresh token (with rotation, so a leaked refresh token can be invalidated).

- API keys for CI/CD and CLI usage - long-lived, scoped, revocable, tied to a tenant and a role, because a GitHub Action can't do an interactive browser login.

- RBAC (Role-Based Access Control): at minimum, Admin (can deploy agents, change gate policies), Developer (can run evals, view logs, cannot change production gates), Viewer (read-only metrics/dashboards). This is what makes the platform look and behave like real enterprise software instead of a side project.

## 10.3 Event-Driven Architecture

Already covered architecturally in 9.3, but to be explicit about why this beats direct function calls: a synchronous API → process() → database design means the API request blocks until processing finishes — completely unworkable when "processing" means running 500 evaluation cases through an LLM. The event-driven version (API → publish event → return job ID immediately → worker consumes asynchronously → result stored → client polls or gets a websocket push) is the only design that scales and is also simply the correct way long-running work is handled in every serious backend system.

## 10.4 Distributed Task Execution

Directly follows from 10.3. Concretely: an eval run is not "the API thread waits." It's: API creates a job record (status: pending), publishes an event, returns the job ID to the caller immediately. A worker (one of potentially many, horizontally scaled) picks the event off the queue, does the work, updates the job record (status: running → completed/failed), and the client either polls GET /jobs/{id} or subscribes to a websocket/SSE channel for live updates. This is the exact pattern behind why "your CI build is running" shows a live progress bar instead of the page just hanging.

## 10.5 Caching Strategy

Three distinct uses, each justified separately (because "just use Redis" without knowing why is a junior-level answer):

- 1. Read-through cache — for expensive, frequently-repeated reads (e.g., a dashboard re- fetching the same evaluation summary). Check Redis first; on miss, query Postgres/ClickHouse, then populate the cache with a TTL.

- 2. Rate limiting — a per-tenant, per-API-key counter (tenant:123:requests with a 60- second expiry) implementing a token-bucket or sliding-window limiter. This is the actual mechanism behind the "noisy neighbor" protection promised in 10.1.


- 3. Distributed locks — prevent the same agent evaluation from being triggered twice concurrently (e.g., a flaky CI retry firing the same job twice). A Redis-based lock (SETNX with expiry, or a proper library like Redlock) ensures only one worker actually executes a given job.

## 10.6 Database Engineering

Why three different stores, not "just Postgres for everything":

- Postgres - relational, transactional data: tenants, users, projects, gate policies, job metadata. This data has real relationships (a user belongs to a tenant, a job belongs to a project) and needs strong consistency — exactly Postgres's strength.

- ClickHouse - trace/event analytics. A single agent run can emit ~20 events (agent_started, tool_called, retrieval_done, llm_called, completed). At meaningful scale (1M+ runs), that's tens of millions of rows of append-only, time-series- shaped data, queried with aggregations ("p95 latency over the last 7 days, grouped by tenant"). Postgres can technically store this, but column-oriented analytical databases like ClickHouse are purpose-built for exactly this query pattern and will outperform Postgres by orders of magnitude here.

- Redis ‐ anything ephemeral and latency-sensitive (Section 10.5).

- Indexing matters and should be measured, not assumed. Concretely: a query like SELECT * FROM runs WHERE tenant_id = 'abc' ORDER BY created_at on a 10-million-row table without an index can take over a second; a composite index on (tenant_id, created_at) can bring that down to tens of milliseconds. Measuring and documenting this exact before/after (with EXPLAIN ANALYZE) is exactly the kind of concrete, demonstrable engineering result worth keeping in the README.

## 10.7 Testing Strategy

A platform whose entire pitch is "we test your agents" cannot itself ship with zero tests — covered in full as its own section (Section 12).

## 10.8 CI/CD Pipeline

Manual deployment is not acceptable for a platform that gates other people's deployments. Pipeline (GitHub Actions): push → run unit + integration tests → build Docker image → vulnerability scan (Trivy) → push image to a registry → deploy to Kubernetes → automated rollback if health checks fail post-deploy. Every deployed image is version-tagged (immutable, traceable) so a bad deploy can be rolled back to an exact known-good tag, not "whatever was there before, probably."

## 10.9 Kubernetes (used properly, not kubectl apply and hope)

- Deployments define desired replica counts per service (e.g., eval-worker replicas: 3).

- HPA (Horizontal Pod Autoscaler) scales worker pools based on a real signal - ideally Kafka consumer lag / queue depth, not just CPU, because an LLM-judge worker can be CPU-idle while waiting on a network call yet still have a deep backlog of pending jobs.


- ConfigMaps hold non-secret environment configuration (log level, feature flags); Secrets hold API keys and credentials, never committed to Git, never baked into images.

- Helm charts package the whole deployment so "install AgentBench" is one command, not twelve manual YAML applies — this is also what makes the project genuinely installable by outside open-source users later.

## 10.10 Security

- API-level: rate limiting (10.5), CORS configured explicitly (not *), strict input validation on every endpoint (especially anything that gets passed into an LLM prompt — see prompt- injection note in 10.12).

- Secrets management: never OPENAI_KEY=12345 in a .env committed to Git. Kubernetes Secrets locally/in-cluster; a managed secrets manager (e.g., cloud provider's secret store) once deployed to real cloud infrastructure.

- Dependency scanning: Trivy (container image scanning) and a dependency vulnerability scanner (e.g., pip-audit/Snyk) wired into CI, so a vulnerable package doesn't silently ship.

## 10.11 Observability (the three pillars, applied here specifically)

- Metrics (Prometheus): requests/sec, latency percentiles, error rates, queue depth per worker pool — this is what HPA scaling decisions and on-call alerting are built on.

- Logs (Loki): structured logs, e.g., "Agent crashed because tool X timed out after 30s" - the why, once metrics tell you something broke.

- Tracing (OpenTelemetry): follow one request across API  Eval Service  Worker → Database → LLM call as a single trace with timed spans — essential in a microservices architecture, because without it, debugging "why was this one job slow" across five services is close to impossible.

## 10.12 AI-Specific Production Concepts

These are what differentiate this project from a generic backend-engineering exercise:

- Model routing: route simple questions to a cheap/fast model and complex reasoning to a larger model, to control cost — directly feeds the cost component of the Agent Reliability Score (Section 5.1).

- Evaluation-before-deploy as a first-class workflow: e.g., "Prompt v1 scored 82% accuracy, Prompt v2 scored 91%" becomes the actual artifact a deployment gate reads, not a Slack message someone remembers to send.

- Guardrails: detection for prompt injection attempts, unsafe/policy-violating outputs, and hallucination signals (e.g., low retrieval-groundedness scores) — feeding the "safety" component of ARS.

- Agent memory, used correctly: short-term/session memory in Redis (fast, ephemeral, scoped to a conversation); long-term memory in Postgres + pgvector (durable, searchable


via embeddings) — a deliberate, justified split rather than throwing everything into one

vector database by default.

## 11. Tech Stack & Justification

| Layer | Choice | Why this, specifically, given |
| --- | --- | --- |
|   |   | Mac M2 + the project's goals |
| Core backend services | Python (FastAPI) | You already have strong Python |
|   |   | fluency from the ADAS |
|   |   | project; FastAPI gives async |
|   |   | support (needed for I/O-bound |
|   |   | LLM calls), automatic |
|   |   | OpenAPI docs (useful for an |
|   |   | open-source platform other |
|   |   | devs will integrate with), and is |
|   |   | the dominant language in the |
|   |   | agent-tooling ecosystem you're |
|   |   | competing/integrating with. |
| Workers (heavy/CPU-bound | Go (optional Phase 3 | Not needed for v1. If a specific |
| paths, optional later) | optimization) | worker (e.g., load-test runner |
|   |   | firing thousands of concurrent |
|   |   | requests) becomes a real |
|   |   | bottleneck in Python, Go is the |
|   |   | documented upgrade path — |
|   |   | mentioned now so it's a |
|   |   | deliberate future decision, not a |
|   |   | rewrite surprise. |
| Event bus | Redpanda (Kafka-API- | Redpanda is a single binary, no |
|   | compatible) instead of Kafka + | JVM, no Zookeeper, |
|   | Zookeeper | dramatically lighter on |
|   |   | RAM/CPU — important for |
|   |   | running the full stack locally on |
|   |   | a Mac M2 with finite memory. |
|   |   | Because it speaks the Kafka |
|   |   | API, every concept you learn |
|   |   | (partitions, consumer groups, |
|   |   | replication, dead-letter queues) |
|   |   | transfers directly to "real" |
|   |   | Kafka if a future employer's |
|   |   | stack uses it — you lose |
|   |   | nothing on the learning/resume |
|   |   | side. |
| Relational/metadata DB | PostgreSQL | Mature, has pgvector for |
|   |   | embeddings (used for agent |
|   |   | memory, Section 10.12, and |
|   |   | behavioral diffing, Section 5.2), |
|   |   | excellent ARM64/Apple |
|   |   | Silicon support, and is the de |


| Layer | Choice | Why this, specifically, given |
| --- | --- | --- |
|   |   | Mac M2 + the project's goals |
|   |   | facto standard for this kind of |
|   |   | metadata — directly |
|   |   | transferable knowledge. |
| Analytics DB | ClickHouse | Purpose-built for the append- |
|   |   | heavy, query-heavy trace/event |
|   |   | data described in Section 10.6; |
|   |   | has official ARM64 Docker |
|   |   | images, runs fine locally. |
| Cache / locks / rate limiting | Redis | Industry standard, minimal |
|   |   | resource footprint, native ARM |
|   |   | support, and one tool cleanly |
|   |   | covers three needs (10.5) |
|   |   | instead of three separate pieces |
|   |   | of infrastructure. |
| Local Kubernetes | k3d (k3s in Docker) | Much lighter than full |
|   |   | minikube/kind on constrained |
|   |   | local resources, spins up/down |
|   |   | fast, genuinely usable for |
|   |   | iterative development on an M2 |
|   |   | without eating all your RAM. |
| Container runtime | Docker Desktop (Apple | Native ARM64 images run |
|   | Silicon build) | natively (fast); when you |
|   |   | eventually need an x86_64 |
|   |   | cloud target, Docker's buildx |
|   |   | supports multi-architecture |
|   |   | image builds from the same |
|   |   | Mac — no separate toolchain |
|   |   | needed. |
| CI/CD | GitHub Actions | Free for public/open-source |
|   |   | repos, the dominant standard, |
|   |   | and what most companies you'd |
|   |   | eventually interview at actually |
|   |   | use. |
| Observability | Prometheus + Grafana + Loki | The de facto open-source |
|   | + OpenTelemetry | observability stack; all have |
|   |   | ARM-compatible images; |
|   |   | OpenTelemetry specifically |
|   |   | because it's vendor-neutral — |
|   |   | your tracing instrumentation |
|   |   | isn't locked into one company's |
|   |   | product. |
| Eval/LLM-judge libraries | DeepEval / OpenAI Evals- | No need to reinvent metric |
|   | style harness (open-source) as | implementations (e.g., |
|   | a starting layer, with custom | faithfulness, answer relevancy) |
|   | scorers added on top | from scratch for the parts that |
|   |   | are already well-solved and |


Layer

Choice

React (or your framework of

Frontend dashboard

choice) + a charting library

(Recharts/Plotly)

Oracle Cloud "Always Free"

Cloud target (when ready for public users)

Ampere ARM instances as the

primary candidate, with

Fly.io/Railway as a fast

secondary option for simple

public demos

Why this, specifically, given

Mac M2 + the project's goals

open-source; your

differentiation is the

platform/infra around

evaluation, not reinventing

every metric.

Standard, widely documented,

easy to deploy as a static site

against the API.

Oracle's free ARM tier is

architecture-matched to your

Mac M2 (ARM64), meaning

your locally-built and tested

images run identically in that

cloud environment with no

architecture-translation

surprises — this is the single

biggest practical reason to

prefer it over an x86-only free

tier. (Verify current free-tier

terms before committing —

cloud provider free-tier policies

change over time.)

General principle behind every choice above: prefer tools that (a) you can run lightly on a Mac M2 without melting your laptop, (b) are API/protocol-compatible with the "real" enterprise version (Redpanda↔Kafka being the clearest example), so nothing you learn is throwaway knowledge, and (c) have genuine ARM64 support so there's no nasty surprise moving from local development to

either an ARM cloud target or, later, an x86 one via multi-arch builds.

## 12. Testing Strategy

A platform that tests other people's agents must be tested itself, rigorously:

- Unit tests (pytest) - every service's business logic (policy evaluation, gate-threshold logic, scoring functions) tested in isolation, no network calls.

- Integration tests - spin up the real dependency stack (Postgres, Redis, Redpanda) via Docker Compose in CI and test that services talk to each other correctly (e.g., publishing an eval.requested event actually results in a worker picking it up and writing a result).

- Load tests (k6) - test AgentBench's own API and worker throughput, not just agents being tested by it (e.g., "10,000 concurrent eval-trigger requests, p95 latency under 180ms" is a real, demonstrable, README-worthy number).

- Security tests - dependency scanning (Trivy/Snyk) in CI, plus basic adversarial testing of your own API inputs (injection attempts, malformed payloads).


- Chaos tests - once the chaos-engineering feature (5.4) exists for evaluating customer agents, the same fault-injection capability should be turned on AgentBench's own dependencies (kill a worker mid-job, drop a Redpanda broker) to prove the platform itself degrades gracefully rather than losing jobs.

- The actual proof-of-value test: run the three benchmark agents (RAG chatbot, tool-calling agent, multi-agent workflow) through both "manual ad-hoc testing" and "AgentBench automated testing," and document the gap concretely (e.g., "manual testing across 20 hand- written cases found 5 failures; AgentBench's automated suite of 1,000 generated/curated cases found 47, and would have blocked the deployment"). This single comparison is the most convincing evidence the whole project works, for a panel, a portfolio, or future users.

## 13. Methodology — Build Order (no fixed timeline, dependency-ordered)

Phases here are ordered by technical dependency, not calendar time — build Phase 2 before Phase 3 because Phase 3's novelty features need Phase 2's data pipeline to exist, not because of any deadline. Phase 1 — Core MVP CLI, single API service, eval engine running against one benchmark agent, basic dashboard, basic GitHub Actions integration that can pass/fail a PR check. Goal: prove the core loop (write agent → run eval → see pass/fail) works end-to-end, even ugly. Phase 2 — Real Distributed Engineering Break the monolith into the control-plane services from Section 9; introduce Redpanda and the worker-pool pattern; add multi-tenancy (10.1), auth/RBAC (10.2), Postgres + ClickHouse + Redis properly separated (10.6), local k3d Kubernetes deployment, and the full observability stack (10.11). Goal: the platform is now architecturally "real," not a toy, even if still running only on your Mac. Phase 3 — Research-Grade Novelty Build the five differentiating features from Section 5: Agent Reliability Score, Behavioral Diff Engine, Production Failure Mining, Chaos Engineering, and Agent Load Testing. Goal: this is what makes AgentBench different from Braintrust/Arize/LangSmith rather than a clone of them. Phase 4 — Hardening & Public Launch Security pass (10.10), CI/CD pipeline hardening (10.8), Helm chart packaging (10.9), documentation good enough for outside contributors, deploy to free- tier cloud, open-source the repo, write the launch post. Goal: a stranger can clone it, deploy it, and

actually use it on their own agent.

- 14. Success Metrics / How You'll Know It Works

- Concrete regression-catching proof: the manual-vs-automated failure-count comparison from Section 12, with real numbers.

- Performance numbers you can defend under questioning: e.g., the index optimization before/after from Section 10.6, the load-test p95 latency from Section 12 — anyone (a panel, an interviewer, a curious open-source user) can ask "how do you know it scales" and you


- have a measured answer, not a claim.

- Real deployment gating in action: a recorded/documented example of a PR that was actually blocked by AgentBench's gate because it failed an eval threshold, with the gate's reasoning visible.

- Adoption signal, once open-sourced: stars/forks aren't vanity metrics here - they're evidence that the framework-agnostic design (Section 8.1) actually worked for someone other than you.

## 15. Risks & Mitigations

| Risk | Mitigation |
| --- | --- |
| Scope is large enough to never finish | Phase ordering (Section 13) ensures there's a |
|   | working, demoable product at the end of every |
|   | phase, not just at the very end |
| Local resource limits on Mac M2 (RAM/CPU | Lightweight tool choices (Redpanda over Kafka, |
| running Postgres + ClickHouse + Redpanda + | k3d over full clusters) specifically chosen in |
| k3d + workers simultaneously) | Section 11 to address this; can also run a |
|   | reduced subset of services at a time during |
|   | development |
| LLM API costs during heavy eval/load testing Use cheap/small models for development-time |   |
|   | testing; reserve larger models for final validation |
|   | runs; the model-routing concept (10.12) literally |
|   | exists to manage this |
| Free-tier cloud limits change or get revoked | Architecture stays cloud-agnostic (Kubernetes + |
|   | standard open-source components), so moving |
|   | providers is a redeploy, not a rewrite |
| Nobody adopts the open-source version | The three benchmark agents and documented |
|   | before/after results (Section 12, 14) exist |
|   | specifically to make the value obvious to a |
|   | stranger within minutes of reading the |
|   | README |

## 16. Glossary (for fast lookup later)

- SRE (Site Reliability Engineering): the discipline of running production systems with measurable reliability targets (SLOs) and acceptable failure budgets, instead of just "try to keep it up."

- SLO (Service Level Objective): a target reliability number (e.g., 99.9% uptime, or here, >90% correctness) you commit to.

- Error budget: how much unreliability is allowed before you must stop shipping new changes and fix reliability first.


- Canary release: rolling out a change to a small fraction of traffic first, to catch problems before a full rollout.

- Chaos engineering: deliberately injecting failures into a system to test its resilience.

- Consumer group (Kafka/Redpanda): a set of workers sharing the job of consuming messages from a topic, so work is distributed rather than duplicated.

- HPA (Horizontal Pod Autoscaler): a Kubernetes mechanism that automatically adds/removes pod replicas based on a metric (CPU, custom queue depth, etc.).

- RBAC: Role-Based Access Control ‑ permissions tied to a role (Admin/Developer/Viewer) rather than to individual users one by one.

- Multi-tenancy: one deployed system serving many separate customers ("tenants"), with their data and usage isolated from each other.

## Final note

This document should be revisited and edited as the project evolves — it is meant to be a living foundation, not a one-time write-up. When a real-world decision contradicts something written

here, update this document, don't just diverge from it silently.
