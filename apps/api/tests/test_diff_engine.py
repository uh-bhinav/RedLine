"""Diff engine: classification, similarity metric, and run_diff end to end."""
import uuid

import pytest

from apps.api.models import DiffCaseResult, DiffRun, DriftAlert
from apps.api.services import diff_engine
from seeding import seed_agent, seed_run, seed_suite, transcript


@pytest.mark.parametrize(
    "code_changed,behaviour_changed,expected",
    [
        (False, False, "no_op"),
        (False, True, "silent_drift"),
        (True, False, "safe_refactor"),
        (True, True, "expected_change"),
    ],
)
def test_classify_truth_table(code_changed, behaviour_changed, expected):
    assert diff_engine.classify(code_changed, behaviour_changed) == expected


def test_similarity_identity_and_empty():
    assert diff_engine.similarity("The quick brown fox", "The quick brown fox") == 1.0
    assert diff_engine.similarity("", "") == 1.0
    assert diff_engine.similarity("...", "!!!") == 1.0  # no tokens on either side


def test_similarity_disjoint_is_zero():
    assert diff_engine.similarity("aaa", "zzz") == 0.0
    assert diff_engine.similarity("", "something") == 0.0


def test_similarity_is_case_insensitive():
    assert diff_engine.similarity("Hello World", "hello world") == 1.0


@pytest.mark.parametrize(
    "a,b",
    [
        ("the cat sat", "the cat sat down"),
        ("refund in 30 days", "refunds are processed within thirty days"),
        ("a", "b"),
        ("x y z", "x"),
    ],
)
def test_similarity_bounds_and_symmetry_of_token_part(a, b):
    s = diff_engine.similarity(a, b)
    assert 0.0 <= s <= 1.0
    assert diff_engine.similarity(a, a) == 1.0


def test_similarity_orders_closer_text_higher():
    base = "your refund will arrive in five business days"
    near = "your refund will arrive in six business days"
    far = "please contact support for shipping options"
    assert diff_engine.similarity(base, near) > diff_engine.similarity(base, far)


# ---------------- run_diff end to end ----------------
def _results(suite, answers, passed=True):
    return [
        {"case_id": cid, "passed": passed, "transcript": transcript(f"q{i}", answers[i])}
        for i, cid in enumerate(suite.case_ids)
    ]


@pytest.fixture
def world(db_session, make_tenant):
    tenant = make_tenant()
    agent = seed_agent(db_session, tenant, versions=2)
    suite = seed_suite(db_session, agent, n_cases=2)
    return tenant, agent, suite


def _diff(db, tenant, agent, suite, run_a, run_b, threshold=0.9):
    d = DiffRun(
        tenant_id=tenant.id, agent_id=agent.id, suite_id=suite.id,
        run_a_id=run_a.id, run_b_id=run_b.id, threshold=threshold,
    )
    db.add(d)
    db.commit()
    return d.id


def _load(db, diff_id):
    db.expire_all()
    return db.get(DiffRun, diff_id)


def test_same_code_same_output_is_no_op(db_session, world):
    tenant, agent, suite = world
    v = agent.versions[0]
    ans = ["Refunds take five days.", "Reset it from settings."]
    a = seed_run(db_session, tenant, v, suite, _results(suite, ans))
    b = seed_run(db_session, tenant, v, suite, _results(suite, ans))
    did = _diff(db_session, tenant, agent, suite, a, b)
    diff_engine.run_diff(did)
    d = _load(db_session, did)
    assert (d.status, d.classification, d.code_changed, d.mean_similarity) == ("completed", "no_op", False, 1.0)
    assert d.completed_at is not None
    assert db_session.query(DriftAlert).count() == 0
    assert db_session.query(DiffCaseResult).filter_by(diff_run_id=did).count() == 2


def test_same_code_changed_output_is_silent_drift_with_alert(db_session, world):
    tenant, agent, suite = world
    v = agent.versions[0]
    a = seed_run(db_session, tenant, v, suite, _results(suite, ["Refunds take five days.", "Reset it from settings."]))
    b = seed_run(db_session, tenant, v, suite, _results(suite, ["Zebras migrate annually.", "Quantum flux capacitor."]))
    did = _diff(db_session, tenant, agent, suite, a, b)
    diff_engine.run_diff(did)
    d = _load(db_session, did)
    assert d.classification == "silent_drift" and d.code_changed is False
    assert d.mean_similarity < d.threshold
    alerts = db_session.query(DriftAlert).all()
    assert len(alerts) == 1
    al = alerts[0]
    assert (al.agent_id, al.diff_run_id, al.eval_run_id) == (agent.id, did, b.id)
    assert al.drift_type == "model" and al.metric == "similarity"
    assert al.baseline_value == d.threshold and al.current_value == d.mean_similarity
    rows = db_session.query(DiffCaseResult).filter_by(diff_run_id=did).all()
    assert {r.output_a for r in rows} == {"Refunds take five days.", "Reset it from settings."}
    assert all(r.similarity < 0.9 for r in rows)


def test_new_code_same_output_is_safe_refactor(db_session, world):
    tenant, agent, suite = world
    ans = ["Refunds take five days.", "Reset it from settings."]
    a = seed_run(db_session, tenant, agent.versions[0], suite, _results(suite, ans))
    b = seed_run(db_session, tenant, agent.versions[1], suite, _results(suite, ans))
    did = _diff(db_session, tenant, agent, suite, a, b)
    diff_engine.run_diff(did)
    d = _load(db_session, did)
    assert (d.classification, d.code_changed) == ("safe_refactor", True)
    assert db_session.query(DriftAlert).count() == 0


def test_new_code_changed_output_is_expected_change(db_session, world):
    tenant, agent, suite = world
    a = seed_run(db_session, tenant, agent.versions[0], suite, _results(suite, ["alpha beta", "gamma delta"]))
    b = seed_run(db_session, tenant, agent.versions[1], suite, _results(suite, ["omega psi", "chi phi"]))
    did = _diff(db_session, tenant, agent, suite, a, b)
    diff_engine.run_diff(did)
    d = _load(db_session, did)
    assert (d.classification, d.code_changed) == ("expected_change", True)
    assert db_session.query(DriftAlert).count() == 0


def test_threshold_controls_behaviour_change(db_session, world):
    tenant, agent, suite = world
    v = agent.versions[0]
    a = seed_run(db_session, tenant, v, suite, _results(suite, ["Refunds take five days.", "Reset it."]))
    b = seed_run(db_session, tenant, v, suite, _results(suite, ["Refunds take six days.", "Reset it."]))
    lenient = _diff(db_session, tenant, agent, suite, a, b, threshold=0.1)
    strict = _diff(db_session, tenant, agent, suite, a, b, threshold=1.0)
    diff_engine.run_diff(lenient)
    diff_engine.run_diff(strict)
    assert _load(db_session, lenient).classification == "no_op"
    assert _load(db_session, strict).classification == "silent_drift"


def test_only_cases_present_in_both_runs_are_compared(db_session, world):
    tenant, agent, suite = world
    v = agent.versions[0]
    full = _results(suite, ["same", "same"])
    a = seed_run(db_session, tenant, v, suite, full)
    b = seed_run(db_session, tenant, v, suite, full[:1])
    did = _diff(db_session, tenant, agent, suite, a, b)
    diff_engine.run_diff(did)
    assert db_session.query(DiffCaseResult).filter_by(diff_run_id=did).count() == 1


def test_missing_diff_raises_value_error():
    with pytest.raises(ValueError):
        diff_engine.run_diff(uuid.uuid4())


def test_latest_completed_run_picks_newest_completed(db_session, world):
    tenant, agent, suite = world
    v = agent.versions[0]
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    seed_run(db_session, tenant, v, suite, _results(suite, ["a", "b"]), created_at=now - timedelta(hours=2))
    newer = seed_run(db_session, tenant, v, suite, _results(suite, ["a", "b"]), created_at=now - timedelta(hours=1))
    seed_run(db_session, tenant, v, suite, [], status="pending", created_at=now)
    found = diff_engine.latest_completed_run(db_session, v.id, suite.id)
    assert found.id == newer.id
