"""ARS computation and error-budget evaluation."""
import pytest

from apps.api.models import EvalCase
from apps.api.services import ars_engine
from seeding import seed_agent, seed_run, seed_snapshots, seed_suite


@pytest.fixture
def world(db_session, make_tenant):
    tenant = make_tenant()
    agent = seed_agent(db_session, tenant)
    suite = seed_suite(db_session, agent, n_cases=4)
    return tenant, agent, suite


def _compute(db, tenant, agent, suite, results):
    run = seed_run(db, tenant, agent.versions[0], suite, results)
    from apps.api.models import EvalRun

    return ars_engine.compute_snapshot(db, db.get(EvalRun, run.id))


def _res(suite, i, passed=True, scorers=None, metrics=None):
    r = {"case_id": suite.case_ids[i], "passed": passed, "scorer_results": scorers or {}}
    if metrics is not None:
        r["metrics"] = metrics
    return r


def test_weights_sum_to_one():
    assert sum(ars_engine.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(ars_engine.WEIGHTS) == {"correctness", "safety", "latency", "cost"}


def test_no_results_defaults_to_perfect(db_session, world):
    snap = _compute(db_session, *world, [])
    assert (snap.correctness, snap.safety, snap.latency, snap.cost, snap.ars) == (1.0, 1.0, 1.0, 1.0, 1.0)


def test_correctness_is_pass_ratio_and_weighted(db_session, world):
    tenant, agent, suite = world
    snap = _compute(db_session, tenant, agent, suite, [_res(suite, i, passed=i != 0) for i in range(4)])
    assert snap.correctness == 0.75
    assert (snap.safety, snap.latency, snap.cost) == (1.0, 1.0, 1.0)
    assert snap.ars == pytest.approx(0.4 * 0.75 + 0.2 * 3, abs=1e-4)


def test_ars_equals_weighted_sum_of_components(db_session, world):
    tenant, agent, suite = world
    scorers = {"ContainsMatchScorer": {"passed": False, "detail": "contains forbidden substrings: ['x']"}}
    snap = _compute(db_session, tenant, agent, suite, [
        _res(suite, 0, passed=False, scorers=scorers), _res(suite, 1), _res(suite, 2), _res(suite, 3),
    ])
    expected = sum(getattr(snap, k) * w for k, w in ars_engine.WEIGHTS.items())
    assert snap.ars == pytest.approx(expected, abs=1e-4)


def test_snapshot_is_persisted_and_linked(db_session, world):
    tenant, agent, suite = world
    snap = _compute(db_session, tenant, agent, suite, [_res(suite, 0)])
    assert snap.id is not None
    assert snap.agent_version_id == agent.versions[0].id
    assert [s.id for s in ars_engine.agent_snapshots(db_session, agent.id)] == [snap.id]


def test_forbidden_substring_is_unsafe(db_session, world):
    tenant, agent, suite = world
    bad = {"ContainsMatchScorer": {"passed": False, "detail": "contains forbidden substrings: ['x']"}}
    snap = _compute(db_session, tenant, agent, suite, [_res(suite, 0, False, bad), _res(suite, 1)])
    assert snap.safety == 0.5


def test_judge_failure_only_unsafe_when_case_has_guard(db_session, world):
    tenant, agent, suite = world
    case = db_session.get(EvalCase, suite.case_ids[0])
    case.expectations = {"must_not_contain": ["secret"]}
    db_session.commit()
    judge_fail = {"LLMJudgeScorer": {"passed": False, "detail": "bad"}}
    snap = _compute(db_session, tenant, agent, suite, [
        _res(suite, 0, False, judge_fail),  # guarded case -> unsafe
        _res(suite, 1, False, judge_fail),  # unguarded case -> not a safety failure
    ])
    assert snap.safety == 0.5


def test_latency_default_limit_applies_when_no_max_configured(db_session, world):
    tenant, agent, suite = world
    no_limit = {"LatencyScorer": {"passed": True, "detail": "no max_latency_ms expectation configured"}}
    snap = _compute(db_session, tenant, agent, suite, [
        _res(suite, 0, scorers=no_limit, metrics={"latency_ms": ars_engine.DEFAULT_MAX_LATENCY_MS}),
        _res(suite, 1, scorers=no_limit, metrics={"latency_ms": ars_engine.DEFAULT_MAX_LATENCY_MS + 1}),
    ])
    assert snap.latency == 0.5


def test_cost_default_limit_applies_when_no_max_configured(db_session, world):
    tenant, agent, suite = world
    no_limit = {"CostScorer": {"passed": True, "detail": "no max_cost_usd expectation configured"}}
    snap = _compute(db_session, tenant, agent, suite, [
        _res(suite, 0, scorers=no_limit, metrics={"cost_usd": ars_engine.DEFAULT_MAX_COST_USD}),
        _res(suite, 1, scorers=no_limit, metrics={"cost_usd": ars_engine.DEFAULT_MAX_COST_USD * 2}),
    ])
    assert snap.cost == 0.5


def test_explicit_scorer_verdict_beats_metrics(db_session, world):
    tenant, agent, suite = world
    scorers = {
        "LatencyScorer": {"passed": False, "detail": "total latency 9ms exceeds max 5ms"},
        "CostScorer": {"passed": False, "detail": "total cost $1 exceeds max $0.5"},
    }
    snap = _compute(db_session, tenant, agent, suite, [
        _res(suite, 0, scorers=scorers, metrics={"latency_ms": 1, "cost_usd": 0.0}),
    ])
    assert snap.latency == 0.0 and snap.cost == 0.0


# ---------------- error budget ----------------
def _budget(db, tenant, agent, suite, values, **kw):
    snaps = seed_snapshots(db, tenant, agent, suite, values)
    return ars_engine.evaluate_error_budget(db, agent.id, **kw), snaps


def test_zero_runs_is_healthy(db_session, world):
    _, agent, _ = world
    b = ars_engine.evaluate_error_budget(db_session, agent.id)
    assert (b.status, b.runs_considered, b.breached, b.exhausted) == ("healthy", 0, 0, False)
    assert b.window == ars_engine.WINDOW and b.target == ars_engine.ARS_TARGET


def test_all_above_target_is_healthy(db_session, world):
    b, _ = _budget(db_session, *world, [0.95, 0.99, 0.9])  # exactly target is not a breach
    assert (b.status, b.breached, b.above_target) == ("healthy", 0, 3)


@pytest.mark.parametrize("values", [[0.5, 0.95, 0.95], [0.5, 0.6, 0.95]])
def test_one_or_two_breaches_is_at_risk(db_session, world, values):
    b, _ = _budget(db_session, *world, values)
    assert b.status == "at_risk" and not b.exhausted
    assert b.breached == sum(v < 0.9 for v in values)


def test_more_than_allowed_breaches_is_frozen(db_session, world):
    b, _ = _budget(db_session, *world, [0.5, 0.6, 0.7])
    assert (b.status, b.breached, b.exhausted) == ("frozen", 3, True)
    assert b.allowed_breaches == 2


def test_only_last_window_runs_count(db_session, world):
    # three old breaches fall out of the 5-run window
    b, _ = _budget(db_session, *world, [0.1, 0.1, 0.1, 0.95, 0.95, 0.95, 0.95, 0.95])
    assert b.runs_considered == ars_engine.WINDOW
    assert b.status == "healthy"


def test_as_of_cutoff_ignores_later_snapshots(db_session, world):
    tenant, agent, suite = world
    snaps = seed_snapshots(db_session, tenant, agent, suite, [0.95, 0.5, 0.5, 0.5])
    full = ars_engine.evaluate_error_budget(db_session, agent.id)
    assert full.status == "frozen"
    at_2 = ars_engine.evaluate_error_budget(db_session, agent.id, as_of=snaps[1].created_at)
    assert (at_2.status, at_2.runs_considered, at_2.breached) == ("at_risk", 2, 1)
    at_0 = ars_engine.evaluate_error_budget(db_session, agent.id, as_of=snaps[0].created_at)
    assert at_0.status == "healthy"


def test_budget_is_per_agent(db_session, make_tenant):
    tenant = make_tenant()
    a1, a2 = seed_agent(db_session, tenant), seed_agent(db_session, tenant)
    s1, s2 = seed_suite(db_session, a1), seed_suite(db_session, a2)
    seed_snapshots(db_session, tenant, a1, s1, [0.1, 0.1, 0.1])
    seed_snapshots(db_session, tenant, a2, s2, [0.99])
    assert ars_engine.evaluate_error_budget(db_session, a1.id).status == "frozen"
    assert ars_engine.evaluate_error_budget(db_session, a2.id).status == "healthy"
