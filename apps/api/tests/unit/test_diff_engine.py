"""
Unit tests for diff_engine._classify_diff() and _cosine_similarity() (Phase 4 Section 2).

Pure function tests -- no database, no embedding calls, no I/O. Matches the style of
test_ars_engine.py and test_gate_engine.py: compute_diff() (the DB-backed orchestrator
that actually calls the embedding API) delegates all classification arithmetic here,
which is what makes it testable without any infrastructure or LLM cost.

Run from the repo root:
    pytest apps/api/tests/unit/test_diff_engine.py -v -m unit
"""
import pytest

from apps.api.services.diff_engine import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DiffClassification,
    _classify_diff,
    _cosine_similarity,
)

pytestmark = pytest.mark.unit


# ---------- _cosine_similarity ----------

def test_identical_vectors_have_similarity_one():
    v = [1.0, 2.0, 3.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_orthogonal_vectors_have_similarity_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_opposite_vectors_have_similarity_negative_one():
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_zero_vector_returns_zero_not_a_division_error():
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_similarity_is_scale_invariant():
    """Cosine similarity cares about direction, not magnitude -- an embedding
    scaled by any positive factor must compare identically."""
    v1 = [1.0, 2.0, 3.0]
    v2 = [2.0, 4.0, 6.0]
    assert _cosine_similarity(v1, v2) == pytest.approx(1.0)


# ---------- _classify_diff: the four quadrants ----------

def test_no_op_when_code_same_and_behavior_same():
    result = _classify_diff(code_changed=False, per_case_similarity={"c1": 0.99, "c2": 0.98})
    assert result.classification == DiffClassification.NO_OP
    assert result.behavior_changed is False


def test_safe_refactor_when_code_changed_but_behavior_same():
    result = _classify_diff(code_changed=True, per_case_similarity={"c1": 0.99, "c2": 0.97})
    assert result.classification == DiffClassification.SAFE_REFACTOR


def test_expected_change_when_code_changed_and_behavior_changed():
    result = _classify_diff(code_changed=True, per_case_similarity={"c1": 0.5, "c2": 0.4})
    assert result.classification == DiffClassification.EXPECTED_CHANGE


def test_silent_drift_when_code_same_but_behavior_changed():
    """The alarm case: no code change, yet the agent's answers moved. Foundational
    doc's specific example -- a model silently upgraded underneath the agent."""
    result = _classify_diff(code_changed=False, per_case_similarity={"c1": 0.5, "c2": 0.45})
    assert result.classification == DiffClassification.SILENT_DRIFT
    assert result.behavior_changed is True
    assert result.code_changed is False


def test_insufficient_data_when_no_shared_cases():
    result = _classify_diff(code_changed=True, per_case_similarity={})
    assert result.classification == DiffClassification.INSUFFICIENT_DATA
    assert "no case_key" in result.detail


# ---------- threshold boundary ----------

def test_similarity_exactly_at_threshold_is_not_a_change():
    """< threshold means changed, so exactly AT threshold must count as unchanged --
    same '< min' vs '<= min' convention as every other threshold in this codebase."""
    result = _classify_diff(
        code_changed=False, per_case_similarity={"c1": 0.9}, similarity_threshold=0.9,
    )
    assert result.behavior_changed is False
    assert result.classification == DiffClassification.NO_OP


def test_similarity_just_under_threshold_is_a_change():
    result = _classify_diff(
        code_changed=False, per_case_similarity={"c1": 0.8999}, similarity_threshold=0.9,
    )
    assert result.behavior_changed is True


def test_custom_threshold_is_respected():
    similarities = {"c1": 0.7}
    strict = _classify_diff(code_changed=False, per_case_similarity=similarities,
                             similarity_threshold=0.95)
    lenient = _classify_diff(code_changed=False, per_case_similarity=similarities,
                              similarity_threshold=0.5)
    assert strict.behavior_changed is True
    assert lenient.behavior_changed is False


# ---------- mean aggregation across multiple cases ----------

def test_mean_similarity_is_averaged_across_cases_not_worst_case():
    result = _classify_diff(
        code_changed=False,
        per_case_similarity={"c1": 1.0, "c2": 1.0, "c3": 0.5},
        similarity_threshold=0.9,
    )
    assert result.mean_similarity == pytest.approx((1.0 + 1.0 + 0.5) / 3)


def test_detail_names_case_count_and_threshold():
    result = _classify_diff(
        code_changed=True, per_case_similarity={"c1": 0.9, "c2": 0.9, "c3": 0.9},
    )
    assert "3 case" in result.detail


def test_per_case_similarity_is_preserved_in_the_result():
    similarities = {"case_a": 0.91, "case_b": 0.42}
    result = _classify_diff(code_changed=True, per_case_similarity=similarities)
    assert result.per_case_similarity == similarities


def test_default_threshold_is_importable_and_sane():
    assert 0.0 < DEFAULT_SIMILARITY_THRESHOLD <= 1.0
