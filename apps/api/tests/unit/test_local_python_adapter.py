"""
Tests for LocalPythonAdapter (roadmap Section 6).

No database needed for these — pure Python import/call mechanics.
Run from the repo root:

    pytest apps/api/tests/unit/test_local_python_adapter.py -v
"""
import pytest

from apps.api.services.adapters.local_python import LocalPythonAdapter


def test_local_python_adapter_loads_and_calls_entrypoint():
    adapter = LocalPythonAdapter("apps.api.tests.unit.fixtures.dummy_agent:run_turn")
    session_state: dict = {}

    result1 = adapter.run_turn(session_state, "hello")
    assert result1.assistant_message == "echo: hello (turn 1)"
    assert result1.tool_calls[0].name == "noop_tool"
    assert result1.tool_calls[0].arguments == {"echo": "hello"}

    # session_state must carry forward across turns, mutated by the agent itself
    result2 = adapter.run_turn(session_state, "again")
    assert result2.assistant_message == "echo: again (turn 2)"
    assert session_state["turn_count"] == 2


def test_local_python_adapter_rejects_bad_entrypoint_format():
    with pytest.raises(ValueError):
        LocalPythonAdapter("not_a_valid_entrypoint")


def test_local_python_adapter_rejects_missing_function():
    with pytest.raises(ValueError):
        LocalPythonAdapter("apps.api.tests.unit.fixtures.dummy_agent:does_not_exist")


def test_local_python_adapter_rejects_unimportable_module():
    with pytest.raises(ModuleNotFoundError):
        LocalPythonAdapter("apps.api.this_module_does_not_exist:run_turn")