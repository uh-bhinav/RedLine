"""Loaded at interpreter start-up of spawned worker children (via PYTHONPATH) in tests only.

When REDLINE_TEST_WORKER_MODE is set, replace eval_worker.HANDLERS with the test handlers so the
real spawn/pipe/timeout machinery can be exercised without running real eval engines.
"""
import os
import sys
from pathlib import Path

if os.environ.get("REDLINE_TEST_WORKER_MODE"):
    _tests = Path(__file__).resolve().parents[1]
    _root = _tests.parents[2]
    for _p in (str(_root), str(_tests)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import worker_handlers

    worker_handlers.install()
