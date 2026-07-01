"""
LocalPythonAdapter — Phase 1's only AgentAdapter implementation.

Given an entrypoint string like 'agents.rag_agent.agent:run_turn'
(module_path:function_name), imports that module and calls the named function
in-process. This is what makes Phase 1 fast to iterate on locally with zero
network overhead. Phase 2 adds HTTPAdapter alongside this for agents deployed
elsewhere — the Eval Engine's calling code does not change.
"""
from __future__ import annotations

import importlib
from typing import Callable

from apps.api.services.adapters.base import AgentTurnResult


class LocalPythonAdapter:
    def __init__(self, entrypoint: str):
        self.entrypoint = entrypoint
        self._fn = self._load_entrypoint(entrypoint)

    @staticmethod
    def _load_entrypoint(entrypoint: str) -> Callable[[dict, str], AgentTurnResult]:
        if ":" not in entrypoint:
            raise ValueError(
                f"invalid entrypoint '{entrypoint}' — expected 'module.path:function_name'"
            )
        module_path, function_name = entrypoint.rsplit(":", 1)
        module = importlib.import_module(module_path)
        fn = getattr(module, function_name, None)
        if fn is None or not callable(fn):
            raise ValueError(f"'{function_name}' not found or not callable in '{module_path}'")
        return fn

    def run_turn(self, session_state: dict, user_message: str) -> AgentTurnResult:
        return self._fn(session_state, user_message)