"""Sprint 0-A endpoint tests: summary, latest_ars, cross-agent lists, run detail
additions, diff context, mining clusters, API-key management, tenant isolation.

Runs against a throwaway Postgres database (see conftest.py); needs no Redpanda,
ClickHouse or LLM.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration


def _seed(tenant_id: str, name: str = "seed-agent") -> dict:
    """One agent with two versions, a suite, a completed passing run with ARS, a
    diff between two runs, a load run and a failure cluster."""
    from apps.api.core.db import SessionLocal
    from apps.api.models import (
        Agent, AgentVersion, ARSSnapshot, BehaviorDiff, EvalCase, EvalCaseResult,
        EvalRun, EvalSuite, FailureCluster, LoadRun,
    )

    tid = uuid.UUID(tenant_id)
    db = SessionLocal()
    try:
        agent = Agent(tenant_id=tid, name=f"{name}-{uuid.uuid4().hex[:6]}")
        db.add(agent)
        db.flush()
        versions = []
        for label in ("v1", "v2"):
            v = AgentVersion(
                agent_id=agent.id, version_label=label, model_name="m",
                prompt_text="p", content_hash=uuid.uuid4().hex, entrypoint="x:y",
            )
            db.add(v)
            versions.append(v)
        suite = EvalSuite(agent_id=agent.id, name="smoke")
        db.add(suite)
        db.flush()
        case = EvalCase(suite_id=suite.id, case_key="c1", turns=[], expectations={})
        db.add(case)
        db.flush()

        runs = []
        now = datetime.now(timezone.utc)
        for i, v in enumerate(versions):
            ts = now - timedelta(minutes=10 - i)  # v1 older than v2 (same-txn now() ties)
            run = EvalRun(
                tenant_id=tid, agent_version_id=v.id, suite_id=suite.id,
                status="completed", triggered_by="manual", created_at=ts,
            )
            db.add(run)
            db.flush()
            res = EvalCaseResult(
                eval_run_id=run.id, case_id=case.id, passed=True,
                metrics={"cost_usd": 0.001, "latency_ms": 100},
                transcript=[], scorer_results={},
            )
            db.add(res)
            db.add(ARSSnapshot(
                agent_version_id=v.id, eval_run_id=run.id, ars=0.95 if v.version_label == "v2" else 0.9,
                correctness=1.0, safety=0.9, latency=0.8, cost=0.7, created_at=ts,
            ))
            runs.append(run)
            db.flush()

        diff = BehaviorDiff(
            agent_id=agent.id, version_a_id=versions[0].id, version_b_id=versions[1].id,
            suite_id=suite.id, eval_run_a_id=runs[0].id, eval_run_b_id=runs[1].id,
            code_changed=True, behavior_changed=False, mean_similarity=0.97,
            similarity_threshold=0.9, classification="safe_refactor",
            per_case_similarity={"c1": 0.97}, detail="d",
        )
        load = LoadRun(
            tenant_id=tid, agent_version_id=versions[1].id, message="hi",
            concurrency=2, duration_seconds=5, status="completed", triggered_by="manual",
            total_requests=10, p95_latency_ms=120.0, error_rate=0.0,
        )
        cluster = FailureCluster(
            agent_id=agent.id, cluster_label=0, size=3, bad_outcome_rate=0.5,
            representative_case_result_id=res.id, representative_text="boom",
        )
        db.add_all([diff, load, cluster])
        db.commit()
        return {
            "agent_id": str(agent.id), "agent_name": agent.name,
            "run_id": str(runs[1].id), "diff_id": str(diff.id),
            "load_id": str(load.id),
        }
    finally:
        db.close()


# ---------- summary + latest_ars ----------

def test_summary_empty_tenant(client, tenant_a):
    r = client.get("/dashboard/summary", headers=tenant_a["headers"])
    assert r.status_code == 200
    assert r.json() == {
        "total_agents": 0, "runs_last_7d": 0, "gate_pass_rate": None,
        "healthy_budget_count": 0, "total_budget_count": 0,
    }


def test_summary_and_latest_ars(client, tenant_a):
    seeded = _seed(tenant_a["tenant_id"])
    body = client.get("/dashboard/summary", headers=tenant_a["headers"]).json()
    assert body["total_agents"] == 1
    assert body["runs_last_7d"] == 2
    assert body["gate_pass_rate"] == 1.0
    assert body["total_budget_count"] == 1
    assert body["healthy_budget_count"] == 1  # both snapshots >= 0.9 target

    agents = client.get("/dashboard/agents", headers=tenant_a["headers"]).json()
    assert len(agents) == 1
    assert agents[0]["id"] == seeded["agent_id"]
    assert agents[0]["latest_ars"] == pytest.approx(0.95)


def test_agent_without_snapshots_has_null_latest_ars(client, tenant_a):
    h = tenant_a["headers"]
    from apps.api.core.db import SessionLocal
    from apps.api.models import Agent

    db = SessionLocal()
    try:
        db.add(Agent(tenant_id=uuid.UUID(tenant_a["tenant_id"]), name="bare"))
        db.commit()
    finally:
        db.close()
    agents = client.get("/dashboard/agents", headers=h).json()
    assert agents[0]["latest_ars"] is None


# ---------- cross-agent lists ----------

def test_runs_diffs_load_runs_lists(client, tenant_a):
    h = tenant_a["headers"]
    s = _seed(tenant_a["tenant_id"])

    runs = client.get("/dashboard/runs", headers=h).json()
    assert len(runs) == 2
    top = runs[0]
    assert top["agent_id"] == s["agent_id"] and top["agent_name"] == s["agent_name"]
    assert top["suite_name"] == "smoke" and top["status"] == "completed"
    assert top["gate_passed"] is True and top["ars"] in (0.9, 0.95)
    assert {r["version_label"] for r in runs} == {"v1", "v2"}

    assert len(client.get(f"/dashboard/runs?agent_id={s['agent_id']}", headers=h).json()) == 2
    assert client.get(f"/dashboard/runs?agent_id={uuid.uuid4()}", headers=h).json() == []
    assert len(client.get("/dashboard/runs?limit=1", headers=h).json()) == 1

    diffs = client.get("/dashboard/diffs", headers=h).json()
    assert len(diffs) == 1
    d = diffs[0]
    assert d["id"] == s["diff_id"] and d["agent_name"] == s["agent_name"]
    assert (d["version_a_label"], d["version_b_label"]) == ("v1", "v2")
    assert d["suite_name"] == "smoke" and d["classification"] == "safe_refactor"

    loads = client.get("/dashboard/load-runs", headers=h).json()
    assert len(loads) == 1
    assert loads[0]["id"] == s["load_id"]
    assert loads[0]["agent_name"] == s["agent_name"] and loads[0]["version_label"] == "v2"
    assert loads[0]["p95_latency_ms"] == 120.0


def test_lists_are_tenant_scoped(client, tenant_a, tenant_b):
    _seed(tenant_a["tenant_id"])
    hb = tenant_b["headers"]
    for path in ("/dashboard/runs", "/dashboard/diffs", "/dashboard/load-runs", "/dashboard/agents"):
        assert client.get(path, headers=hb).json() == [], path
    assert client.get("/dashboard/summary", headers=hb).json()["total_agents"] == 0


def test_lists_require_auth(client):
    for path in ("/dashboard/runs", "/dashboard/diffs", "/dashboard/load-runs", "/dashboard/summary"):
        assert client.get(path).status_code == 401


# ---------- run detail / diff / traces / clusters ----------

def test_run_detail_additions(client, tenant_a, tenant_b):
    s = _seed(tenant_a["tenant_id"])
    r = client.get(f"/dashboard/runs/{s['run_id']}", headers=tenant_a["headers"])
    assert r.status_code == 200
    b = r.json()
    assert b["agent_id"] == s["agent_id"] and b["agent_name"] == s["agent_name"]
    assert b["version_label"] == "v2" and b["suite_name"] == "smoke"
    assert b["triggered_by"] == "manual" and b["created_at"]
    assert b["ars"] == {"ars": 0.95, "correctness": 1.0, "safety": 0.9, "latency": 0.8, "cost": 0.7}
    assert "case_results" in b and "gate_result" in b  # old fields intact
    assert client.get(f"/dashboard/runs/{s['run_id']}", headers=tenant_b["headers"]).status_code == 404


def test_traces_empty_not_500_when_clickhouse_unavailable(client, tenant_a, monkeypatch):
    s = _seed(tenant_a["tenant_id"])
    from apps.api.routers import dashboard

    def boom():
        raise ConnectionError("clickhouse down")

    monkeypatch.setattr(dashboard, "get_clickhouse", boom)
    r = client.get(f"/dashboard/runs/{s['run_id']}/traces", headers=tenant_a["headers"])
    assert r.status_code == 200 and r.json() == []


def test_diff_response_has_agent_and_version_labels(client, tenant_a, tenant_b):
    s = _seed(tenant_a["tenant_id"])
    r = client.get(f"/diff-runs/{s['diff_id']}", headers=tenant_a["headers"])
    assert r.status_code == 200
    b = r.json()
    assert b["agent_name"] == s["agent_name"]
    assert (b["version_a_label"], b["version_b_label"]) == ("v1", "v2")
    assert b["suite_name"] == "smoke" and b["mean_similarity"] == 0.97
    assert client.get(f"/diff-runs/{s['diff_id']}", headers=tenant_b["headers"]).status_code == 404


def test_mining_clusters_list_and_isolation(client, tenant_a, tenant_b):
    s = _seed(tenant_a["tenant_id"])
    r = client.get(f"/mining/{s['agent_id']}/clusters", headers=tenant_a["headers"])
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["size"] == 3 and rows[0]["representative_text"] == "boom"
    assert client.get(f"/mining/{s['agent_id']}/clusters", headers=tenant_b["headers"]).status_code == 404


# ---------- API keys ----------

def test_api_key_lifecycle(client, tenant_a, tenant_b):
    h = tenant_a["headers"]
    created = client.post("/auth/api-keys", json={"label": "ci pipeline", "role": "developer"}, headers=h)
    assert created.status_code == 201
    c = created.json()
    raw = c["key"]
    assert raw.startswith("rl_live_") and len(raw) > 30
    assert c["label"] == "ci pipeline" and c["role"] == "developer" and c["revoked"] is False
    assert c["last_four"] == raw[-4:]

    # raw key appears only on creation
    listed = client.get("/auth/api-keys", headers=h)
    assert listed.status_code == 200
    assert raw not in listed.text
    item = next(k for k in listed.json() if k["id"] == c["id"])
    assert item["masked_key"].endswith(raw[-4:]) and "key" not in item
    assert item["revoked"] is False

    # the minted key authenticates (existing API-key auth path), with its role
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert me.status_code == 200 and me.json()["role"] == "developer"
    assert me.json()["tenant_id"] == tenant_a["tenant_id"]

    # other tenant can neither see nor revoke it
    assert client.get("/auth/api-keys", headers=tenant_b["headers"]).json() == []
    assert client.delete(f"/auth/api-keys/{c['id']}", headers=tenant_b["headers"]).status_code == 404

    # revoke -> flagged in list, key stops working
    d = client.delete(f"/auth/api-keys/{c['id']}", headers=h)
    assert d.status_code == 200 and d.json()["revoked"] is True
    again = client.delete(f"/auth/api-keys/{c['id']}", headers=h)  # idempotent
    assert again.status_code == 200
    item = next(k for k in client.get("/auth/api-keys", headers=h).json() if k["id"] == c["id"])
    assert item["revoked"] is True and item["revoked_at"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_api_key_management_is_admin_only(client, tenant_a):
    h = tenant_a["headers"]
    raw = client.post("/auth/api-keys", json={"label": "viewer key", "role": "viewer"}, headers=h).json()["key"]
    vh = {"Authorization": f"Bearer {raw}"}
    assert client.get("/auth/api-keys", headers=vh).status_code == 403
    assert client.post("/auth/api-keys", json={"label": "x"}, headers=vh).status_code == 403
    assert client.post("/auth/api-keys", json={"label": "  "}, headers=h).status_code == 422
    assert client.post("/auth/api-keys", json={"label": "x", "role": "root"}, headers=h).status_code == 422
    assert client.get("/auth/api-keys").status_code == 401


# ---------- non-DB fixes ----------

def test_llm_judge_fails_closed_without_key(monkeypatch):
    from types import SimpleNamespace

    from apps.api.services.scorers import llm_judge

    monkeypatch.setattr(llm_judge, "get_settings", lambda: SimpleNamespace(gemini_api_key=""))
    scorer = llm_judge.LLMJudgeScorer()  # constructing must not need a key
    case = SimpleNamespace(expectations={"judge_rubric": "be nice"})
    res = scorer.score(case, [])
    assert res.passed is False
    assert res.detail == "LLM judge unavailable: GEMINI_API_KEY is not set"
    # no rubric -> still passes without touching the judge
    assert scorer.score(SimpleNamespace(expectations={}), []).passed is True
