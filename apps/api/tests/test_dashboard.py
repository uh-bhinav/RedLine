"""Dashboard read-model response shapes, driven by rows inserted straight into the DB."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.models import DriftAlert, EvalCase
from seeding import seed_agent, seed_run, seed_snapshot, seed_suite, transcript

TOOL_TRANSCRIPT = [
    {"role": "user", "content": "weather in Paris?"},
    {
        "role": "assistant", "content": "It is sunny.", "latency_ms": 120, "cost_usd": 0.002,
        "tool_calls": [{"name": "get_weather", "arguments": {"city": "Paris"}, "result": "sunny", "latency_ms": 40}],
    },
    {"role": "user", "content": "thanks"},
    {"role": "assistant", "content": "Welcome!", "latency_ms": 5, "cost_usd": 0.0001},
]


@pytest.fixture
def world(db_session, make_user):
    user = make_user("viewer")
    tenant = user.tenant
    agent = seed_agent(db_session, tenant, name="rag-agent", versions=2)
    empty_agent = seed_agent(db_session, tenant, name="idle-agent", versions=0)
    suite = seed_suite(db_session, agent, n_cases=2)
    case = db_session.get(EvalCase, suite.case_ids[0])
    case.is_chaos = True
    db_session.commit()

    now = datetime.now(timezone.utc)
    old = seed_run(db_session, tenant, agent.versions[0], suite,
                   [{"case_id": c, "passed": True} for c in suite.case_ids],
                   created_at=now - timedelta(days=10))
    good = seed_run(db_session, tenant, agent.versions[1], suite,
                    [{"case_id": suite.case_ids[0], "passed": True, "transcript": TOOL_TRANSCRIPT},
                     {"case_id": suite.case_ids[1], "passed": True}],
                    created_at=now - timedelta(minutes=5))
    pending = seed_run(db_session, tenant, agent.versions[1], suite, [], status="pending", created_at=now)
    seed_snapshot(db_session, agent.versions[0], old, 0.80, created_at=now - timedelta(days=10),
                  correctness=0.7, safety=0.8, latency=0.9, cost=1.0)
    seed_snapshot(db_session, agent.versions[1], good, 0.95, created_at=now - timedelta(minutes=5),
                  correctness=1.0, safety=1.0, latency=0.9, cost=0.9)
    db_session.add(DriftAlert(
        agent_id=agent.id, drift_type="metric", metric="ars", baseline_value=0.9, current_value=0.7,
        message="dropped", eval_run_id=good.id,
    ))
    db_session.commit()
    return type("W", (), dict(user=user, agent=agent, empty=empty_agent, suite=suite,
                              old=old, good=good, pending=pending))


def test_summary_shape_and_values(client, world):
    r = client.get("/dashboard/summary", headers=world.user.headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"total_agents", "runs_last_7d", "gate_pass_rate", "healthy_budget_count", "total_budget_count"}
    assert body["total_agents"] == 2 and body["total_budget_count"] == 2
    assert body["runs_last_7d"] == 2  # the 10-day-old run is excluded
    assert body["gate_pass_rate"] is not None and 0 <= body["gate_pass_rate"] <= 1
    assert body["healthy_budget_count"] == 2


def test_summary_empty_tenant(client, make_user):
    u = make_user("viewer")
    assert client.get("/dashboard/summary", headers=u.headers).json() == {
        "total_agents": 0, "runs_last_7d": 0, "gate_pass_rate": None,
        "healthy_budget_count": 0, "total_budget_count": 0,
    }


def test_agents_list_shape(client, world):
    r = client.get("/dashboard/agents", headers=world.user.headers)
    assert r.status_code == 200
    items = {a["name"]: a for a in r.json()}
    assert set(items) == {"rag-agent", "idle-agent"}
    rag = items["rag-agent"]
    assert set(rag) == {"id", "name", "description", "latest_version_label", "latest_run", "latest_ars",
                        "error_budget_status", "created_at"}
    assert rag["latest_ars"] == 0.95
    assert rag["error_budget_status"] in {"healthy", "at_risk", "frozen"}
    assert set(rag["latest_run"]) == {"id", "status", "gate_passed", "created_at"}
    assert rag["latest_run"]["id"] == str(world.pending.id)
    assert rag["latest_run"]["gate_passed"] is None  # pending run has no verdict
    idle = items["idle-agent"]
    assert idle["latest_run"] is None and idle["latest_ars"] is None
    assert idle["latest_version_label"] is None and idle["error_budget_status"] == "healthy"


def test_agent_detail_shape(client, world):
    r = client.get(f"/dashboard/agents/{world.agent.id}", headers=world.user.headers)
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"id", "name", "description", "created_at", "latest_version", "versions", "suites",
                      "recent_runs", "latest_ars", "latest_gate", "error_budget", "drift_alerts", "load_runs"}
    assert len(b["versions"]) == 2 and b["latest_version"]["id"] == b["versions"][0]["id"]
    assert set(b["versions"][0]) == {"id", "version_label", "model_name", "content_hash", "entrypoint", "created_at"}
    assert b["suites"] == [{"id": str(world.suite.id), "agent_id": str(world.agent.id),
                            "name": b["suites"][0]["name"], "case_count": 2}]
    assert len(b["recent_runs"]) == 3
    assert b["recent_runs"][0]["status"] == "pending"
    assert b["latest_ars"] == 0.95
    assert b["latest_gate"]["passed"] is True and b["latest_gate"]["reasons"] == []
    assert b["error_budget"]["status"] == "at_risk"  # the 0.80 run breached
    assert b["error_budget"]["breached"] == 1 and b["error_budget"]["window"] == 5
    assert [a["message"] for a in b["drift_alerts"]] == ["dropped"]
    assert b["drift_alerts"][0]["agent_name"] == "rag-agent"
    assert b["load_runs"] == []


def test_agent_detail_without_versions(client, world):
    b = client.get(f"/dashboard/agents/{world.empty.id}", headers=world.user.headers).json()
    assert b["latest_version"] is None and b["versions"] == [] and b["latest_gate"] is None
    assert b["error_budget"]["status"] == "healthy" and b["error_budget"]["runs_considered"] == 0


def test_run_detail_shape(client, world):
    r = client.get(f"/dashboard/runs/{world.good.id}", headers=world.user.headers)
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"id", "status", "triggered_by", "agent_id", "agent_name", "version_label", "suite_name",
                      "started_at", "completed_at", "created_at", "gate_result", "ars", "cases"}
    assert (b["agent_name"], b["version_label"], b["status"]) == ("rag-agent", "v2", "completed")
    assert b["gate_result"] == {"passed": True, "reasons": []}
    assert b["ars"] == {"ars": 0.95, "correctness": 1.0, "safety": 1.0, "latency": 0.9, "cost": 0.9}
    assert len(b["cases"]) == 2
    case = next(c for c in b["cases"] if c["case_key"] == "case_0")
    assert set(case) == {"id", "case_key", "description", "is_chaos", "passed", "metrics", "transcript", "scorer_results"}
    assert case["is_chaos"] is True and case["passed"] is True
    assert case["transcript"][1]["tool_calls"][0]["name"] == "get_weather"


def test_pending_run_detail_has_no_gate_or_ars(client, world):
    b = client.get(f"/dashboard/runs/{world.pending.id}", headers=world.user.headers).json()
    assert b["status"] == "pending" and b["gate_result"] is None and b["ars"] is None and b["cases"] == []


def test_traces_expand_tool_calls_and_turns(client, world):
    r = client.get(f"/dashboard/runs/{world.good.id}/traces", headers=world.user.headers)
    assert r.status_code == 200
    events = [e for e in r.json() if e["case_key"] == "case_0"]
    assert [(e["turn"], e["kind"]) for e in events] == [
        (1, "user"), (1, "tool"), (1, "assistant"), (2, "user"), (2, "assistant"),
    ]
    tool = events[1]
    assert tool["name"] == "get_weather" and tool["latency_ms"] == 40
    assert tool["content"] == "get_weather({'city': 'Paris'}) -> sunny"
    assistant = events[2]
    assert assistant["content"] == "It is sunny." and assistant["latency_ms"] == 120
    assert assistant["cost_usd"] == 0.002 and assistant["passed"] is True
    assert set(events[0]) == {"case_key", "turn", "kind", "name", "content", "latency_ms", "cost_usd", "passed"}
    assert events[0]["name"] is None and events[0]["passed"] is None


def test_ars_history_is_chronological_with_components(client, world):
    r = client.get(f"/dashboard/agents/{world.agent.id}/ars-history", headers=world.user.headers)
    assert r.status_code == 200
    pts = r.json()
    assert [p["version_label"] for p in pts] == ["v1", "v2"]
    assert [p["ars"] for p in pts] == [0.80, 0.95]
    assert set(pts[0]) == {"eval_run_id", "version_label", "ars", "correctness", "safety", "latency", "cost", "created_at"}
    assert pts[0]["correctness"] == 0.7 and pts[1]["eval_run_id"] == str(world.good.id)
    assert client.get(f"/dashboard/agents/{world.empty.id}/ars-history", headers=world.user.headers).json() == []


def test_error_budget_and_drift_alert_endpoints(client, world):
    h = world.user.headers
    eb = client.get(f"/dashboard/agents/{world.agent.id}/error-budget", headers=h).json()
    assert set(eb) == {"status", "window", "runs_considered", "above_target", "breached",
                       "allowed_breaches", "exhausted", "target"}
    assert eb["runs_considered"] == 2 and eb["above_target"] == 1
    alerts = client.get(f"/dashboard/agents/{world.agent.id}/drift-alerts", headers=h).json()
    assert len(alerts) == 1
    assert set(alerts[0]) == {"id", "agent_id", "agent_name", "drift_type", "metric", "baseline_value",
                              "current_value", "message", "eval_run_id", "diff_run_id", "detected_at"}


def test_runs_list_and_agent_filter(client, world):
    h = world.user.headers
    runs = client.get("/dashboard/runs", headers=h).json()
    assert len(runs) == 3
    assert [r["status"] for r in runs][0] == "pending"  # newest first
    assert set(runs[0]) == {"id", "agent_id", "agent_name", "version_label", "suite_name", "status",
                            "triggered_by", "gate_passed", "ars", "created_at", "completed_at"}
    by_id = {r["id"]: r for r in runs}
    assert by_id[str(world.good.id)]["ars"] == 0.95 and by_id[str(world.good.id)]["gate_passed"] is True
    assert client.get(f"/dashboard/runs?agent_id={world.empty.id}", headers=h).json() == []
    assert len(client.get(f"/dashboard/runs?agent_id={world.agent.id}", headers=h).json()) == 3


def test_failed_gate_surfaces_in_run_detail(client, db_session, make_user):
    user = make_user("viewer")
    agent = seed_agent(db_session, user.tenant)
    suite = seed_suite(db_session, agent, n_cases=2)
    run = seed_run(db_session, user.tenant, agent.versions[0], suite, [
        {"case_id": suite.case_ids[0], "passed": True, "transcript": transcript("q", "a")},
        {"case_id": suite.case_ids[1], "passed": False, "transcript": transcript("q2", "a")},
    ])
    b = client.get(f"/dashboard/runs/{run.id}", headers=user.headers).json()
    assert b["gate_result"]["passed"] is False
    assert b["gate_result"]["reasons"][0].startswith("pass_rate 0.50")


def test_unknown_ids_404_and_bad_ids_422(client, world):
    h = world.user.headers
    ghost = uuid.uuid4()
    for path in (f"/dashboard/agents/{ghost}", f"/dashboard/agents/{ghost}/ars-history",
                 f"/dashboard/agents/{ghost}/error-budget", f"/dashboard/runs/{ghost}",
                 f"/dashboard/runs/{ghost}/traces"):
        assert client.get(path, headers=h).status_code == 404, path
    assert client.get("/dashboard/runs/not-a-uuid", headers=h).status_code == 422
