"""Gate engine: pass rate, policy thresholds, ARS floor and error-budget reasons."""
import uuid

import pytest

from apps.api.models import GatePolicy
from apps.api.services import gate_engine
from seeding import seed_agent, seed_run, seed_snapshot, seed_snapshots, seed_suite


@pytest.fixture
def world(db_session, make_tenant):
    tenant = make_tenant()
    agent = seed_agent(db_session, tenant)
    suite = seed_suite(db_session, agent, n_cases=4)
    return tenant, agent, suite


def _run(db, world, passes, metrics=None):
    tenant, agent, suite = world
    results = []
    for i, p in enumerate(passes):
        r = {"case_id": suite.case_ids[i], "passed": p}
        if metrics:
            r["metrics"] = metrics
        results.append(r)
    return seed_run(db, tenant, agent.versions[0], suite, results)


def test_unknown_run_raises():
    with pytest.raises(ValueError):
        gate_engine.evaluate(uuid.uuid4())


def test_no_results_blocks(db_session, world):
    res = gate_engine.evaluate(_run(db_session, world, []).id)
    assert res.passed is False and "no case results" in res.reasons[0]


def test_all_pass_no_snapshot_passes(db_session, world):
    res = gate_engine.evaluate(_run(db_session, world, [True] * 4).id)
    assert res.passed is True and res.reasons == []


def test_pass_rate_below_default_minimum(db_session, world):
    res = gate_engine.evaluate(_run(db_session, world, [True, True, True, False]).id)
    assert res.passed is False
    assert res.reasons == ["pass_rate 0.75 is below required minimum 0.90"]


def test_pass_rate_exactly_at_minimum_passes(db_session, world):
    tenant, agent, suite = world
    db_session.add(GatePolicy(agent_id=agent.id, min_pass_rate=0.75))
    db_session.commit()
    assert gate_engine.evaluate(_run(db_session, world, [True, True, True, False]).id).passed is True


def test_custom_policy_raises_the_bar(db_session, world):
    _, agent, _ = world
    db_session.add(GatePolicy(agent_id=agent.id, min_pass_rate=1.0))
    db_session.commit()
    res = gate_engine.evaluate(_run(db_session, world, [True, True, True, False]).id)
    assert res.passed is False and "1.00" in res.reasons[0]


def test_policy_cost_and_latency_limits(db_session, world):
    _, agent, _ = world
    db_session.add(GatePolicy(agent_id=agent.id, max_avg_cost_usd=0.001, max_avg_latency_ms=100))
    db_session.commit()
    run = _run(db_session, world, [True] * 4, metrics={"cost_usd": 0.5, "latency_ms": 900})
    res = gate_engine.evaluate(run.id)
    assert res.passed is False
    assert any(r.startswith("avg_cost_usd") for r in res.reasons)
    assert any(r.startswith("avg_latency_ms") for r in res.reasons)


def test_ars_below_minimum_blocks(db_session, world):
    tenant, agent, suite = world
    run = _run(db_session, world, [True] * 4)
    seed_snapshot(db_session, agent.versions[0], run, 0.80)
    res = gate_engine.evaluate(run.id)
    assert res.passed is False
    assert res.reasons == ["ars 0.80 is below minimum 0.85"]


def test_ars_at_minimum_passes(db_session, world):
    _, agent, _ = world
    run = _run(db_session, world, [True] * 4)
    seed_snapshot(db_session, agent.versions[0], run, gate_engine.MIN_ARS)
    assert gate_engine.evaluate(run.id).passed is True


def test_exhausted_error_budget_blocks_even_with_good_run(db_session, world):
    tenant, agent, suite = world
    seed_snapshots(db_session, tenant, agent, suite, [0.5, 0.5, 0.5])  # three earlier breaches
    run = _run(db_session, world, [True] * 4)
    seed_snapshot(db_session, agent.versions[0], run, 0.97)  # newest, itself fine
    res = gate_engine.evaluate(run.id)
    assert res.passed is False
    assert res.reasons == ["error budget exhausted: 3/4 recent runs below target"]


def test_budget_only_looks_at_snapshots_up_to_the_run(db_session, world):
    tenant, agent, suite = world
    from datetime import datetime, timedelta, timezone

    run = _run(db_session, world, [True] * 4)
    # the run's snapshot predates the breaches seeded below (those start at now-1h)
    seed_snapshot(db_session, agent.versions[0], run, 0.97,
                  created_at=datetime.now(timezone.utc) - timedelta(hours=3))
    # breaches recorded AFTER this run must not retroactively fail it
    seed_snapshots(db_session, tenant, agent, suite, [0.5, 0.5, 0.5])
    assert gate_engine.evaluate(run.id).passed is True


def test_multiple_reasons_accumulate(db_session, world):
    tenant, agent, suite = world
    seed_snapshots(db_session, tenant, agent, suite, [0.5, 0.5, 0.5])
    run = _run(db_session, world, [True, False, False, False])
    seed_snapshot(db_session, agent.versions[0], run, 0.4)
    res = gate_engine.evaluate(run.id)
    assert res.passed is False and len(res.reasons) == 3
