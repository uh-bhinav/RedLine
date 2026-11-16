"""
Unit tests for mining.engine._cluster_embeddings() and
_identify_significant_clusters() (Phase 4 Section 6).

_cluster_embeddings() takes plain synthetic vectors -- no Gemini call, no DB --
so DBSCAN's actual clustering behavior is tested for real, deterministically.
_identify_significant_clusters() takes labels and outcomes already computed, so
the significance thresholds are tested with zero embeddings at all.

The DB-backed mine_failures() (real transcripts, real embeddings, real Postgres)
is covered by test_mining_engine_end_to_end.py.

Run from the repo root:
    pytest apps/api/tests/unit/test_mining_engine.py -v -m unit
"""
import pytest

from apps.api.services.mining.engine import (
    DEFAULT_MIN_BAD_OUTCOME_RATE,
    DEFAULT_MIN_CLUSTER_SIZE,
    NOISE_LABEL,
    ClusterSummary,
    _cluster_embeddings,
    _identify_significant_clusters,
)

pytestmark = pytest.mark.unit


# ---------- _cluster_embeddings: real DBSCAN, synthetic vectors ----------

def test_empty_input_returns_empty_labels():
    assert _cluster_embeddings([]) == []


def test_identical_vectors_cluster_together():
    vectors = [[1.0, 0.0, 0.0]] * 5
    labels = _cluster_embeddings(vectors, eps=0.01, min_samples=3)
    assert len(set(labels)) == 1
    assert labels[0] != NOISE_LABEL


def test_clearly_separated_groups_get_different_labels():
    group_a = [[1.0, 0.0, 0.0]] * 4
    group_b = [[0.0, 1.0, 0.0]] * 4
    vectors = group_a + group_b
    labels = _cluster_embeddings(vectors, eps=0.1, min_samples=3)

    labels_a = set(labels[:4])
    labels_b = set(labels[4:])
    assert labels_a != labels_b
    assert NOISE_LABEL not in labels_a
    assert NOISE_LABEL not in labels_b


def test_a_single_outlier_among_a_cluster_is_noise():
    cluster = [[1.0, 0.0, 0.0]] * 4
    outlier = [[0.0, 0.0, 1.0]]
    vectors = cluster + outlier
    labels = _cluster_embeddings(vectors, eps=0.1, min_samples=3)

    assert labels[-1] == NOISE_LABEL
    assert all(label != NOISE_LABEL for label in labels[:4])


def test_too_few_similar_points_are_all_noise():
    # min_samples=3 but only 2 similar points -- neither can form a cluster.
    vectors = [[1.0, 0.0], [1.0, 0.0]]
    labels = _cluster_embeddings(vectors, eps=0.1, min_samples=3)
    assert all(label == NOISE_LABEL for label in labels)


def test_zero_vector_does_not_raise_a_division_error():
    vectors = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    labels = _cluster_embeddings(vectors, eps=0.1, min_samples=3)
    assert len(labels) == 4  # must not crash


# ---------- _identify_significant_clusters: pure significance logic ----------

def test_mismatched_lengths_raises():
    with pytest.raises(ValueError, match="same length"):
        _identify_significant_clusters([0, 0, 1], [True, False])


def test_noise_labeled_points_are_never_a_cluster():
    labels = [NOISE_LABEL] * 10
    outcomes = [True] * 10
    result = _identify_significant_clusters(labels, outcomes, min_cluster_size=2)
    assert result == []


def test_cluster_below_min_size_is_excluded():
    labels = [0, 0]  # size 2
    outcomes = [True, True]
    result = _identify_significant_clusters(labels, outcomes, min_cluster_size=3)
    assert result == []


def test_cluster_meeting_size_and_bad_rate_is_included():
    labels = [0, 0, 0]
    outcomes = [True, True, False]  # 2/3 = 67% bad
    result = _identify_significant_clusters(
        labels, outcomes, min_cluster_size=3, min_bad_outcome_rate=0.5,
    )
    assert len(result) == 1
    assert result[0].size == 3
    assert result[0].bad_outcome_rate == pytest.approx(2 / 3)


def test_cluster_with_mostly_good_outcomes_is_excluded():
    """A common, mostly-fine topic must not look like a failure pattern."""
    labels = [0, 0, 0, 0]
    outcomes = [False, False, False, True]  # only 25% bad
    result = _identify_significant_clusters(
        labels, outcomes, min_cluster_size=3, min_bad_outcome_rate=0.5,
    )
    assert result == []


def test_multiple_clusters_are_each_evaluated_independently():
    labels = [0, 0, 0, 1, 1, 1]
    outcomes = [True, True, True, False, False, False]  # cluster 0 all bad, cluster 1 all good
    result = _identify_significant_clusters(labels, outcomes, min_cluster_size=3)
    assert len(result) == 1
    assert result[0].cluster_label == 0


def test_representative_index_prefers_a_bad_outcome_member():
    labels = [0, 0, 0]
    outcomes = [False, True, False]  # index 1 is the only bad one
    result = _identify_significant_clusters(
        labels, outcomes, min_cluster_size=3, min_bad_outcome_rate=0.3,
    )
    assert result[0].representative_index == 1


def test_representative_falls_back_to_first_member_if_somehow_none_are_bad():
    """Defensive: shouldn't happen given min_bad_outcome_rate > 0, but must not crash."""
    labels = [0, 0, 0]
    outcomes = [False, False, False]
    result = _identify_significant_clusters(
        labels, outcomes, min_cluster_size=3, min_bad_outcome_rate=0.0,
    )
    assert len(result) == 1
    assert result[0].representative_index == 0


def test_detail_string_names_the_counts():
    labels = [0, 0, 0]
    outcomes = [True, True, False]
    result = _identify_significant_clusters(labels, outcomes, min_cluster_size=3)
    assert "2/3" in result[0].detail


def test_defaults_are_importable_and_sane():
    assert DEFAULT_MIN_CLUSTER_SIZE >= 2
    assert 0.0 < DEFAULT_MIN_BAD_OUTCOME_RATE <= 1.0
