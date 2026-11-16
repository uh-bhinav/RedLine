"""
Root conftest.

pytest_sessionfinish fix (Phase 3 Section 8 follow-up, "ConsoleSpanExporter noisy
teardown"): `apps.api.core.telemetry._setup_tracing()` constructs
`ConsoleSpanExporter()` at import time, which binds to whatever `sys.stdout` is
at that moment -- under pytest that is pytest's capture proxy, not the real
terminal stream. `BatchSpanProcessor` exports on a `daemon=True` background
thread that wakes up on its own schedule (default every 5s) with no shutdown
hook of its own. If that thread's periodic export fires after pytest has torn
down its capture buffer for the session, it writes to an already-closed file
object -> "ValueError: I/O operation on closed file".

Explicitly shutting the provider down here -- which flushes any queued spans
and joins the worker thread -- runs while pytest's capture is still live, so
nothing is left to fire into a closed buffer afterwards. Root-caused as part of
the Phase 4.5 cleanup pass. Phase 5.1 has since swapped ConsoleSpanExporter for
OTLPSpanExporter (which doesn't write through Python file objects at all), so
this specific failure mode is gone -- this hook stays anyway as correct
BatchSpanProcessor hygiene: any exporter's background thread should be flushed
and joined before the process exits, not just the one that used to crash.

Bounded-join wrapper (Phase 5.1): shutdown() flushes the exporter, which for
OTLPSpanExporter means a real (bounded, timeout=5 in telemetry.py) network
attempt. Running it on its own thread with a join timeout is defense in depth
so a pytest session can never hang here regardless of exporter/network
behavior -- the same "must never be load-bearing" principle applied to test
teardown, not just to emit_trace()'s request-path try/except.
"""
import threading

from opentelemetry import trace


def pytest_sessionfinish(session, exitstatus):
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if shutdown is None:
        return
    t = threading.Thread(target=shutdown, daemon=True)
    t.start()
    t.join(timeout=8)
