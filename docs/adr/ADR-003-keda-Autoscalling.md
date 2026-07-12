# ADR-003: Use KEDA for eval worker autoscaling on Redpanda consumer lag

**Status**: Accepted  
**Date**: 2026-07-08  
**Context**: Phase 2 introduces Kubernetes (k3d). The eval worker must scale
horizontally under load. Two options: CPU-based HPA (built-in), or KEDA with
a Kafka consumer lag trigger.

## Decision

Use **KEDA** with a Kafka consumer lag trigger for the eval worker.
Use CPU-based HPA for the stateless API services (eval_service, agent_service,
gate_service).

## Why CPU HPA is the wrong metric for the eval worker

The eval worker spends ~95% of execution time blocked on network I/O waiting
for Gemini API responses and Postgres writes. CPU utilization stays below 10%
even when the worker is fully saturated. CPU-based HPA never triggers under
this workload regardless of queue depth.

## Why consumer lag is the correct metric

Consumer lag (unconsumed messages in eval.requested ahead of the eval-worker
consumer group) is a direct measure of unprocessed work. When lag grows, scale
up. When lag is zero, all work is done, scale down. This is the same scaling
signal used by Kafka Streams, AWS Lambda with SQS, and Cloud Run with Pub/Sub.

## Why KEDA specifically

KEDA integrates with Kubernetes HPA via the custom metrics API. It does not
replace HPA -- it feeds it the correct signal. The ScaledObject CRD is the
only new resource type. The Deployment itself is unchanged.

## cooldownPeriod: 300 seconds

Scaling DOWN is dangerous for in-flight eval jobs. The 300s cooldown gives
running jobs time to complete before KEDA removes a replica. Phase 4 should
add a SIGTERM handler that lets the current eval job finish before pod exit.

## Future review trigger

Re-evaluate if: eval jobs become sub-second, multiple brokers are deployed
(partition count affects per-replica lag), or multiple worker types are
introduced (each gets its own ScaledObject and topic).