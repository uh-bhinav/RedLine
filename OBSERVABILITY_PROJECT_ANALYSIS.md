# Observability Implementation Analysis — RedLine

Code-first, not theory-first. Every entry is: **concept → exact file/line → actual code → runtime behavior → why**. Theory of OpenTelemetry/Prometheus/Grafana/Loki/Tempo is assumed learned elsewhere — this document only maps that theory onto what this specific repository does.

---

## 1. Implementation-Level Classification

Per the 8-level test (dependency exists → configured → initialized → generates telemetry → exported → reaches destination → Grafana consumes it → actually useful at runtime), here is where each technology actually lands. **This table is the single most important finding in this document — read it before anything else.**

| Technology | Status | One-line reason |
|---|---|---|
| **OpenTelemetry (tracing)** | **IMPLEMENTED** (with a bounded scope) | Manual `TracerProvider` + `OTLPSpanExporter` → Tempo, real spans with attributes/exceptions, actually emitted by every eval run. `opentelemetry-instrumentation-fastapi` is a declared dependency but never imported — auto-instrumentation is **not** wired up (§2.1). |
| **Prometheus (metrics)** | **PARTIALLY IMPLEMENTED — split outcome** | The three FastAPI *services* (`eval_service`, `agent_service`, `gate_service`) correctly expose `/metrics` and are genuinely scrapable. The *business* metrics (eval run counts, case results, drift scores) are defined and really incremented — but they run inside the **worker** and **drift-scheduler** processes, which **never expose a `/metrics` endpoint or call `start_http_server()`**. Those metrics exist in memory and die with the process, invisible to any scraper. This is the most important, least obvious finding in this repo (§7). |
| **Grafana** | **CONFIGURED BUT UNUSED (locally) / NOT AUTOMATED (k3d)** | No Grafana container anywhere in `docker-compose.yml`. Only reachable via an optional, manual `make monitoring-install` Helm step in k3d. Even there, connecting Grafana to Tempo is an explicitly documented **manual, one-time UI step** — no datasource provisioning file exists in the repo (§9). No dashboard JSON, no alert rule, found anywhere. |
| **Loki** | **CONFIGURED BUT UNUSED** | Installed only via the optional `make monitoring-install` Helm target (`grafana/loki-stack` chart). No `docker-compose.yml` service. No custom Promtail scrape config, no log-label configuration, found anywhere in the repo — whatever labels/behavior exist are entirely the Helm chart's defaults, never customized here. The application does produce structured JSON logs to stdout (§2.4) that *would* be Loki-ingestible if Promtail were actually deployed, but nothing in this repo proves that pipeline was ever run end-to-end. |
| **Tempo** | **IMPLEMENTED** | Real `tempo` service in `docker-compose.yml`, real config file (`infra/tempo.yaml`), real OTLP gRPC receiver on `:4317`, verified reachable via a documented `curl` against its query API (§9). This is the one piece of the five that is genuinely running, receiving real data, and documented as manually verified against live infrastructure. |

**Read this as:** RedLine's observability story is real for distributed tracing (OTel → Tempo) and real for HTTP-layer metrics on the three API services, but the metrics/logging/dashboarding story around Grafana and Loki is scaffolding — present in tooling and Helm charts, never wired into an automatic, running pipeline in this repository as it stands.

---

## 2. Exact Code Locations

### 2.1 OpenTelemetry — TracerProvider + OTLPSpanExporter Setup

**File:** `apps/api/core/telemetry.py`
**Function:** `_setup_tracing(service_name: str)`
**Lines:** 103-130

```python
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
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=_settings.otel_exporter_endpoint, insecure=True, timeout=5)
        )
    )
    trace.set_tracer_provider(provider)

    return trace.get_tracer(service_name)


tracer = _setup_tracing("redline")  # default tracer for non-service code
```

**What it does:** builds one `TracerProvider` with a single `Resource` attribute (`service.name`), attaches a `BatchSpanProcessor` wrapping an `OTLPSpanExporter` pointed at `_settings.otel_exporter_endpoint` (gRPC, `insecure=True` — no TLS), sets it as the global tracer provider, and returns a `Tracer` bound to `"redline"`. This module-level line (`tracer = _setup_tracing("redline")`) runs once, at import time, giving every module that does `from apps.api.core.telemetry import tracer` the same tracer instance.

**The idempotency guard (line 105):** `if isinstance(get_tracer_provider(), TracerProvider): return trace.get_tracer(service_name)` — OTel's global tracer provider defaults to a no-op `ProxyTracerProvider` until something sets a real one; once a real `TracerProvider` is installed, calling `_setup_tracing()` again just returns a tracer from the *existing* provider instead of building (and registering) a second one. This matters because `_setup_tracing("redline")` runs at import time regardless of which service imports `telemetry.py`, so this guard prevents duplicate provider registration if the module is somehow re-executed.

**`insecure=True` and `timeout=5`:** no TLS to the OTLP receiver (matches Tempo's config in `infra/tempo.yaml`, which only declares a plain gRPC endpoint, no TLS). `timeout=5` is a deliberate, commented choice (lines 117-122): *"an unreachable Tempo (no infra running, or a unit-test process) must fail an export attempt in bounded time, not hang on gRPC's default connection/retry behavior. Tracing must never be load-bearing — the same principle `emit_trace()`'s non-fatal try/except already applies to ClickHouse writes."*

**Config backing it:** `otel_exporter_endpoint` — a `Settings` field (in `apps/api/core/config.py`, not shown here but confirmed present), sourced from `OTEL_EXPORTER_ENDPOINT` env var, set to `http://tempo:4317` in every service's `docker-compose.yml` block (see §5).

**Not present:** `opentelemetry-instrumentation-fastapi` (`requirements.txt:38`, `pyproject.toml:67`) is declared as a dependency but grepping the entire `apps/` tree for `FastAPIInstrumentor` or any `opentelemetry.instrumentation` import returns **zero matches**. Auto-instrumentation (which would automatically create a span per incoming HTTP request, propagate `traceparent` headers, etc.) is not wired up anywhere — every span in this codebase is manually created via `tracer.start_as_current_span(...)`.

---

### 2.2 OpenTelemetry — Manual Spans in the Eval Engine

**File:** `apps/api/services/eval_engine.py`
**Function:** `run_eval(eval_run_id)`
**Lines:** 116-120 (outer span), 156-160 (nested span), 213-217 and 232-235 (exception recording)

```python
def run_eval(eval_run_id: uuid.UUID) -> None:
    with tracer.start_as_current_span(
        "eval_run",
        attributes={"eval_run_id": str(eval_run_id)},
    ) as span:
        ...
        span.set_attribute("case_count", len(cases))
        span.set_attribute("agent_version", agent_version.version_label)
        ...
        for i, case in enumerate(cases):
            with tracer.start_as_current_span(
                "eval_case",
                attributes={"case_key": case.case_key, "case_index": i},
            ):
                ...
```

Exception recording (line 217, inside a nested `try` around ARS computation):
```python
            except Exception as ars_exc:
                span.record_exception(ars_exc)
```

Exception recording on the run's own failure path (line 235):
```python
        except Exception as exc:
            ...
            # Record the ACTUAL exception. This previously passed a bare
            # `Exception()`, which produced a span with an empty error and threw away
            # the only diagnostic the trace carried.
            span.record_exception(exc)
```

**What it does:** one `eval_run` span per `run_eval()` call, with a nested `eval_case` child span per test case — this produces a real parent/child trace tree in Tempo: one trace per eval run, with one child span per case inside it, each with `case_key`/`case_index` attributes for filtering. `span.set_attribute(...)` adds `case_count`/`agent_version` to the parent span after they're known (attributes can be added after span creation, not just at creation time — both patterns are used here: `attributes={...}` at creation for the nested case spans, `.set_attribute()` after creation for the parent). `span.record_exception(exc)` attaches exception details (type, message, stacktrace) to the span without necessarily ending the span in an error state on its own — see the gap noted below.

**Real, documented bug fix (lines 232-234's own comment):** an earlier version of this code called `span.record_exception(Exception())` — a bare, empty exception object — which produced a span carrying no actual diagnostic information. Fixed to pass the real caught `exc`.

**A gap worth knowing if asked to critique this:** `record_exception()` is called on both error paths, but `span.set_status(StatusCode.ERROR, ...)` is **never called anywhere in this codebase** — grepped the whole `apps/api` tree for `StatusCode`/`set_status`/`Status(` and the only hit is the `from opentelemetry.trace import StatusCode` import itself in `telemetry.py:37`, which is imported but never used. This means: a failed eval run's span carries an attached exception record, but the span's own **status** is never explicitly set to `ERROR` — by OTel semantics, an unset status defaults to `UNSET`, not `ERROR`, so a Tempo/Grafana query or dashboard filtering specifically on span *status* (rather than presence of an exception event) would not surface these failed runs. `StatusCode` and `Status` are imported at the top of `telemetry.py` (lines 36-37) but neither is ever instantiated or applied to a span anywhere in the repository — dead imports pointing at an incomplete implementation.

**Runtime behavior:** each `run_eval()` call produces one trace visible in Tempo (queryable via `service.name=redline`, per the documented verification command in §9), with span attributes and any exceptions attached, but without a reliable `ERROR` status marker to filter on.

---

### 2.3 Prometheus — Metric Definitions

**File:** `apps/api/core/telemetry.py`
**Lines:** 54-98

```python
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
```

**Types used:** `Counter` (4 instances) and `Histogram` (3 instances). **`Gauge` and `Summary` are not used in this file** — `Gauge` does appear elsewhere (§2.6, drift metrics). No `Summary` metric exists anywhere in the repository.

**Label cardinality note worth being able to discuss:** `HTTP_REQUESTS_TOTAL` and `HTTP_REQUEST_DURATION_SECONDS` both label on raw `path` (line 156-157 of the middleware, §2.5) — for a path containing a UUID (e.g., `/eval-runs/{eval_run_id}`), this means every distinct `eval_run_id` ever requested creates a new label combination, an unbounded-cardinality time series. Not flagged or handled anywhere in this codebase (no path-templating/normalization step before labeling) — a real, findable "would you change anything" answer.

**Histogram bucket choices are business-aware, not generic:** `EVAL_RUN_DURATION_SECONDS`'s buckets (`[1, 5, 10, 30, 60, 120, 300]`) span seconds to 5 minutes, matching real eval-run durations, not a generic web-latency bucket scale; `EVAL_CASE_COST_USD`'s buckets (`[0.0001, 0.001, 0.01, 0.1, 1.0]`) span sub-cent to a dollar, matching realistic per-case LLM costs. `HTTP_REQUEST_DURATION_SECONDS`'s buckets (`[0.01, ..., 10.0]`) are the more conventional web-latency shape. Good evidence of deliberate metric design, not copy-pasted defaults, if asked.

**`GATE_DECISIONS_TOTAL` is defined but never incremented anywhere in the repository** — confirmed by grepping every `.py` file for `GATE_DECISIONS_TOTAL`; the only match is its own definition at line 76. This metric would appear in `/metrics` output (Prometheus client libraries expose a metric at its initial zero value even before any `.inc()` call), but its value would be permanently and misleadingly `0`, forever, never reflecting a real gate decision. This is the single cleanest "configured but unused" example in the whole document.

---

### 2.4 Structured Logging (the "Logs" pillar's application-side half)

**File:** `apps/api/core/telemetry.py`
**Lines:** 45-49

```python
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("redline")
```

**What it does:** configures Python's root logger with a format string that happens to produce valid-shaped JSON per line (`{"time": ..., "level": ..., "logger": ..., "msg": ...}`), writing to stdout by default (`logging.basicConfig` with no `filename`/`handlers` argument uses `StreamHandler` → stderr actually, by Python's default — worth double-checking in a real run, but the important architectural point stands regardless of stdout vs stderr: it's one line per log record, JSON-shaped). This is the half of "structured JSON logging" that lives in this repository — it is what a log-collection agent (Promtail, Fluent Bit, etc.) would need to already be true for Loki ingestion to work well.

**What does NOT exist here:** any actual log shipper. No Promtail config file, no Fluent Bit config, no `docker-compose.yml` service for either, anywhere in the repository. The comment at the top of `telemetry.py` (line 9) states the *intent* — `"Promtail collects into Loki automatically"` — but nothing in this repo instantiates that collection pipeline; it would only exist if `make monitoring-install`'s `loki-stack` Helm chart (which does bundle a default Promtail subchart) were actually run against a live cluster, and even then, this repo shows no evidence that pipeline was ever exercised end-to-end (no dashboard, no LogQL query, no screenshot/verification doc referencing it — contrast directly with Tempo, §9, which *does* have a documented verification `curl`).

---

### 2.5 Prometheus — HTTP Middleware and `/metrics` Endpoint

**File:** `apps/api/core/telemetry.py`
**Function:** `setup_metrics(app: FastAPI, service_name: str)`
**Lines:** 135-181

```python
def setup_metrics(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
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
```

**Call sites (all three, verified — grepped for `setup_metrics`):**
- `apps/eval_service/main.py:17,33` — `from apps.api.core.telemetry import setup_metrics` / `setup_metrics(app, "eval-service")`
- `apps/agent_service/main.py:16,32` — same pattern, `"agent-service"`
- `apps/gate_service/main.py:17,33` — same pattern, `"gate-service"`

**`apps/api/main.py` (the monolith used by the README's own Quickstart) does NOT call `setup_metrics()` anywhere** — confirmed, grepped the file directly. The monolith has a `/health` endpoint and the Redis rate-limit middleware (covered in the separate Redis analysis), but **no `/metrics` endpoint, no HTTP metrics middleware, and no OpenTelemetry instrumentation of any kind.** Anyone running the platform via the README's day-to-day monolith path gets zero Prometheus/OTel telemetry; only the three decomposed microservices (`eval_service`/`agent_service`/`gate_service`, used in the Phase 2+ Docker Compose / k3d path) get instrumented.

**Runtime behavior:** `generate_latest()` (from `prometheus_client`) serializes the **entire process-global default registry** — every `Counter`/`Histogram`/`Gauge` object that has been instantiated anywhere in that process's Python interpreter, not just the ones defined in `telemetry.py`. This matters directly for §7's finding: if `eval_engine.py`'s `EVAL_RUNS_TOTAL` etc. were ever incremented inside the *same process* that also called `setup_metrics()`, they'd show up here automatically (Prometheus client's registry is a module-level singleton, not something you have to explicitly register each metric into). The reason they don't show up is that they're incremented in a **different process** (the worker) than the one exposing `/metrics` (the API service) — see §7.

---

### 2.6 Prometheus — Drift Detection Metrics (Counter + Gauge)

**File:** `apps/api/services/drift/runner.py`
**Lines:** 20, 39-49 (definitions), 173-176 (the Gauge update)

```python
from prometheus_client import Counter, Gauge
...
DRIFT_CHECK_RUNS_TOTAL = Counter(
    "redline_drift_check_runs_total",
    "Total scheduled drift check runs",
    ["status"],  # "ok" | "error"
)

DRIFT_SCORE_DELTA = Gauge(
    "redline_drift_score_delta",
    "Latest pass_rate delta from baseline (negative = regression)",
    ["agent_version_id", "suite_id"],
)
```

```python
    # Update Prometheus gauge so Grafana can alert
    DRIFT_SCORE_DELTA.labels(
        agent_version_id=str(agent_version.id),
        suite_id=str(suite.id),
    ).set(result.delta)
```

**What it does:** `DRIFT_SCORE_DELTA` is this repository's **only `Gauge`** — appropriate because a "current delta from baseline" is a point-in-time value that can go up or down, unlike a `Counter`, which can only increase. It's labeled by `(agent_version_id, suite_id)`, so each distinct agent-version/suite pair gets its own tracked gauge value, set (not incremented) on every drift check.

**Where this runs:** the module docstring (`drift/runner.py:1-11`) states explicitly: *"This runs in the `drift_scheduler` process, NOT in the API server and NOT in the eval worker — it is its own long-lived process with its own DB session lifecycle."* This is a **fourth** process in the system, separate from the three API services and the two Redpanda-consumer workers, and it — like the eval worker — never calls `setup_metrics()` or `start_http_server()` anywhere (confirmed by grep). Same fate as the eval-business metrics: real Prometheus objects, really updated, never exposed for scraping (§7).

---

### 2.7 ClickHouse `emit_trace()` — a Second, Separate, Non-OTel "Tracing" System

**File:** `apps/api/core/clickhouse_client.py`
**Function:** `emit_trace(...)`
**Lines:** 134-176

```python
def emit_trace(
    *,
    eval_run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    event_type: str,
    case_key: str = "",
    turn_index: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    passed: bool | None = None,
    detail: str = "",
) -> None:
    try:
        ch = get_clickhouse()
        ch.execute(
            """
            INSERT INTO traces
            (trace_id, eval_run_id, tenant_id, event_type, case_key,
             turn_index, latency_ms, cost_usd, passed, detail, created_at)
            VALUES
            """,
            [{...}],
        )
    except Exception as e:
        print(f"[trace] write failed (non-fatal): {e}")
```

**Do not conflate this with OpenTelemetry — it's a completely separate, custom system, despite the name "trace":** this writes one row per lifecycle event (`run_started`, `turn_completed`, `run_completed`) into a ClickHouse table called `traces`, using a hand-rolled `trace_id = uuid.uuid4()` (line 162) that has **no relationship whatsoever** to OTel's actual trace/span IDs generated by `tracer.start_as_current_span(...)` in §2.2. It is application-level structured event logging into an analytics database, not distributed tracing — no span context propagation, no parent/child relationships beyond what the `eval_run_id`/`case_key`/`turn_index` columns encode manually.

**Table schema** (`clickhouse_client.py:51-65`):
```sql
CREATE TABLE IF NOT EXISTS traces (
    trace_id     UUID,
    eval_run_id  UUID,
    tenant_id    UUID,
    event_type   String,
    case_key     String,
    turn_index   UInt8,
    latency_ms   UInt32,
    cost_usd     Float32,
    passed       Nullable(UInt8),
    detail       String,
    created_at   DateTime64(3, 'UTC')
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, eval_run_id, created_at)
```

**Error handling — this function catches internally, unlike everything in §2.1-2.6:** the whole body is wrapped in `try/except Exception as e: print(...)` (lines 152,175-176). This means every call site (`eval_engine.py:143,180,200,237-249`) is already safe without needing its own additional try/except — the non-fatal guarantee lives inside `emit_trace()` itself, not at each call site. (This resolves what could look like a Rule-4 violation if you only look at the call sites in isolation — the safety net is one level down, inside the function.)

**Consumed by:** `apps/api/routers/dashboard.py`'s `run_traces()` endpoint (`GET /dashboard/runs/{eval_run_id}/traces`, lines 363+) — RedLine's **own dashboard router queries this table directly with raw SQL**, not through Grafana. This is a self-built trace-timeline view, independent of the Tempo/Grafana pipeline entirely.

---

### 2.8 OTel in Tests — Provider Shutdown Hygiene

**File:** `apps/api/tests/conftest.py`
**Lines:** ~30-40 (based on grep matches)

```python
from opentelemetry import trace
...
provider = trace.get_tracer_provider()
```

**What it does (per the file's own extensive header comment, lines 1-24):** a `pytest_sessionfinish` hook that explicitly shuts down the global `TracerProvider` at the end of a test session, flushing any queued spans in the `BatchSpanProcessor`'s background daemon thread before the process exits. The comment documents real history: this used to matter more when the exporter was `ConsoleSpanExporter` (writing to `sys.stdout`, which pytest can capture/close before a background thread finishes writing, causing a crash) — now that Phase 5.1 uses `OTLPSpanExporter` (network-based, not tied to a Python file object), the crash risk that motivated the original fix is gone, but the shutdown call is kept anyway as general `BatchSpanProcessor` hygiene (any exporter's background thread should be flushed before the interpreter exits, not just to work around the old bug).

**Runtime behavior:** without this, spans queued in the batch processor's buffer at the moment a test process exits could simply be dropped, never reaching Tempo — this hook guarantees a clean flush.

---

## 3. Architecture Diagram — Only Components Actually Present

```
                    eval_service / agent_service / gate_service
                    (apps/eval_service, apps/agent_service, apps/gate_service)
                                   |
                    setup_metrics(app, "<service-name>")
                                   |
                    +--------------+--------------+
                    |                             |
         HTTP middleware records            GET /metrics
         HTTP_REQUESTS_TOTAL,                (prometheus_client.generate_latest())
         HTTP_REQUEST_DURATION_SECONDS              |
                                                     ↓
                                          (scraped only if something
                                           scrapes it — see §7:
                                           locally, NOTHING does;
                                           in k3d, the ServiceMonitor does,
                                           IF kube-prometheus-stack was
                                           installed via `make monitoring-install`)


    eval_worker.py / eval_worker_v2.py / drift_scheduler process
    (apps/api/workers/, apps/api/services/drift/runner.py)
                    |
         run_eval() / run_drift_check()
                    |
        +-----------+-----------+---------------------------+
        |                       |                           |
   tracer.start_as_current_span   EVAL_RUNS_TOTAL.inc()  emit_trace()
   ("eval_run", "eval_case")      etc. (§2.3, §2.6)      (§2.7 — NOT OTel)
        |                       |                           |
        ↓                       ↓                           ↓
   OTLPSpanExporter        process-local Prometheus     ClickHouse
   (BatchSpanProcessor)    registry — NEVER SCRAPED      "traces" table
        |                  (no /metrics, no                    |
        ↓                   start_http_server                   ↓
   Grafana Tempo            anywhere in this process)   apps/api/routers/
   (docker-compose.yml,                                 dashboard.py's
    infra/tempo.yaml)                                   run_traces()
        |                                                (RedLine's own
        ↓                                                 dashboard UI,
   Grafana (Tempo datasource,                             NOT Grafana)
   MANUAL one-time setup only —
   no provisioning file exists,
   Grafana itself not in docker-compose.yml,
   only reachable via optional
   `make monitoring-install` + k3d)


   Structured JSON stdout logs (every process, via logging.basicConfig)
                    |
                    ↓
        Promtail — NOT PRESENT in docker-compose.yml
        (only exists as a bundled default subchart if
         `make monitoring-install`'s loki-stack Helm
         chart is actually installed into k3d)
                    |
                    ↓
        Loki — same conditional existence as above,
        never verified end-to-end anywhere in this repo
```

---

## 4. Data Flow — Per Pillar

### 4.1 Traces (the one pillar that's genuinely end-to-end)

```
run_eval(eval_run_id)                              eval_engine.py:116
   ↓
tracer.start_as_current_span("eval_run", ...)       eval_engine.py:117-120
   ↓ (one nested span per case)
tracer.start_as_current_span("eval_case", ...)      eval_engine.py:157-160
   ↓
span.set_attribute(...) / span.record_exception(...) eval_engine.py:136-137,217,235
   ↓
BatchSpanProcessor buffers the span in a background daemon thread
   ↓
OTLPSpanExporter.export()  → gRPC → OTEL_EXPORTER_ENDPOINT (http://tempo:4317)  telemetry.py:122
   ↓ (bounded, timeout=5s — fails fast if Tempo is unreachable)
Tempo's OTLP receiver (infra/tempo.yaml: distributor.receivers.otlp.protocols.grpc, :4317)
   ↓
Tempo ingester → local blocks storage (infra/tempo.yaml: storage.trace.backend: local)
   ↓
Verifiable via: curl "http://localhost:3200/api/search?tags=service.name%3Dredline&limit=5"
(documented in docs/infra-hardening.md — this is a genuinely verified path)
   ↓
Grafana (Tempo datasource) — ONLY if manually added (docs/infra-hardening.md's own words:
"No automated datasource provisioning is wired up ... One-time manual step")
```

### 4.2 Metrics — the working half (HTTP metrics on the 3 API services)

```
Incoming HTTP request to eval_service / agent_service / gate_service
   ↓
_metrics_middleware  telemetry.py:144-166
   ↓
HTTP_REQUESTS_TOTAL.labels(...).inc()
HTTP_REQUEST_DURATION_SECONDS.labels(...).observe(duration)
   ↓ (stored in this process's in-memory prometheus_client default registry)
GET /metrics  →  generate_latest()  telemetry.py:169-173
   ↓
Locally (docker-compose.yml): NOTHING scrapes this — no Prometheus container
exists in docker-compose.yml at all. The endpoint is live and correct; nothing
is polling it.
   ↓
In k3d (if `make monitoring-install` was run): kube-prometheus-stack's Prometheus,
via the ServiceMonitor (helm/redline/templates/base/servicemonitor.yaml,
port: "http", path: /metrics, interval: 15s) — this path IS wired up correctly
IF the optional Helm install step was actually performed.
```

### 4.3 Metrics — the broken half (business metrics defined but never scraped)

```
run_eval() executing inside eval_worker.py / eval_worker_v2.py (a SEPARATE process
from eval_service/agent_service/gate_service)
   ↓
EVAL_CASE_RESULTS_TOTAL.labels(...).inc()   eval_engine.py:177
EVAL_CASE_COST_USD.observe(...)             eval_engine.py:178
EVAL_RUNS_TOTAL.labels(...).inc()           eval_engine.py:197,230
EVAL_RUN_DURATION_SECONDS.observe(...)      eval_engine.py:198
   ↓ (stored in the WORKER PROCESS's own in-memory prometheus_client registry —
      a completely separate registry object from any FastAPI service's)
   ↓
DEAD END. This process never calls setup_metrics(), never calls
prometheus_client.start_http_server(), has no /metrics route, and
(confirmed) has no Kubernetes Service object in helm/redline/templates/worker/
for a ServiceMonitor to even target. These metric values live and die with
the worker process. Same fate for DRIFT_CHECK_RUNS_TOTAL / DRIFT_SCORE_DELTA
in the drift_scheduler process (drift/runner.py).
```

### 4.4 Logs

```
Every process: logging.basicConfig(...) at telemetry.py:45-48
   ↓
logger.info(...) calls throughout the codebase → stdout/stderr, one JSON-shaped
line per record
   ↓
Docker Compose: no log-shipping container exists. Whatever's in each container's
stdout stays in that container's stdout (retrievable via `docker logs`/
`docker compose logs`, nothing more automated).
   ↓
k3d, only if `make monitoring-install` was run: loki-stack's bundled Promtail
default DaemonSet would pick up container stdout automatically (that's the
chart's normal behavior) — but NOT customized, configured, or verified anywhere
in this repository. No LogQL query, no Loki datasource setup step, no
verification command exists for this pillar (contrast directly with Tempo's
documented curl verification in docs/infra-hardening.md).
```

---

## 5. Configuration Chain

| Setting | Template value | Loaded | Consumed |
|---|---|---|---|
| `OTEL_EXPORTER_ENDPOINT` | not in `.env.example` at all — only set per-service inside `docker-compose.yml` | `apps/api/core/config.py` `Settings.otel_exporter_endpoint` field | `telemetry.py:122`, `OTLPSpanExporter(endpoint=...)` |
| — (Compose) | `docker-compose.yml`: `eval_service`, `agent_service`, `gate_service` blocks all set `OTEL_EXPORTER_ENDPOINT: "http://tempo:4317"` | env var into container | same as above |
| — (Helm) | `helm/redline/values.yaml`: `infra.otelExporterEndpoint: "http://host.k3d.internal:4317"` | `configmap.yaml` | pods reach the same Compose-run Tempo via k3d's host DNS bridge (same pattern as Postgres/Redis/Redpanda/ClickHouse — no Tempo resource exists inside the Helm chart itself; confirmed no `tempo` directory under `helm/redline/templates/`) |

**No Prometheus/Grafana/Loki connection strings exist as application config anywhere** — these three are entirely infrastructure-side concerns (Helm chart installs, `kubectl port-forward`, manual Grafana UI clicks), never referenced by any `Settings` field or environment variable the application code reads.

---

## 6. Docker Compose — Exact Service Definition

**File:** `docker-compose.yml`
```yaml
tempo:
  image: grafana/tempo:2.5.0
  container_name: redline_tempo
  restart: unless-stopped
  command: ["-config.file=/etc/tempo.yaml"]
  volumes:
    - ./infra/tempo.yaml:/etc/tempo.yaml:ro
    - redline_tempo_data:/var/tempo
  ports:
    - "4317:4317"   # OTLP gRPC receiver
    - "3200:3200"   # Tempo query API (Grafana datasource target)
```

**`depends_on` from the three services — deliberately weak:** `eval_service`/`agent_service`/`gate_service` each declare `tempo: condition: service_started` (not `service_healthy` — Tempo has no `healthcheck:` block in this compose file at all). Documented reasoning (`docs/infra-hardening.md`): *"Tracing is never load-bearing ... a slow or absent Tempo never blocks API startup."* This is consistent with the bounded `timeout=5` on the exporter itself (§2.1) — two independent places in the codebase encode the same "tracing must not be able to block or fail the actual product" principle.

**Grafana, Loki, Prometheus: no service block exists for any of the three in `docker-compose.yml`.** Confirmed by grep — the only observability-adjacent service in local Compose is `tempo`.

---

## 7. THE Critical Gap — Business Metrics Are Never Scraped

This deserves its own section because it's the single most interview-relevant, non-obvious finding in this whole document, and it's easy to miss if you only read `telemetry.py` in isolation and assume "metrics are defined, therefore metrics work."

**The chain of facts:**
1. `EVAL_RUNS_TOTAL`, `EVAL_CASE_RESULTS_TOTAL`, `EVAL_RUN_DURATION_SECONDS`, `EVAL_CASE_COST_USD` are all incremented inside `apps/api/services/eval_engine.py`'s `run_eval()` — real `.inc()`/`.observe()` calls, not stubs.
2. `run_eval()` is called exclusively from worker processes: `apps/api/workers/eval_worker.py` and `apps/api/workers/eval_worker_v2.py` — never from `eval_service`/`agent_service`/`gate_service`'s FastAPI process.
3. Neither worker file calls `setup_metrics()`, imports `start_http_server` from `prometheus_client`, or defines any `/metrics` route — confirmed by grep across `apps/api/workers/`.
4. `DRIFT_CHECK_RUNS_TOTAL` and `DRIFT_SCORE_DELTA` follow the identical pattern one process further out: incremented inside `apps/api/services/drift/runner.py`'s `run_drift_check()`, which its own module docstring says runs in a **fourth, separate `drift_scheduler` process** — also with no `/metrics` route anywhere.
5. Even in the k3d/Helm path, where a `ServiceMonitor` does exist (`helm/redline/templates/base/servicemonitor.yaml`) and does correctly scrape `eval-service`/`agent-service`/`gate-service`, there is **no Kubernetes `Service` object for either worker Deployment** (`helm/redline/templates/worker/` and `load-worker/` each contain only `deployment.yaml` + `scaledobject.yaml`, no `service.yaml`) — so even a correctly-configured Prometheus Operator setup has no target to scrape for these processes.

**Conclusion:** `redline_eval_runs_total`, `redline_eval_case_results_total`, `redline_eval_run_duration_seconds`, `redline_eval_case_cost_usd`, `redline_drift_check_runs_total`, and `redline_drift_score_delta` are all **real Prometheus metric objects that are correctly incremented at runtime and are structurally impossible to scrape** in the current architecture, in either the local Docker Compose environment or the k3d/Helm environment. This is not a hypothetical "what if Prometheus isn't installed" gap (that's true of the HTTP metrics too, locally) — it's a **process-topology** gap: these specific metrics live in processes that were never given a scrape surface at all, regardless of whether Prometheus itself is running.

**The fix, if asked "how would you resolve this":** either (a) have the worker/scheduler processes call `prometheus_client.start_http_server(port)` on a dedicated metrics port and add a matching `Service` + `ServiceMonitor` entry for them, or (b) use the Prometheus Pushgateway pattern (appropriate here specifically because these are short-lived/batch-style processes relative to a long-running HTTP server — the classic textbook justification for Pushgateway's existence), pushing metric values after each `run_eval()`/`run_drift_check()` call rather than waiting to be scraped.

---

## 8. Testing

**File:** `apps/api/tests/conftest.py` — the `pytest_sessionfinish` OTel provider shutdown hook (§2.8). This is the **only** observability-specific test infrastructure found in the repository.

**Not found:** any test that asserts a specific span was created with specific attributes (no OTel `InMemorySpanExporter`-based assertion anywhere), any test asserting a Prometheus counter's value changed after an operation (no `prometheus_client.REGISTRY` inspection in any test file), any test exercising the `/metrics` endpoint's actual output shape, and no test for `emit_trace()`'s ClickHouse write beyond what's incidentally covered by broader integration tests. `test_eval_run_error_field.py`'s docstring (matched in the initial grep) mentions the error being *"recorded in the OTel span and the ClickHouse trace, neither of which the [test] ..."* — read this file directly if you need the exact scope of what it does and doesn't assert; the grep match confirms the test's own documentation is aware of both telemetry paths but the match alone doesn't confirm either is actually asserted against.

---

## 9. Manual Verification Steps (documented, not automated)

From `docs/infra-hardening.md`, the project's own operational reference:

**Tempo — has a real, documented, copy-pasteable verification command:**
```bash
docker compose up -d tempo
# Trigger any eval run, then:
curl "http://localhost:3200/api/search?tags=service.name%3Dredline&limit=5"
```

**Grafana → Tempo — explicitly manual, one-time, UI-driven, with the gap named in the doc's own words:**
> "No automated datasource provisioning is wired up (the existing `make monitoring-install` has no values-file/provisioning pattern to extend, and building that from scratch was out of proportion to this pass). One-time manual step: 1. `make monitoring-install` (or however you're reaching Grafana — port 3000 by default). 2. In Grafana: Connections → Data sources → Add data source → Tempo. 3. URL: `http://host.k3d.internal:3200` (k3d) or `http://localhost:3200` (docker-compose only)."

**No equivalent documented verification step exists anywhere in the repo for Loki, or for the Prometheus scraping of the three FastAPI services locally** (the k3d ServiceMonitor path is config-verified by reading the YAML, but no `curl`/`kubectl` command demonstrating it working end-to-end is documented the way Tempo's is).

---

## 10. Known Gaps — Summary (useful for "what would you improve")

1. **Business metrics (`EVAL_RUNS_TOTAL` and friends, `DRIFT_SCORE_DELTA` and friends) are defined and incremented but structurally unscrapable** — §7, the headline finding of this document.
2. **`opentelemetry-instrumentation-fastapi` is a declared dependency that is never imported or used** — auto-instrumentation (automatic per-request spans, `traceparent` propagation) doesn't exist; every span is manual.
3. **`opentelemetry.trace.Status`/`StatusCode` are imported in `telemetry.py` but never used** — failed eval-run spans get `record_exception()` but never an explicit `ERROR` status, meaning status-based filtering in Tempo/Grafana wouldn't reliably surface them.
4. **`GATE_DECISIONS_TOTAL` is defined but never incremented anywhere** — would report a permanent, misleading zero if it were ever scraped.
5. **The monolith (`apps/api/main.py`) has zero observability instrumentation** — no `/metrics`, no OTel tracer setup call, nothing. Only the three decomposed microservices get `setup_metrics()`.
6. **Unbounded label cardinality on `path`** in the HTTP metrics middleware (`telemetry.py:156-157,163`) — no route-templating before labeling, so any path containing a dynamic ID segment (e.g. `/eval-runs/{uuid}`) creates a fresh time series per distinct value ever requested.
7. **No Grafana, Loki, or Prometheus container in local `docker-compose.yml` at all** — the entire "look at your telemetry" experience locally is `curl`ing Tempo's raw API or reading `/metrics` output directly; there is no dashboard anywhere in this repository (no `.json` dashboard file, no provisioning config).
8. **No automated Grafana↔Tempo datasource wiring, even in the k3d/Helm path** — explicitly, honestly documented as a manual step by the project's own infra doc, not something this analysis is inferring.
9. **Loki/Promtail have no custom configuration anywhere and no documented end-to-end verification** — whatever behavior they'd have is 100% the `loki-stack` Helm chart's untouched defaults, never confirmed working in this repository's own history the way Tempo explicitly was.

---

## 11. Interview Q&A — Tied To This Exact Code

**"Walk me through what happens when an eval run executes, in terms of observability."**
`run_eval()` opens an `eval_run` span (`eval_engine.py:117`), a nested `eval_case` span per case (`line 157`), increments four Prometheus counters/histograms as it goes (`lines 177-178, 197-198, 230`), and writes lifecycle events into ClickHouse via `emit_trace()` (a separate, non-OTel system, §2.7). The spans export to Tempo over OTLP gRPC. The Prometheus metrics, however — and this is the part worth volunteering — never leave the worker process, because the worker never exposes `/metrics` (§7).

**"Is your tracing setup complete?"**
The exporter and span creation are real and verified (`docs/infra-hardening.md`'s documented `curl` against Tempo's query API). What's missing: auto-instrumentation (`opentelemetry-instrumentation-fastapi` is installed but unused, so HTTP-layer spans and trace-context propagation across service boundaries don't happen automatically), and explicit span status on error (`record_exception()` is called, `set_status(ERROR)` never is).

**"Why do you have both OpenTelemetry traces and this ClickHouse `traces` table? Isn't that redundant?"**
They're not the same system despite the name collision. OTel spans are for distributed-tracing tooling (Tempo/Grafana) — process-level, protocol-standard, meant for ops/debugging. The ClickHouse `traces` table is a custom, application-level event log RedLine's own dashboard queries directly for a business-facing "what happened during this eval run" timeline — different consumer, different query pattern (`SELECT` by `eval_run_id`/`tenant_id`, not trace-ID lookup), different retention/partitioning model (`PARTITION BY toYYYYMM`, `ORDER BY (tenant_id, eval_run_id, created_at)` — optimized for per-tenant time-range queries, not for trace reconstruction).

**"Are your business metrics — eval pass rate, drift score, etc. — actually visible in Prometheus/Grafana right now?"**
No, and this is worth being precise about rather than hand-waving: the `Counter`/`Histogram`/`Gauge` objects are real and are genuinely incremented at runtime, but they live inside the worker and drift-scheduler processes, neither of which exposes a `/metrics` endpoint or has a Kubernetes `Service` object for a `ServiceMonitor` to target. They're invisible to any scraper as the system is currently wired, regardless of whether Prometheus itself is even running.

**"How would you fix that?"**
Either give the worker/scheduler processes their own `start_http_server()` call plus a matching Service/ServiceMonitor, or push these specific metrics through a Prometheus Pushgateway — which is actually the more textbook-correct choice here, since these are short-lived-relative-to-a-scrape-interval batch/worker processes, the canonical use case Pushgateway exists for, rather than long-running servers a scraper can reliably poll.

**"Is Grafana wired up in this project?"**
Not automatically, and not in local development at all — no Grafana container exists in `docker-compose.yml`. It's only reachable via an optional `make monitoring-install` Helm step targeting k3d, and even then, connecting it to Tempo is a documented manual UI step with no provisioning file — the project's own `docs/infra-hardening.md` says exactly that.

**"What's your log pipeline?"**
The application emits structured, JSON-shaped log lines to stdout via a custom `logging.basicConfig` format string (`telemetry.py:45-48`). That's the entire application-side contribution. Loki/Promtail exist only as an optional Helm chart install with zero custom configuration in this repo, and — unlike Tempo — there's no documented verification that logs actually made it into Loki successfully at any point in this project's history.

---

## 12. Interview-Ready Explanation (60-90 seconds)

"Observability here splits into what's actually wired end-to-end and what's scaffolded but not connected. Tracing is the real one: I set up a `TracerProvider` with an OTLP exporter pointed at Grafana Tempo, and the eval engine wraps each run in a span with a nested span per test case, so you get a real trace tree per run — I've actually verified this by curling Tempo's search API after triggering a run. Metrics are more mixed. The three decomposed API services each expose a proper `/metrics` endpoint with `prometheus-client` — request counts, latency histograms, all scrapable. But the business metrics — eval pass counts, per-case cost, drift scores — are defined in the same file and are genuinely incremented, just from inside the worker process and a separate drift-scheduler process, and neither of those exposes a scrape endpoint or has a Kubernetes Service object for a ServiceMonitor to hit. So those specific metrics exist, update in real time, and are completely invisible to Prometheus as the system is wired right now — which is exactly the kind of gap that's easy to miss if you only check 'did I call `.inc()` somewhere' instead of tracing the whole path to a scraper. Grafana and Loki are the least finished part — no container for either in local Docker Compose, only available through an optional Helm install, and connecting Grafana to Tempo is a documented manual click-through, not something provisioned as code. If I were prioritizing what to fix next, it'd be giving the worker and scheduler processes their own metrics exposure — probably via a Pushgateway, since they're closer to batch jobs than long-running servers — before touching the Grafana/Loki side at all."

---

## 13. Observability Study Map

| Concept | Used? | File | Function/Class | Important Code | Importance |
|---|---|---|---|---|---|
| `TracerProvider` + `OTLPSpanExporter` setup | Yes | `telemetry.py:103-130` | `_setup_tracing()` | §2.1 | 🔥 |
| Manual spans (`start_as_current_span`) | Yes | `eval_engine.py:117,157` | `run_eval()` | §2.2 | 🔥 |
| Span attributes | Yes | `eval_engine.py:136-137,159` | `run_eval()` | §2.2 | ⭐⭐ |
| `record_exception()` | Yes | `eval_engine.py:217,235` | `run_eval()` | §2.2 | ⭐⭐ |
| `set_status(ERROR)` | **Not found** | — | — | §2.2, §10.3 | ⭐⭐ (know it's missing) |
| FastAPI auto-instrumentation | **Not found** (dependency unused) | — | — | §2.1, §10.2 | ⭐⭐ |
| Prometheus `Counter` | Yes | `telemetry.py:54-58,70-86`; `drift/runner.py:39-43` | module-level | §2.3, §2.6 | 🔥 |
| Prometheus `Histogram` | Yes | `telemetry.py:60-65,88-98` | module-level | §2.3 | 🔥 |
| Prometheus `Gauge` | Yes (one instance) | `drift/runner.py:45-49,173-176` | `DRIFT_SCORE_DELTA` | §2.6 | ⭐⭐ |
| Prometheus `Summary` | **Not found** | — | — | §2.3 | ⭐ |
| `/metrics` endpoint | Yes (3 of 4 processes) | `telemetry.py:168-173` | `setup_metrics()` | §2.5 | 🔥 |
| Metrics middleware | Yes | `telemetry.py:143-166` | `_metrics_middleware` | §2.5 | 🔥 |
| **Business metrics actually scraped** | **No — structural gap** | worker/scheduler processes | `eval_engine.py`, `drift/runner.py` | §7 | 🔥🔥 (the single best finding to bring up) |
| Prometheus scrape config (k3d) | Yes | `helm/redline/templates/base/servicemonitor.yaml` | `ServiceMonitor` | §6, §7 | ⭐⭐ |
| Prometheus in local Compose | **Not found** | — | — | §6 | ⭐⭐ |
| Grafana | Configured but unused / manual only | `Makefile:116-135` | `monitoring-install`, `monitoring-port-forward` | §9, §10.7-8 | ⭐⭐ |
| Grafana↔Tempo datasource | **Not found** (manual step only) | — | — | §9 | ⭐⭐ |
| Grafana dashboards / alerts | **Not found** | — | — | — | ⭐ |
| Structured JSON logging | Yes | `telemetry.py:45-49` | `logging.basicConfig` | §2.4 | ⭐⭐ |
| Loki | Configured but unused | `Makefile:126-128` | `loki-stack` Helm install | §2.4, §10.9 | ⭐ |
| Promtail | **Not found** (chart default only, unverified) | — | — | §2.4 | ⭐ |
| Tempo (the collector/backend itself) | Yes | `docker-compose.yml`, `infra/tempo.yaml` | `tempo` service | §6, §9 | 🔥 |
| Non-OTel ClickHouse "traces" table | Yes (separate system) | `clickhouse_client.py:51-65,134-176` | `emit_trace()` | §2.7 | 🔥 (common point of confusion, know the distinction cold) |
| OTel test hygiene | Yes | `conftest.py` | `pytest_sessionfinish` hook | §2.8 | ⭐ |
