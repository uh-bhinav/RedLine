"""Test-only job handlers for the eval_worker process tests.

Top-level, importable functions: the worker runs each job in a 'spawn' child, which re-imports
modules from scratch, so monkeypatching `eval_worker.HANDLERS` in the parent is invisible there.
`_worker_site/sitecustomize.py` installs `install()` into every child started with
REDLINE_TEST_WORKER_MODE set. The mode picks the behaviour for every job type.
"""
from __future__ import annotations

import os
import time
import uuid

MODE_ENV = "REDLINE_TEST_WORKER_MODE"


def handler(target_id: uuid.UUID) -> None:
    mode = os.environ.get(MODE_ENV, "ok")
    if mode == "ok":
        return
    if mode == "hang":
        time.sleep(300)
    elif mode == "raise":
        raise RuntimeError("handler exploded: kaboom-marker")
    elif mode == "exit":
        os._exit(1)  # abrupt death: nothing is sent over the pipe
    else:
        raise AssertionError(f"unknown mode {mode!r}")


def install() -> None:
    from apps.api.workers import eval_worker

    for job_type in list(eval_worker.HANDLERS):
        eval_worker.HANDLERS[job_type] = handler
