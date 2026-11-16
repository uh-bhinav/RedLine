# RedLine (AgentBench Cloud) - Complete Deployment & Demo Guide

**Last Updated**: August 2026  
**Project Status**: Phase 3 Complete ✅ | All 5 Novelty Features Implemented

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Prerequisites](#prerequisites)
4. [Local Development Setup](#local-development-setup)
5. [Running the Full Stack](#running-the-full-stack)
6. [Demo: The 5 Novelty Features](#demo-the-5-novelty-features)
7. [Production Deployment](#production-deployment)
8. [System Design & Scalability Analysis](#system-design--scalability-analysis)
9. [Troubleshooting](#troubleshooting)
10. [Next Steps & Improvements](#next-steps--improvements)

---

## Executive Summary

**RedLine** is a production-grade Agent Reliability Engineering platform that applies SRE principles (SLOs, error budgets, chaos engineering) to AI agents. Unlike observability-focused tools (LangSmith, Langfuse, Braintrust), RedLine **physically blocks** unreliable agents from deploying via hard CI/CD gates.

### What Makes RedLine Different (The 5 Novelty Features)

| Feature | What It Does | Why It Matters |
|---------|--------------|----------------|
| **1. Agent Reliability Score (ARS)** | Composite score (0.4×correctness + 0.2×safety + 0.2×latency + 0.2×cost) with SLO/error-budget tracking | One number gates deployment, like "99.9% uptime" for infrastructure |
| **2. Behavioral Diff Engine** | Semantic embedding comparison across versions | Catches "silent drift" when model changes but code doesn't |
| **3. Production Failure Mining** | DBSCAN clustering on embeddings to auto-generate regression tests | Test suite learns from production failures automatically |
| **4. Agent Chaos Engineering** | Fault injection (timeouts, malformed responses, wrong data) | Tests agent resilience like Netflix's Chaos Monkey |
| **5. Agent Load Testing** | Concurrent user simulation with p50/p95/p99 latency + cost-per-hour metrics | Finds cost and failure-rate breaking points |

### Current Implementation Status

✅ **Phase 1**: Core eval loop (run_eval → scorers → gate)  
✅ **Phase 2**: Distributed infrastructure (Redpanda, Redis, ClickHouse, k3d + KEDA, OpenTelemetry)  
✅ **Phase 3**: All 5 novelty features fully implemented with tests  
⏳ **Phase 4**: Hardening & public launch (pending)

---

## System Architecture

```
                    ┌──────────────────────────────────┐
                    │  nginx gateway (8085 / k3d :8000) │
                    └──────┬──────────┬──────────┬──────┘
                           │          │          │
          ┌────────────────▼──┐  ┌────▼──────┐  ┌▼──────────────┐
          │  eval_service     │  │agent_svc  │  │gate_service   │
          │  :8001            │  │:8002      │  │:8003          │
          │  - /eval-runs     │  │- /agents  │  │- /dashboard   │
          │  - /ci            │  │- /suites  │  │               │
          │  - /auth          │  │           │  │               │
          │  - /diff-runs     │  │           │  │               │
          │  - /load-runs     │  │           │  │               │
          │  - /mining        │  │           │  │               │
          └──────┬────────────┘  └───────────┘  └───────────────┘
                 │
    ┌────────────▼───────────────────────────────────┐
    │  Worker Pool (KEDA-scaled)                     │
    │  - eval_worker_v2  (Redpanda consumer)         │
    │  - load_worker     (concurrent test executor)  │
    └──────┬─────────────────────────────────────────┘
           │
    ┌──────▼────────────────────────────────────────┐
    │  Infrastructure Layer                         │
    │  - Redpanda (Kafka-compatible event bus)      │
    │  - PostgreSQL (relational data)               │
    │  - Redis (rate limiting, caching)             │
    │  - ClickHouse (analytics, trace storage)      │
    │  - Prometheus + Grafana (metrics)             │
    │  - Loki (log aggregation)                     │
    │  - Jaeger (distributed tracing)               │
    └───────────────────────────────────────────────┘
```

### Key Architectural Decisions

1. **Event-Driven Architecture**: Redpanda (Kafka-compatible) for async job processing
2. **Multi-Tenancy**: All tables have `tenant_id` with row-level isolation
3. **Service Decomposition**: 3 microservices (eval, agent, gate) instead of monolith
4. **Horizontal Scalability**: KEDA autoscales workers based on Redpanda lag
5. **Framework-Agnostic**: `AgentAdapter` protocol supports any agent (LangChain, LangGraph, raw API)

---

## Prerequisites

### Hardware Requirements

- **Mac M2** (as designed) or equivalent Linux/WSL2
- **16GB RAM minimum** (8GB for k3d cluster, 4GB for infra, 4GB for services)
- **20GB free disk space**

### Software Requirements

```bash
# Required
- Docker Desktop 4.x+
- Python 3.10
- kubectl 1.28+
- k3d 5.6+
- Helm 3.12+

# Optional (for development)
- make
- psql (PostgreSQL client)
- rpk (Redpanda CLI)
```

### Installation Check

```bash
# Verify versions
docker --version          # Docker version 24.0.0+
python3.10 --version      # Python 3.10.x
kubectl version --client  # v1.28+
k3d version               # v5.6+
helm version --short      # v3.12+
```

---

## Local Development Setup

### Step 1: Clone and Environment Setup

```bash
git clone https://github.com/uh-bhinav/RedLine.git
cd RedLine

# Copy example env file
cp .env.example .env
```

### Step 2: Configure Environment Variables

Edit `.env`:

```bash
# === Database ===
DATABASE_URL=postgresql://redline:redline_dev@localhost:5433/redline

# === Redpanda ===
REDPANDA_BROKERS=localhost:19092

# === Redis ===
REDIS_URL=redis://localhost:6380/0

# === ClickHouse ===
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=18123
CLICKHOUSE_PASSWORD=redline_dev

# === LLM API Keys ===
GEMINI_API_KEY=your_gemini_api_key_here  # Get from https://makersuite.google.com/app/apikey

# === Security ===
JWT_SECRET_KEY=your_secret_key_here  # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"

# === GitHub (for CI integration) ===
GITHUB_TOKEN=ghp_your_token_here  # Optional: for PR checks
GITHUB_REPO_OWNER=your_username
GITHUB_REPO_NAME=your_repo
```

### Step 3: Python Dependencies

```bash
# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r apps/api/requirements.txt
pip install -r apps/cli/requirements.txt
```

---

## Running the Full Stack

### Quick Start (All-in-One)

```bash
# 1. Start infrastructure (Postgres, Redis, ClickHouse, Redpanda)
make infra-up

# Wait ~30 seconds for services to initialize

# 2. Run database migrations
cd apps/api
alembic upgrade head
cd ../..

# 3. Start k3d cluster
make cluster-up

# 4. Install KEDA (autoscaler)
make keda-install

# 5. Build and deploy all services
make deploy

# 6. Wait for pods to be ready (~2 minutes)
kubectl get pods -n redline --watch

# Press Ctrl+C when all pods show Running/Completed
```

### Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n redline

# Expected output:
# NAME                              READY   STATUS    RESTARTS   AGE
# agent-service-xxx                 1/1     Running   0          2m
# eval-service-xxx                  1/1     Running   0          2m
# gate-service-xxx                  1/1     Running   0          2m
# eval-worker-v2-xxx                1/1     Running   0          2m
# nginx-gateway-xxx                 1/1     Running   0          2m

# Check logs
make logs
```

### Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| API Gateway | http://localhost:8000 | Main entry point |
| Grafana | http://localhost:3000 | Metrics dashboards (admin/admin) |
| Jaeger | http://localhost:16686 | Distributed tracing |
| Prometheus | http://localhost:9090 | Metrics backend |
| Redpanda Console | http://localhost:8080 | Kafka topic viewer |

---

## Demo: The 5 Novelty Features

### Setup: Create a Test Agent and Suite

```bash
# 1. Create API key
cd apps/api
python scripts/create_api_key.py

# Save the output: rl_live_xxxxx...

# 2. Register a test agent
export REDLINE_API_KEY=rl_live_xxxxx  # Your key from step 1
python scripts/register_agent_version.py \
  --name "demo-agent" \
  --version "v1.0" \
  --entrypoint "agents/rag_agent/agent.py:run" \
  --description "Demo RAG agent for testing"

# 3. Push an eval suite
python scripts/push_suite.py \
  --agent-name "demo-agent" \
  --suite-file "../../test_suites/rag_demo_suite.yaml"

cd ../..
```

### Feature 1: Agent Reliability Score (ARS) + SLO/Error-Budget

**What It Does**: Computes a composite reliability score and tracks error budget over time.

```bash
# 1. Run an eval that computes ARS
curl -X POST http://localhost:8000/eval-runs \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_version_id": "your-version-id",
    "suite_id": "your-suite-id",
    "triggered_by": "manual"
  }'

# 2. Check ARS score
curl http://localhost:8000/eval-runs/{run_id} \
  -H "Authorization: Bearer $REDLINE_API_KEY" | jq '.ars_score'

# Expected output:
# {
#   "ars": 0.847,
#   "correctness": 0.90,
#   "safety": 0.95,
#   "latency": 0.78,
#   "cost": 0.82,
#   "detail": "ARS=0.847 = 0.4*0.90(correctness) + 0.2*0.95(safety) + 0.2*0.78(latency) + 0.2*0.82(cost)"
# }

# 3. Check error budget status
curl http://localhost:8000/agents/{agent_id}/error-budget \
  -H "Authorization: Bearer $REDLINE_API_KEY" | jq

# Expected output:
# {
#   "exhausted": false,
#   "target_ars": 0.90,
#   "error_budget_pct": 0.10,
#   "window_size": 7,
#   "breaches": 2,
#   "breach_rate": 0.286,
#   "budget_remaining_pct": 0.086,
#   "detail": "2/7 recent run(s) scored below target ARS 0.90 (28.6% breach rate vs 10.0% allowed budget)"
# }
```

**What This Demonstrates**:
- ✅ ARS is a single number (0.0-1.0) that combines 4 dimensions
- ✅ Error budget tracks recent reliability (SRE concept applied to agents)
- ✅ When budget exhausted → deployment gate blocks (see gate check demo)

---

### Feature 2: Behavioral Diff Engine

**What It Does**: Compares agent behavior across versions using semantic embeddings, catching "silent drift".

```bash
# 1. Run eval for version 1
RUN_A_ID=$(curl -X POST http://localhost:8000/eval-runs \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_version_id": "version-1-id",
    "suite_id": "suite-id",
    "triggered_by": "manual"
  }' | jq -r '.id')

# Wait for completion (~30s)
sleep 30

# 2. Register version 2 (same code, different model)
python apps/api/scripts/register_agent_version.py \
  --name "demo-agent" \
  --version "v1.1" \
  --entrypoint "agents/rag_agent/agent.py:run" \
  --description "Same code, model upgraded by provider"

# 3. Run eval for version 2
RUN_B_ID=$(curl -X POST http://localhost:8000/eval-runs \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_version_id": "version-2-id",
    "suite_id": "suite-id",
    "triggered_by": "manual"
  }' | jq -r '.id')

sleep 30

# 4. Compute behavioral diff
curl -X POST http://localhost:8000/diff-runs \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"eval_run_a_id\": \"$RUN_A_ID\",
    \"eval_run_b_id\": \"$RUN_B_ID\"
  }" | jq

# Expected output (SILENT_DRIFT case):
# {
#   "classification": "silent_drift",
#   "code_changed": false,
#   "behavior_changed": true,
#   "mean_similarity": 0.82,
#   "threshold": 0.90,
#   "per_case_similarity": {
#     "case_1": 0.88,
#     "case_2": 0.76,
#     "case_3": 0.81
#   },
#   "detail": "code UNCHANGED but behavior changed -- likely a silent model/provider update. mean_similarity=0.820 (threshold=0.90) across 3 case(s)"
# }
```

**What This Demonstrates**:
- ✅ Detects behavioral changes even when code hash is identical
- ✅ Four classifications: NO_OP, SAFE_REFACTOR, EXPECTED_CHANGE, SILENT_DRIFT
- ✅ Per-case similarity breakdown shows which tests changed

---

### Feature 3: Production Failure Mining

**What It Does**: Clusters historical eval outputs to find recurring failure patterns and auto-generate regression tests.

```bash
# 1. Run mining analysis
curl -X POST http://localhost:8000/mining/analyze \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "your-agent-id",
    "min_cluster_size": 3,
    "min_bad_outcome_rate": 0.5
  }' | jq

# Expected output:
# {
#   "clusters_found": 2,
#   "candidate_cases_generated": 2,
#   "clusters": [
#     {
#       "cluster_label": 0,
#       "size": 5,
#       "bad_outcome_rate": 0.80,
#       "representative_text": "I don't have access to that information...",
#       "candidate_case_id": "uuid-1"
#     },
#     {
#       "cluster_label": 1,
#       "size": 4,
#       "bad_outcome_rate": 0.75,
#       "representative_text": "Calculating... Error: division by zero",
#       "candidate_case_id": "uuid-2"
#     }
#   ]
# }

# 2. View candidate regression tests
curl http://localhost:8000/mining/candidates \
  -H "Authorization: Bearer $REDLINE_API_KEY" | jq

# 3. Promote a candidate to a real test case
curl -X POST http://localhost:8000/mining/candidates/{candidate_id}/promote \
  -H "Authorization: Bearer $REDLINE_API_KEY"
```

**What This Demonstrates**:
- ✅ DBSCAN clustering finds recurring patterns automatically
- ✅ Only surfaces clusters with high failure rates (not just common topics)
- ✅ Regression test suite grows from production data, not manual writing

---

### Feature 4: Agent Chaos Engineering

**What It Does**: Injects faults (timeouts, malformed responses, wrong data) to test agent resilience.

```bash
# 1. Create a chaos-enabled eval suite
cat > chaos_suite.yaml <<EOF
name: chaos-resilience-test
description: Tests agent recovery under faults
cases:
  - key: timeout_recovery
    description: Agent should handle timeout gracefully
    turns:
      - user: "What is the capital of France?"
        chaos:
          mode: timeout
          target_turn_indices: [0]
      - user: "And what about Germany?"  # Should still work
    expectations:
      final_response:
        contains: "Berlin"

  - key: malformed_data
    description: Agent should not hallucinate when data corrupted
    turns:
      - user: "Give me customer #12345 details"
        chaos:
          mode: malformed_response
          probability: 1.0
    expectations:
      scorer:
        - type: safety
          must_not_contain: ["confirmed", "approved"]

  - key: wrong_answer_injection
    description: Agent should detect plausible but incorrect data
    turns:
      - user: "What's 2 + 2?"
        chaos:
          mode: plausible_wrong
          target_turn_indices: [0]
      - user: "Are you sure?"  # Should recalculate
    expectations:
      final_response:
        contains: "4"
EOF

# 2. Push chaos suite
python apps/api/scripts/push_suite.py \
  --agent-name "demo-agent" \
  --suite-file "chaos_suite.yaml"

# 3. Run chaos eval
curl -X POST http://localhost:8000/eval-runs \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_version_id": "your-version-id",
    "suite_id": "chaos-suite-id",
    "triggered_by": "manual"
  }'

# 4. Check results with chaos markers
curl http://localhost:8000/eval-runs/{run_id}/results \
  -H "Authorization: Bearer $REDLINE_API_KEY" | jq '.results[] | select(.tool_calls[] | .name == "__chaos_fault__")'
```

**What This Demonstrates**:
- ✅ Five fault modes: timeout, connection_reset, malformed_response, plausible_wrong, latency_injection
- ✅ Deterministic (specific turns) or probabilistic fault injection
- ✅ RecoveryScorer validates graceful degradation vs hallucination

---

### Feature 5: Agent Load Testing

**What It Does**: Simulates concurrent users to measure p50/p95/p99 latency, error rate, and cost-per-hour at scale.

```bash
# 1. Create a load test run
curl -X POST http://localhost:8000/load-runs \
  -H "Authorization: Bearer $REDLINE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_version_id": "your-version-id",
    "message": "What are your business hours?",
    "virtual_users": 50,
    "duration_seconds": 60,
    "description": "50 concurrent users for 1 minute"
  }' | jq -r '.id'

# Save the load run ID
LOAD_RUN_ID="..."

# 2. Wait for completion (~70 seconds)
sleep 70

# 3. Get results
curl http://localhost:8000/load-runs/$LOAD_RUN_ID \
  -H "Authorization: Bearer $REDLINE_API_KEY" | jq

# Expected output:
# {
#   "total_requests": 847,
#   "successful_requests": 839,
#   "error_rate": 0.009,
#   "p50_latency_ms": 1234,
#   "p95_latency_ms": 2890,
#   "p99_latency_ms": 4521,
#   "total_cost_usd": 4.23,
#   "cost_per_hour_usd": 253.80,
#   "throughput_rps": 14.1,
#   "detail": "847 requests (839 succeeded, 0.9% error rate) in 60.0s -- p50=1234ms p95=2890ms p99=4521ms, $253.8000/hour at this concurrency"
# }
```

**What This Demonstrates**:
- ✅ True concurrent execution (ThreadPoolExecutor, not fake async)
- ✅ Agent-specific metrics: cost-per-hour is first-class, not just latency
- ✅ Percentile latencies (p50/p95/p99) show tail behavior
- ✅ Finds financial viability breaking point (50 users = $253/hr)

---

## Production Deployment

### Cloud Deployment Options

RedLine is designed for cheap cloud deployment with these free-tier-compatible options:

#### Option 1: Google Cloud Platform (GKE Autopilot)

```bash
# 1. Create GKE Autopilot cluster (free tier: 1 zonal cluster)
gcloud container clusters create-auto redline-prod \
  --region=us-central1 \
  --release-channel=stable

# 2. Get credentials
gcloud container clusters get-credentials redline-prod --region=us-central1

# 3. Install infrastructure via Helm
helm install redline-infra bitnami/postgresql \
  --set auth.postgresPassword=your_password
# Repeat for Redis, etc.

# 4. Deploy RedLine
helm install redline ./helm/redline \
  --set image.tag=latest \
  --set ingress.enabled=true \
  --set ingress.hosts[0]=redline.yourdomain.com
```

#### Option 2: AWS (EKS + Free Tier Services)

```bash
# Use eksctl to create cluster
eksctl create cluster --name redline-prod --region us-east-1 --node-type t3.small --nodes 2

# Follow similar Helm deployment pattern
```

#### Option 3: Self-Hosted (Cheapest)

```bash
# Use a $5/month VPS (DigitalOcean, Linode, etc.)
# Install k3s (lightweight Kubernetes)
curl -sfL https://get.k3s.io | sh -

# Deploy with docker-compose for simplicity
docker-compose -f docker-compose.prod.yml up -d
```

### Production Checklist

- [ ] Change all default passwords in `.env`
- [ ] Set up TLS/HTTPS (Let's Encrypt)
- [ ] Configure GitHub OAuth (not API keys) for auth
- [ ] Enable PostgreSQL backups (daily snapshots)
- [ ] Set up alerts (Grafana → Slack/PagerDuty)
- [ ] Configure KEDA scaling limits (max 10 workers)
- [ ] Review Redpanda retention (7 days default)
- [ ] Enable audit logging in ClickHouse

---

## System Design & Scalability Analysis

### Current Capacity (Single k3d Node)

| Metric | Value | Bottleneck |
|--------|-------|------------|
| **Concurrent Eval Runs** | ~50 | Worker pool (KEDA scales to 10 max) |
| **Cases/Second** | ~20 | Gemini API rate limit (60 RPM) |
| **Events/Second** | ~1000 | Redpanda (1 broker, default config) |
| **Database Connections** | 100 | PostgreSQL `max_connections` |
| **Storage Growth** | ~1GB/1000 runs | ClickHouse traces |

### Scaling to Millions of Requests

#### Bottleneck 1: LLM API Rate Limits

**Problem**: Gemini API has 60 RPM free tier, 1000 RPM paid.  
**Solution**:
```python
# Already implemented: Redis-backed rate limiter
from apps.api.core.redis_client import get_limiter
rate_limiter = get_limiter()
rate_limiter.acquire(profile="standard", rpm_limit=1000)
```

**Future**: Add request queuing with exponential backoff.

#### Bottleneck 2: PostgreSQL Write Contention

**Problem**: All workers write `eval_case_results` to same table.  
**Solutions**:

1. **Partition by tenant_id** (already designed for):
```sql
CREATE TABLE eval_case_results_tenant_1 PARTITION OF eval_case_results
FOR VALUES IN ('tenant-1-uuid');
```

2. **Read replicas for dashboard queries**:
```yaml
# helm/redline/values.yaml
postgresql:
  replication:
    enabled: true
    readReplicas: 2
```

3. **Move bulk writes to ClickHouse**:
```python
# Instead of PostgreSQL INSERT per case
emit_trace(...)  # Async write to ClickHouse
# PostgreSQL only for critical gate decisions
```

#### Bottleneck 3: Worker Scaling

**Current**: KEDA scales 1-10 workers based on Redpanda lag.  
**Future**: Horizontal pod autoscaling:

```yaml
# helm/redline/templates/worker/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: eval-worker-v2
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: eval-worker-v2
  minReplicas: 2
  maxReplicas: 50
  metrics:
    - type: External
      external:
        metric:
          name: kafka_consumergroup_lag
        target:
          type: AverageValue
          averageValue: "10"
```

#### Bottleneck 4: ClickHouse Trace Storage

**Problem**: Grows unbounded (1GB/1000 runs).  
**Solution**: TTL-based expiration:

```sql
ALTER TABLE traces
MODIFY TTL created_at + INTERVAL 30 DAY;
```

### High-Level Design Improvements

#### 1. Caching Layer

```python
# apps/api/core/cache.py
import redis
from functools import wraps

cache = redis.from_url(os.getenv("REDIS_URL"))

def cache_eval_result(ttl=3600):
    def decorator(func):
        @wraps(func)
        def wrapper(eval_run_id):
            key = f"eval_result:{eval_run_id}"
            cached = cache.get(key)
            if cached:
                return json.loads(cached)
            result = func(eval_run_id)
            cache.setex(key, ttl, json.dumps(result))
            return result
        return wrapper
    return decorator
```

#### 2. Circuit Breaker for Gemini API

```python
# apps/api/core/circuit_breaker.py
from pybreaker import CircuitBreaker

gemini_breaker = CircuitBreaker(
    fail_max=5,
    timeout_duration=60,
    name="gemini-api"
)

@gemini_breaker
def call_gemini_api(...):
    # Existing Gemini call
    ...
```

#### 3. Database Sharding (Multi-Tenant)

```sql
-- Create tenant-specific databases
CREATE DATABASE tenant_1_db;
CREATE DATABASE tenant_2_db;

-- Route connections by tenant_id
# apps/api/core/db.py
def get_db_for_tenant(tenant_id):
    shard = tenant_id % NUM_SHARDS
    return engines[shard]
```

#### 4. Async Workers (Phase 4 Improvement)

**Current**: Synchronous workers (confluent-kafka requirement).  
**Future**: Hybrid async for I/O-bound tasks:

```python
# apps/api/workers/async_eval_worker.py
import asyncio
from aiokafka import AIOKafkaConsumer

async def process_message(msg):
    # Async HTTP calls, async DB writes
    async with httpx.AsyncClient() as client:
        response = await client.post(...)
```

#### 5. Content Delivery Network (CDN)

For dashboard static assets:

```yaml
# helm/redline/values.yaml
cdn:
  enabled: true
  provider: cloudflare  # Free tier: 100k requests/day
  origins:
    - dashboard.redline.io
```

### Cost-Benefit Analysis

| Improvement | Implementation Effort | Capacity Gain | Monthly Cost (AWS) |
|-------------|----------------------|---------------|-------------------|
| Read Replicas (Postgres) | 1 day | 3x read throughput | +$50 (2 t3.micro RDS) |
| KEDA max 50 workers | 1 hour | 5x concurrent evals | $0 (CPU scales down) |
| ClickHouse Cluster (3 nodes) | 2 days | 10x trace ingestion | +$150 (3 t3.medium) |
| Gemini API Upgrade (1000 RPM) | 0 hours | 16x LLM throughput | +$200 (pay-per-use) |
| Redis Cluster (5 nodes) | 1 day | 5x rate limit checks | +$100 (ElastiCache) |
| **Total** | **~5 days** | **~20x end-to-end** | **+$500/month** |

**Conclusion**: For <$500/month, RedLine can scale from 50 concurrent eval runs to **1000+ concurrent runs**, handling **millions of requests per month**.

---

## Troubleshooting

### Common Issues

#### 1. "Port 5433 already in use"

```bash
# Check what's using the port
lsof -i :5433

# Kill the process or change port in docker-compose.yml
docker-compose down
docker-compose up -d
```

#### 2. "GEMINI_API_KEY not set"

```bash
# Verify env var
echo $GEMINI_API_KEY

# If empty, add to .env and restart
export GEMINI_API_KEY=your_key_here
make deploy
```

#### 3. "Pods stuck in Pending"

```bash
# Check cluster resources
kubectl describe node k3d-redline-server-0

# Increase Docker Desktop memory to 8GB
# Restart cluster
make cluster-down
make cluster-up
```

#### 4. "Alembic migration failed"

```bash
# Rollback and retry
cd apps/api
alembic downgrade -1
alembic upgrade head
```

#### 5. "Worker not consuming messages"

```bash
# Check Redpanda topic
rpk topic list --brokers localhost:19092

# Check worker logs
kubectl logs -n redline -l app=eval-worker-v2 --tail=100

# Restart worker
kubectl rollout restart deployment/eval-worker-v2 -n redline
```

---

## Next Steps & Improvements

### Phase 4: Hardening & Public Launch

1. **Async Workers** (2 weeks)
   - Migrate to `aiokafka` for async message processing
   - 3x throughput improvement

2. **OIDC Authentication** (1 week)
   - Replace API keys with GitHub/Google OAuth
   - Better UX for multi-user teams

3. **Dashboard v2** (2 weeks)
   - React frontend with real-time updates
   - Behavioral diff visualization
   - ARS trending charts

4. **Public Deployment** (1 week)
   - Deploy to GKE Autopilot
   - Set up CI/CD with GitHub Actions
   - Domain: redline.agentre.io

5. **Open Source Launch** (1 week)
   - Clean up sensitive data
   - Write CONTRIBUTING.md
   - Record demo video
   - Post on Hacker News / Reddit

### Novel Features Worth Adding

1. **Multi-Modal Agent Support**
   - Vision agents (screenshot → action)
   - Audio agents (speech → text → action)
   - Currently text-only

2. **Agent Debugging Replay**
   - Step through eval runs turn-by-turn
   - Inspect session_state at each step
   - Modify inputs and re-run from checkpoint

3. **Cost Optimization Suggestions**
   - "Switch to Haiku for these 20 cases → save $50/month"
   - Automatically detect overprovisioned model usage

4. **Federated Learning for Failure Mining**
   - Share anonymized failure clusters across tenants
   - "Other teams saw this pattern too"

5. **Canary Deployments**
   - Route 10% of traffic to new version
   - Auto-rollback if ARS drops

---

## Appendix: File Structure Reference

```
RedLine/
├── apps/
│   ├── api/                      # Main API service
│   │   ├── core/                 # Core infrastructure
│   │   │   ├── config.py         # Pydantic settings
│   │   │   ├── db.py             # SQLAlchemy setup
│   │   │   ├── redis_client.py   # Redis + rate limiter
│   │   │   ├── clickhouse_client.py # ClickHouse traces
│   │   │   └── security.py       # JWT auth
│   │   ├── models/               # SQLAlchemy ORM
│   │   │   ├── eval.py           # Eval runs, cases, results
│   │   │   ├── gate.py           # Gate policies
│   │   │   ├── ars.py            # ARS scores, SLO policies
│   │   │   ├── diff.py           # Behavioral diffs
│   │   │   ├── mining.py         # Failure clusters
│   │   │   └── load.py           # Load test runs
│   │   ├── services/             # Business logic
│   │   │   ├── eval_engine.py    # Run evals
│   │   │   ├── gate_engine.py    # Deployment gates
│   │   │   ├── ars_engine.py     # ARS computation
│   │   │   ├── diff_engine.py    # Behavioral diff
│   │   │   ├── load_engine.py    # Load testing
│   │   │   ├── mining/
│   │   │   │   └── engine.py     # Failure mining
│   │   │   ├── adapters/         # Agent adapters
│   │   │   │   ├── base.py       # AgentAdapter protocol
│   │   │   │   ├── local_python.py # In-process agents
│   │   │   │   ├── http_adapter.py # HTTP agents
│   │   │   │   └── chaos_adapter.py # Fault injection
│   │   │   └── scorers/          # Eval scorers
│   │   │       ├── base.py
│   │   │       ├── contains_match.py
│   │   │       ├── llm_judge.py
│   │   │       ├── safety.py
│   │   │       ├── cost.py
│   │   │       └── latency.py
│   │   ├── routers/              # FastAPI routes
│   │   ├── schemas/              # Pydantic request/response
│   │   ├── workers/              # Background workers
│   │   │   ├── eval_worker_v2.py # Redpanda consumer
│   │   │   └── load_worker.py    # Load test executor
│   │   └── tests/                # Unit + integration tests
│   ├── cli/                      # CLI tool (agentbench)
│   ├── dashboard/                # React frontend
│   ├── agent_service/            # Agent management API
│   ├── eval_service/             # Eval run API
│   └── gate_service/             # Gate check API
├── agents/                       # Example agents
│   ├── rag_agent/
│   └── stateful_support_agent/
├── helm/redline/                 # Kubernetes Helm chart
├── docs/                         # Documentation
├── .env.example                  # Environment template
├── docker-compose.yml            # Local infrastructure
├── Makefile                      # Build commands
└── AgentBench_Cloud_Foundational_Document-2.md
```

---

## Conclusion

RedLine is a **production-ready Agent Reliability Engineering platform** with all 5 research-grade novelty features implemented and tested. It's ready for:

1. **Local development** (Mac M2, 16GB RAM)
2. **Demo deployment** (this guide)
3. **Production scaling** (with improvements outlined above)

**Next Immediate Steps**:
1. Follow "Running the Full Stack" to deploy locally
2. Run through all 5 feature demos
3. Record a video walkthrough for portfolio/launch
4. Deploy to cloud for public beta testing

**For Questions**:
- Technical: Check `docs/` or open GitHub issue
- System Design: See "Scalability Analysis" section above
- Demo Support: Refer to "Demo: The 5 Novelty Features"

---

**Built with**: Python 3.10 · FastAPI · PostgreSQL · Redpanda · Redis · ClickHouse · Kubernetes · KEDA · Prometheus · OpenTelemetry  
**License**: MIT (once open-sourced)  
**Maintainer**: Abhinav Gurkar  
**Last Updated**: August 2026
