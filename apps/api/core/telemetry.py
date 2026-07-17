"""
Telemetry (Phase 2 Section 8 -- Holy Grail §10.11).

Three pillars:
  1. Metrics  -- prometheus-client (already a transitive dep, no new package).
                 HTTP middleware records requests/sec, latency, error rates.
                 Custom eval metrics track business-level signals.
                 /metrics endpoint exposed on every service for Prometheus scraping.
  2. Logs     -- structured JSON stdout; Promtail collects into Loki automatically.
  3. Traces   -- OTel SDK with console exporter (Phase 2). Traces appear in pod logs
                 (Loki-indexed). Phase 3: swap for OTLPSpanExporter -> Grafana Tempo.

Design note: prometheus-fastapi-instrumentator 8.x requires starlette>=1.0.0 but
fastapi==0.115.6 ships starlette 0.41.x. Rather than introduce a version conflict,
we use prometheus-client directly. This gives us precise control over exactly the
metrics the Holy Grail doc specifies and avoids any dependency churn.
"""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import get_tracer_provider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode

# ─── Structured logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("redline")


# ─── HTTP metrics (Holy Grail §10.11: requests/sec, latency, error rates) ────

HTTP_REQUESTS_TOTAL = Counter(
    "redline_http_requests_total",
    "Total HTTP requests",
    ["service", "method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "redline_http_request_duration_seconds",
    "HTTP request duration",
    ["service", "method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
)


# ─── Eval business metrics ────────────────────────────────────────────────────

EVAL_RUNS_TOTAL = Counter(
    "redline_eval_runs_total",
    "Total eval runs by final status",
    ["status"],
)

GATE_DECISIONS_TOTAL = Counter(
    "redline_gate_decisions_total",
    "Gate engine decisions",
    ["passed"],
)

EVAL_CASE_RESULTS_TOTAL = Counter(
    "redline_eval_case_results_total",
    "Eval case results by outcome",
    ["passed"],
)

EVAL_RUN_DURATION_SECONDS = Histogram(
    "redline_eval_run_duration_seconds",
    "End-to-end eval run duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

EVAL_CASE_COST_USD = Histogram(
    "redline_eval_case_cost_usd",
    "Per-case LLM cost in USD",
    buckets=[0.0001, 0.001, 0.01, 0.1, 1.0],
)


# ─── OpenTelemetry ────────────────────────────────────────────────────────────

def _setup_tracing(service_name: str):

    if isinstance(get_tracer_provider(), TracerProvider):
        return trace.get_tracer(service_name)

    resource = Resource.create(
        {
            "service.name": service_name,
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter())
    )
    trace.set_tracer_provider(provider)

    return trace.get_tracer(service_name)


tracer = None


# ─── FastAPI wiring ───────────────────────────────────────────────────────────

def setup_metrics(app: FastAPI, service_name: str) -> None:
    """
    Adds:
      - HTTP middleware that records requests/sec, latency, status codes
      - GET /metrics endpoint for Prometheus scraping
    Call once in each service's main.py.
    """
    global tracer

    if tracer is None:
        tracer = _setup_tracing(service_name)

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        # Skip /metrics and /health from being tracked (noise, not signal)
        if request.url.path in ("/metrics", "/health"):
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        HTTP_REQUESTS_TOTAL.labels(
            service=service_name,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            service=service_name,
            method=request.method,
            path=request.url.path,
        ).observe(duration)

        return response

    @app.get("/metrics", include_in_schema=False)
    def _metrics_endpoint():
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    logger.info(
    "Telemetry initialized",
    extra={
        "service": service_name,
        "metrics": "/metrics",
    },
)
    