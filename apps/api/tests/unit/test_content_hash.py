"""
Unit tests for content_hash computation (roadmap Section 15, Section 4 item).

The content_hash is the Agent Registry's mechanism for detecting identical
agent versions (Holy Grail §10.14). These tests prove it is:
  1. Deterministic -- same file always produces the same hash
  2. Unique -- different content produces a different hash
  3. Well-formed -- output is a 64-character lowercase SHA256 hex string
  4. Robust -- fails loudly on a bad entrypoint, not silently

No DB, no LLM, no I/O beyond reading files already on disk.

Run from the repo root:
    pytest apps/api/tests/unit/test_content_hash.py -v
"""
import hashlib
import tempfile
from pathlib import Path

import pytest

from apps.api.scripts.register_agent_version import _compute_content_hash

pytestmark = pytest.mark.unit


def _write_temp_module(content: str, suffix: str = "") -> tuple[str, Path]:
    """Creates a temp Python file and returns (entrypoint_string, path)."""
    tmp = tempfile.NamedTemporaryFile(
        suffix=f"{suffix}.py", delete=False, mode="w", prefix="test_agent_"
    )
    tmp.write(content)
    tmp.close()
    path = Path(tmp.name)
    return path


def test_content_hash_is_valid_sha256_hex():
    hash_val = _compute_content_hash("agents.rag_agent.agent:run_turn")
    assert len(hash_val) == 64
    assert all(c in "0123456789abcdef" for c in hash_val)


def test_content_hash_is_deterministic():
    h1 = _compute_content_hash("agents.rag_agent.agent:run_turn")
    h2 = _compute_content_hash("agents.rag_agent.agent:run_turn")
    assert h1 == h2, "same file must always produce the same hash"


def test_content_hash_matches_manual_sha256():
    """Cross-verify against a direct hashlib computation -- no hidden magic."""
    import importlib
    module = importlib.import_module("agents.rag_agent.agent")
    expected = hashlib.sha256(open(module.__file__, "rb").read()).hexdigest()
    actual = _compute_content_hash("agents.rag_agent.agent:run_turn")
    assert actual == expected


def test_different_entrypoints_produce_different_hashes():
    """Two different source files must produce different hashes (uniqueness guarantee)."""
    h_agent = _compute_content_hash("agents.rag_agent.agent:run_turn")
    h_fixture = _compute_content_hash(
        "apps.api.tests.unit.fixtures.dummy_agent:run_turn"
    )
    assert h_agent != h_fixture, (
        "different source files must never produce the same hash -- "
        "the registry uses this to identify unique versions"
    )


def test_content_hash_raises_on_missing_colon():
    with pytest.raises(ValueError):
        _compute_content_hash("agents.rag_agent.agent_no_colon")


def test_content_hash_raises_on_unimportable_module():
    with pytest.raises(ModuleNotFoundError):
        _compute_content_hash("agents.this_module_does_not_exist:run_turn")