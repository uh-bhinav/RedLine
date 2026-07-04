# ADR-001: Use confluent-kafka as the Kafka/Redpanda client

**Status**: Accepted  
**Date**: 2026-07-03  
**Context**: Phase 2 introduces Redpanda as the event bus. Two Python clients exist for
the Kafka-compatible API: `confluent-kafka` (librdkafka-backed, synchronous) and
`aiokafka` (asyncio-native).

## Decision

Use `confluent-kafka==2.14.2`.

## Rationale

The entire Phase 2 execution model is synchronous:

- The eval worker is a blocking poll loop (`while True: claim → process → commit`)
- `eval_engine.run_eval()` is synchronous — it calls the agent, waits for results,
  writes DB rows, and returns. There is no async boundary in this path.
- SQLAlchemy 2.0 is used in its synchronous ORM mode (`Session`, not `AsyncSession`)
- `confluent-kafka` is backed by librdkafka — the same C library that powers Confluent
  Cloud, production Kafka deployments at scale, and Redpanda's own client tooling.
  It is not an experimental choice.

Introducing `aiokafka` in this context would require either (a) running an event loop
inside a sync thread via `asyncio.run()` — which adds overhead and complexity for zero
benefit — or (b) rewriting the entire eval engine and SQLAlchemy layer as async, which
is a larger architectural change than warranted by the current bottlenecks.

## What this is NOT

This is not a "temporary convenience choice" or a shortcut. The synchronous worker
model is deliberate: horizontal scaling is achieved through Kafka consumer groups
(multiple worker processes consuming from the same topic), not through in-process
concurrency. A single synchronous consumer process claiming one job at a time and
processing it end-to-end is the correct architecture for a workload where each job
takes 10–30 seconds and has strong ordering/correctness requirements.

## Future review trigger

Re-evaluate this decision **only if** one of the following conditions becomes true:

1. The worker execution model fundamentally changes to async (e.g., eval engine
   switches to `AsyncSession` and all LLM calls become `await`-able coroutines)
2. A single worker process must multiplex large numbers of concurrent lightweight
   evaluations where I/O wait dominates (e.g., sub-second tool calls at high volume)
3. A load test demonstrates that synchronous consumer throughput is the actual
   bottleneck (not LLM latency, not DB write latency, not network — but the
   consumer library itself)

None of these conditions currently apply.

## Consequences

- `confluent-kafka` is added to `apps/api/requirements.txt`
- `RedpandaJobQueue` uses the synchronous `Producer`/`Consumer` API
- Workers remain single-threaded processes; horizontal scaling is via process count
- Future async migration would require replacing `confluent-kafka` with `aiokafka`
  and rewriting the eval engine — but the `JobQueue` STABLE CONTRACT means the
  interface stays identical; only the implementation changes