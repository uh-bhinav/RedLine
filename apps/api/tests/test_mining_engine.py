"""Failure mining: clustering, bad-outcome rate, re-mining semantics."""
import pytest

from apps.api.models import CandidateCase, FailureCluster
from apps.api.services import mining_engine
from seeding import seed_agent, seed_run, seed_suite, transcript

REFUND = [
    "How do I get a refund for my order?",
    "What is your refund policy for damaged orders?",
    "I want a refund for my broken order",
]
PASSWORD = [
    "How do I reset my password?",
    "I forgot my password, how can I reset it?",
]


@pytest.fixture
def world(db_session, make_tenant):
    tenant = make_tenant()
    agent = seed_agent(db_session, tenant)
    suite = seed_suite(db_session, agent, n_cases=6)
    return tenant, agent, suite


def _run(db, world, outcomes):
    """outcomes: list of (prompt, passed) -> one completed run."""
    tenant, agent, suite = world
    results = [
        {"case_id": suite.case_ids[i], "passed": passed, "transcript": transcript(prompt, "ans")}
        for i, (prompt, passed) in enumerate(outcomes)
    ]
    return seed_run(db, tenant, agent.versions[0], suite, results)


def test_no_results_returns_empty(db_session, world):
    assert mining_engine.mine(db_session, world[1].id) == []


def test_all_passing_returns_empty_and_creates_nothing(db_session, world):
    _run(db_session, world, [(p, True) for p in REFUND + PASSWORD])
    assert mining_engine.mine(db_session, world[1].id) == []
    assert db_session.query(FailureCluster).count() == 0
    assert db_session.query(CandidateCase).count() == 0


def test_clusters_cover_failing_prompts_only(db_session, world):
    failing = REFUND + PASSWORD
    _run(db_session, world, [(p, False) for p in failing] + [("What are your opening hours?", True)])
    clusters = mining_engine.mine(db_session, world[1].id)
    assert clusters
    assert sum(c.case_count for c in clusters) == len(failing)
    assert all(c.bad_outcome_rate == 1.0 for c in clusters)
    assert {c.representative for c in clusters} <= set(failing)
    assert "What are your opening hours?" not in {c.representative for c in clusters}
    assert sorted(c.cluster_index for c in clusters) == list(range(len(clusters)))
    assert all(c.label.startswith("Questions about") for c in clusters)


def test_one_candidate_per_cluster_and_pending(db_session, world):
    _run(db_session, world, [(p, False) for p in REFUND + PASSWORD])
    clusters = mining_engine.mine(db_session, world[1].id)
    cands = db_session.query(CandidateCase).all()
    assert len(cands) == len(clusters)
    assert {c.cluster_id for c in cands} == {c.id for c in clusters}
    assert all(c.status == "pending" and c.case_key.startswith("mined_") for c in cands)
    assert {c.prompt for c in cands} == {c.representative for c in clusters}


def test_single_failing_prompt_and_bad_outcome_rate(db_session, world):
    p = "How do I get a refund?"
    _run(db_session, world, [(p, False), ("Other question", True)])
    _run(db_session, world, [(p, True)])
    _run(db_session, world, [(p, False)])
    _run(db_session, world, [(p, True)])
    clusters = mining_engine.mine(db_session, world[1].id)
    assert len(clusters) == 1
    assert clusters[0].case_count == 1
    assert clusters[0].bad_outcome_rate == 0.5  # failed in 2 of 4 runs
    assert clusters[0].representative == p


def test_rate_mixes_across_prompts_in_cluster(db_session, world):
    _run(db_session, world, [(REFUND[0], False), (REFUND[1], False)])
    _run(db_session, world, [(REFUND[0], True), (REFUND[1], False)])
    clusters = mining_engine.mine(db_session, world[1].id)
    total = sum(c.case_count for c in clusters)
    assert total == 2
    weighted = sum(c.bad_outcome_rate * c.case_count for c in clusters)
    assert 0 < weighted / total <= 1


def test_remine_replaces_pending_candidates_and_clusters(db_session, world):
    agent = world[1]
    _run(db_session, world, [(p, False) for p in REFUND + PASSWORD])
    first = mining_engine.mine(db_session, agent.id)
    first_ids = {c.id for c in first}
    second = mining_engine.mine(db_session, agent.id)
    assert len(second) == len(first)
    assert not (first_ids & {c.id for c in second})
    assert db_session.query(FailureCluster).count() == len(second)
    assert db_session.query(CandidateCase).count() == len(second)


def test_remine_after_fixing_failures_clears_pending(db_session, world):
    agent = world[1]
    _run(db_session, world, [(p, False) for p in REFUND])
    assert mining_engine.mine(db_session, agent.id)
    # every prompt now passes everywhere -> no failures remain only if no run ever failed;
    # so instead wipe the results and re-mine
    from sqlalchemy import text

    db_session.execute(text("DELETE FROM eval_case_results"))
    db_session.commit()
    assert mining_engine.mine(db_session, agent.id) == []
    assert db_session.query(FailureCluster).count() == 0
    assert db_session.query(CandidateCase).count() == 0


def test_mining_is_scoped_to_agent(db_session, make_tenant):
    tenant = make_tenant()
    a1, a2 = seed_agent(db_session, tenant), seed_agent(db_session, tenant)
    s1, s2 = seed_suite(db_session, a1, 1), seed_suite(db_session, a2, 1)
    seed_run(db_session, tenant, a1.versions[0], s1,
             [{"case_id": s1.case_ids[0], "passed": False, "transcript": transcript("broken thing", "x")}])
    assert mining_engine.mine(db_session, a2.id) == []
    assert len(mining_engine.mine(db_session, a1.id)) == 1


def test_remine_keeps_reviewed_candidates(db_session, world):
    agent = world[1]
    _run(db_session, world, [(p, False) for p in REFUND + PASSWORD])
    mining_engine.mine(db_session, agent.id)
    cand = db_session.query(CandidateCase).first()
    cand.status = "approved"
    db_session.commit()
    mining_engine.mine(db_session, agent.id)
    assert db_session.query(CandidateCase).filter_by(status="approved").count() == 1
