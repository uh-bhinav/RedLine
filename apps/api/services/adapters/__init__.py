"""
Adapter selection (Phase 3 Section 2).

`build_adapter(entrypoint)` is the single place that decides which AgentAdapter
implementation an agent version needs. Everything downstream -- the eval engine's
per-turn loop, every scorer, the gate engine -- talks only to the AgentAdapter
Protocol and is unaware of which implementation it got.

Selection is by the shape of `agent_versions.entrypoint`, so adding HTTP support
required no schema migration:

    agents.rag_agent.agent:run_turn     -> LocalPythonAdapter (in-process import)
    https://my-agent.example.com/turn   -> HTTPAdapter        (deployed elsewhere)

Phase 4 adds ChaosAdapter, which satisfies this same Protocol *and* wraps whichever
adapter build_adapter returned -- fault injection as a decorator over the stable
contract, with no change to the eval engine.
"""
from __future__ import annotations

from apps.api.services.adapters.base import AgentAdapter, AgentTurnResult, ToolCall
from apps.api.services.adapters.http_adapter import AgentHTTPError, HTTPAdapter
from apps.api.services.adapters.local_python import LocalPythonAdapter

__all__ = [
    "AgentAdapter",
    "AgentHTTPError",
    "AgentTurnResult",
    "HTTPAdapter",
    "LocalPythonAdapter",
    "ToolCall",
    "build_adapter",
]

_HTTP_SCHEMES = ("http://", "https://")


def build_adapter(entrypoint: str, **kwargs) -> AgentAdapter:
    """Returns the adapter appropriate for this entrypoint.

    kwargs are forwarded to the selected implementation (e.g. timeout_seconds or
    headers for HTTPAdapter). LocalPythonAdapter takes none, so passing HTTP-only
    options alongside a Python entrypoint is a programming error and raises rather
    than being silently dropped.
    """
    if not entrypoint or not entrypoint.strip():
        raise ValueError(
            "entrypoint is empty -- expected 'module.path:function' or an http(s) URL"
        )

    entrypoint = entrypoint.strip()

    if entrypoint.startswith(_HTTP_SCHEMES):
        return HTTPAdapter(entrypoint, **kwargs)

    if ":" not in entrypoint:
        raise ValueError(
            f"invalid entrypoint '{entrypoint}' -- expected 'module.path:function_name' "
            f"for a local Python agent, or an http(s):// URL for a deployed agent"
        )

    if kwargs:
        raise ValueError(
            f"adapter options {sorted(kwargs)} are not supported for the local Python "
            f"entrypoint '{entrypoint}'"
        )

    return LocalPythonAdapter(entrypoint)
