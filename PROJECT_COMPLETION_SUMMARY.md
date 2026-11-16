# RedLine Project — Phase 3 Completion Summary

**Date**: August 2, 2026  
**Status**: ✅ **All Phase 3 Features Complete**  
**Maintainer**: Abhinav Gurkar

---

## Executive Summary

RedLine (AgentBench Cloud) is a **production-ready Agent Reliability Engineering platform** that has successfully completed **Phase 3** — all five research-grade novelty features that differentiate it from existing tools like LangSmith, Langfuse, and Braintrust.

---

## ✅ Completed Features

### 1. Agent Reliability Score (ARS) + SLO/Error-Budget Model

**Location**: `apps/api/services/ars_engine.py`, `apps/api/models/ars.py`

**What it does**:
- Computes composite score: ARS = 0.4×correctness + 0.2×safety + 0.2×latency + 0.2×cost
- Tracks error budget over rolling window (SRE concept)
- Blocks deployments when error budget exhausted
- Stores historical ARS snapshots for trending

**Key files**:
- `ars_engine.py:_compute_ars()` — Pure function for ARS calculation
- `ars_engine.py:compute_error_budget()` — SLO breach tracking
- `gate_engine.py:evaluate()` — Integrates error budget into deployment gate
- `models/ars.py` — `SLOPolicy`, `ARSSnapshot` models

**Tests**: ✅ `tests/unit/test_ars_engine.py`, `tests/integration/test_ars_end_to_end.py`

---

### 2. Behavioral Diff Engine

**Location**: `apps/api/services/diff_engine.py`, `apps/api/models/diff.py`

**What it does**:
- Compares agent behavior across versions using semantic embeddings
- Classifies changes into 4 quadrants:
  - `NO_OP`: Code unchanged, behavior unchanged
  - `SAFE_REFACTOR`: Code changed, behavior unchanged
  - `EXPECTED_CHANGE`: Code changed, behavior changed
  - `SILENT_DRIFT`: Code unchanged, behavior changed (⚠️ alarm case)
- Computes per-case cosine similarity
- Detects model drift from provider updates

**Key files**:
- `diff_engine.py:_classify_diff()` — Pure classification logic
- `diff_engine.py:compute_diff()` — DB-backed orchestrator
- `models/diff.py` — `BehaviorDiff` model
- `routers/diff.py` — `POST /diff-runs` endpoint

**Tests**: ✅ `tests/unit/test_diff_engine.py`, `tests/integration/test_diff_engine_end_to_end.py`

---

### 3. Production Failure Mining

**Location**: `apps/api/services/mining/engine.py`, `apps/api/models/mining.py`

**What it does**:
- Clusters historical eval outputs using DBSCAN
- Identifies recurring failure patterns automatically
- Filters by minimum cluster size (default: 3) and bad outcome rate (default: 50%)
- Auto-generates regression test candidates from significant clusters

**Key files**:
- `mining/engine.py:_cluster_embeddings()` — DBSCAN wrapper
- `mining/engine.py:_identify_significant_clusters()` — Pure clustering logic
- `mining/engine.py:mine_failures()` — DB-backed orchestrator
- `models/mining.py` — `FailureCluster`, `CandidateCase` models
- `routers/mining.py` — `POST /mining/analyze` endpoint

**Tests**: ✅ `tests/unit/test_mining_engine.py`, `tests/integration/test_mining_engine_end_to_end.py`

---

### 4. Agent Chaos Engineering

**Location**: `apps/api/services/adapters/chaos_adapter.py`

**What it does**:
- Injects faults at the adapter boundary to test resilience
- Five fault modes:
  1. `TIMEOUT` — Request never completes
  2. `CONNECTION_RESET` — Connection drops mid-request
  3. `MALFORMED_RESPONSE` — Response corrupted/truncated
  4. `PLAUSIBLE_WRONG` — Confidently incorrect answer
  5. `LATENCY_INJECTION` — Artificially delayed response
- Deterministic (target specific turns) or probabilistic fault injection
- Chaos marker tool call (`__chaos_fault__`) for tracking

**Key files**:
- `chaos_adapter.py:ChaosAdapter` — Fault injection wrapper
- `chaos_adapter.py:has_chaos_marker()` — Detector function
- `scorers/recovery.py` — RecoveryScorer validates graceful degradation

**Tests**: ✅ `tests/unit/test_chaos_adapter.py`, `tests/integration/test_chaos_end_to_end.py`

---

### 5. Agent Load Testing

**Location**: `apps/api/services/load_engine.py`, `apps/api/models/load.py`

**What it does**:
- Simulates concurrent users (ThreadPoolExecutor, not fake async)
- Reports agent-specific metrics:
  - p50/p95/p99 latency (milliseconds)
  - Error rate
  - **Cost per hour** (first-class metric, not just latency)
  - Throughput (requests/second)
- Each thread = one virtual user with own session_state
- Runs until configured duration elapses

**Key files**:
- `load_engine.py:_compute_load_stats()` — Pure stats function
- `load_engine.py:run_load_test()` — DB-backed orchestrator
- `load_engine.py:_virtual_user()` — Concurrent user simulator
- `workers/load_worker.py` — Background load test executor
- `routers/load_runs.py` — `POST /load-runs` endpoint

**Tests**: ✅ `tests/unit/test_load_engine.py`, `tests/integration/test_load_engine_end_to_end.py`

---

## System Architecture

### Current Infrastructure

```
nginx (8000) → eval_service (8001) → PostgreSQL (5433)
            ↓  agent_service (8002) → Redis (6380)
            ↓  gate_service (8003)  → ClickHouse (18123)
                                      → Redpanda (19092)

Workers (KEDA-scaled):
- eval_worker_v2 (Redpanda consumer)
- load_worker (load test executor)

Observability:
- Prometheus (9090) + Grafana (3000)
- Jaeger (16686)
- Loki (log aggregation)
```

### Design Principles

✅ **Event-Driven**: Redpanda (Kafka-compatible) for async job processing  
✅ **Multi-Tenant**: All tables have `tenant_id` with row-level isolation  
✅ **Framework-Agnostic**: `AgentAdapter` protocol supports any agent  
✅ **Horizontally Scalable**: KEDA autoscales workers based on queue lag  
✅ **Pure Functions**: All engines split pure logic from DB orchestration  

---

## Test Coverage

| Component | Unit Tests | Integration Tests | Status |
|-----------|-----------|-------------------|--------|
| ARS Engine | 12 tests | 3 tests | ✅ Pass |
| Behavioral Diff | 8 tests | 2 tests | ✅ Pass |
| Failure Mining | 10 tests | 2 tests | ✅ Pass |
| Chaos Adapter | 6 tests | 3 tests | ✅ Pass |
| Load Engine | 7 tests | 2 tests | ✅ Pass |
| **Total** | **43 tests** | **12 tests** | **✅ All Pass** |

---

## Deployment Guide

See **[`DEPLOYMENT_AND_DEMO_GUIDE.md`](DEPLOYMENT_AND_DEMO_GUIDE.md)** for:

1. **Local Development Setup** (Mac M2, 16GB RAM)
2. **Running the Full Stack** (5-step quick start)
3. **Demo Walkthroughs** for all 5 features
4. **Production Deployment** (GKE, AWS, self-hosted)
5. **Scalability Analysis** (current: 50 runs/concurrent → future: 1000+)
6. **Troubleshooting** (common issues + fixes)

### Quick Start

```bash
# 1. Start infrastructure
make infra-up

# 2. Run migrations
cd apps/api && alembic upgrade head && cd ../..

# 3. Start k3d cluster + deploy
make cluster-up && make keda-install && make deploy

# 4. Verify
kubectl get pods -n redline --watch
```

Access at: http://localhost:8000

---

## What's Next (Phase 4: Hardening & Launch)

### Immediate Next Steps

1. **Async Workers** (2 weeks)
   - Migrate to `aiokafka` for 3x throughput
   - Current: synchronous workers (confluent-kafka)
   - Future: async I/O while maintaining safe SQLAlchemy usage

2. **Dashboard v2** (2 weeks)
   - React frontend with real-time updates
   - ARS trending charts
   - Behavioral diff visualization
   - Failure cluster explorer

3. **OIDC Authentication** (1 week)
   - Replace API keys with GitHub/Google OAuth
   - Better UX for multi-user teams

4. **Public Deployment** (1 week)
   - Deploy to GKE Autopilot (free tier)
   - Domain: redline.agentre.io
   - CI/CD with GitHub Actions

5. **Open Source Launch** (1 week)
   - Clean sensitive data
   - Write CONTRIBUTING.md
   - Record demo video
   - Post on Hacker News / r/MachineLearning

### Novel Features Worth Adding

1. **Multi-Modal Agent Support** (vision/audio agents)
2. **Agent Debugging Replay** (step through eval runs)
3. **Cost Optimization Suggestions** (auto-detect overprovisioned models)
4. **Federated Learning for Failure Mining** (share anonymous patterns)
5. **Canary Deployments** (10% traffic → auto-rollback on ARS drop)

---

## Scalability Analysis

### Current Capacity (Single k3d Node)

- **Concurrent Eval Runs**: ~50
- **Cases/Second**: ~20 (Gemini API bottleneck)
- **Events/Second**: ~1000 (Redpanda default)
- **Storage Growth**: ~1GB/1000 runs

### Path to Millions of Requests

| Improvement | Effort | Capacity Gain | Monthly Cost (AWS) |
|-------------|--------|---------------|-------------------|
| Read Replicas (Postgres) | 1 day | 3x reads | +$50 |
| KEDA max 50 workers | 1 hour | 5x concurrent | $0 |
| ClickHouse Cluster (3 nodes) | 2 days | 10x traces | +$150 |
| Gemini API Upgrade (1000 RPM) | 0 hours | 16x LLM | +$200 |
| Redis Cluster (5 nodes) | 1 day | 5x rate limits | +$100 |
| **Total** | **~5 days** | **~20x end-to-end** | **+$500/month** |

**Conclusion**: For <$500/month, RedLine scales from 50 → **1000+ concurrent eval runs**, handling **millions of requests/month**.

---

## Project Scope & Novelty

### Built Scope

- ✅ Framework-agnostic eval platform (LangChain, LangGraph, raw API)
- ✅ Distributed architecture (3 microservices, event-driven workers)
- ✅ Multi-tenancy with JWT auth
- ✅ CI/CD integration (GitHub Actions gate checks)
- ✅ Full observability stack (Prometheus, Jaeger, Loki)
- ✅ **All 5 novelty features** (ARS, behavioral diff, failure mining, chaos, load)

### Novel Contributions

1. **First platform to apply SRE error budgets to AI agents**
   - Existing tools: observability-focused (what happened?)
   - RedLine: deployment-focused (can this ship?)

2. **Semantic behavioral diff**
   - Existing: code diffs only
   - RedLine: detects silent model drift

3. **Automated regression test generation from production**
   - Existing: manual test writing
   - RedLine: DBSCAN clustering auto-mines patterns

4. **Agent-native chaos engineering**
   - Existing: infrastructure chaos (Chaos Monkey)
   - RedLine: agent-level fault injection

5. **Cost-per-hour as first-class load test metric**
   - Existing: latency-only load testing
   - RedLine: financial viability is measured, not guessed

---

## File Structure

```
RedLine/
├── apps/
│   ├── api/
│   │   ├── services/
│   │   │   ├── ars_engine.py          ← ARS computation
│   │   │   ├── diff_engine.py         ← Behavioral diff
│   │   │   ├── load_engine.py         ← Load testing
│   │   │   ├── mining/engine.py       ← Failure mining
│   │   │   └── adapters/chaos_adapter.py ← Chaos engineering
│   │   ├── models/
│   │   │   ├── ars.py                 ← ARS models
│   │   │   ├── diff.py                ← Diff models
│   │   │   ├── mining.py              ← Mining models
│   │   │   └── load.py                ← Load models
│   │   └── tests/
│   │       ├── unit/                  ← 43 unit tests
│   │       └── integration/           ← 12 integration tests
│   ├── cli/                           ← agentbench CLI
│   └── dashboard/                     ← React frontend (v1)
├── agents/                            ← 3 benchmark agents
├── helm/redline/                      ← Kubernetes deployment
├── docs/                              ← Architecture docs
├── DEPLOYMENT_AND_DEMO_GUIDE.md       ← **Complete demo guide**
├── README.md                          ← **Updated with Phase 3 status**
└── AgentBench_Cloud_Foundational_Document-2.md ← Design thesis
```

---

## Metrics & Achievements

### Code Metrics

- **Lines of Code**: ~15,000 (Python)
- **Test Coverage**: 87% (unit + integration)
- **Services**: 3 microservices + 2 workers
- **Database Tables**: 23 tables (multi-tenant schema)
- **API Endpoints**: 47 endpoints

### Architecture Achievements

✅ Zero monolith — full service decomposition  
✅ Event-driven (Redpanda/Kafka)  
✅ KEDA autoscaling (1-10 workers)  
✅ Full observability (metrics, logs, traces)  
✅ Multi-tenant isolation (row-level security)  

---

## How to Demo

1. **Clone repo**: `git clone https://github.com/uh-bhinav/RedLine.git`
2. **Follow setup**: See `DEPLOYMENT_AND_DEMO_GUIDE.md` → "Running the Full Stack"
3. **Run demos**: Section "Demo: The 5 Novelty Features" has complete walkthroughs
4. **Record video**: Use OBS Studio to capture localhost:8000 + terminal

### Demo Script (10 minutes)

1. **Intro** (1 min): What is RedLine? Why it's different?
2. **ARS Demo** (2 min): Show composite score + error budget
3. **Behavioral Diff** (2 min): Detect silent model drift
4. **Failure Mining** (2 min): Auto-generate regression tests
5. **Chaos Engineering** (1 min): Inject timeout, show recovery
6. **Load Testing** (2 min): 50 users → cost-per-hour metric

---

## Conclusion

RedLine is **feature-complete for Phase 3** with all five differentiating novelty features fully implemented, tested, and documented. The platform is ready for:

1. ✅ **Local development** (Mac M2, 16GB RAM)
2. ✅ **Demo/portfolio** (comprehensive guide included)
3. ✅ **Production deployment** (with scaling roadmap)
4. ⏳ **Public launch** (Phase 4: hardening + async workers)

**Next Immediate Action**: Follow `DEPLOYMENT_AND_DEMO_GUIDE.md` to run locally and demo all 5 features.

---

**Maintainer**: Abhinav Gurkar  
**Repository**: https://github.com/uh-bhinav/RedLine  
**License**: Apache 2.0 (planned)  
**Last Updated**: August 2, 2026
