"""Cross-tenant isolation, role enforcement and unauthenticated access."""
import uuid

import pytest

from apps.api.models import CandidateCase, DiffRun, FailureCluster, LoadRun
from seeding import seed_agent, seed_run, seed_snapshot, seed_suite


@pytest.fixture
def world(db_session, make_tenant, make_user):
    ta, tb = make_tenant("tenant-a"), make_tenant("tenant-b")
    a_admin, b_admin = make_user("admin", ta), make_user("admin", tb)
    agent = seed_agent(db_session, ta, name="a-agent", versions=2)
    suite = seed_suite(db_session, agent, n_cases=2)
    ver = agent.versions[0]
    run = seed_run(db_session, ta, ver, suite, [{"case_id": c, "passed": True} for c in suite.case_ids])
    seed_snapshot(db_session, ver, run, 0.95)
    diff = DiffRun(tenant_id=ta.id, agent_id=agent.id, suite_id=suite.id, run_a_id=run.id, run_b_id=run.id)
    load = LoadRun(tenant_id=ta.id, agent_version_id=ver.id, suite_id=suite.id, concurrency=5, duration_seconds=10)
    cluster = FailureCluster(agent_id=agent.id, cluster_index=0, label="l", representative="r",
                             case_count=1, bad_outcome_rate=1.0)
    db_session.add_all([diff, load, cluster])
    db_session.flush()
    cand = CandidateCase(agent_id=agent.id, cluster_id=cluster.id, case_key="k", prompt="p")
    db_session.add(cand)
    db_session.commit()
    return type("W", (), dict(
        a=a_admin, b=b_admin, agent=agent, suite=suite, ver=ver, ver2=agent.versions[1], run=run,
        diff=diff.id, load=load.id, cluster=cluster.id, cand=cand.id, ta=ta, tb=tb,
    ))


def _read_paths(w):
    return [
        f"/dashboard/agents/{w.agent.id}",
        f"/dashboard/agents/{w.agent.id}/ars-history",
        f"/dashboard/agents/{w.agent.id}/error-budget",
        f"/dashboard/agents/{w.agent.id}/drift-alerts",
        f"/dashboard/runs/{w.run.id}",
        f"/dashboard/runs/{w.run.id}/traces",
        f"/eval-runs/{w.run.id}",
        f"/diffs/{w.diff}",
        f"/load-runs/{w.load}",
        f"/mining/{w.agent.id}/clusters",
        f"/mining/{w.agent.id}/candidates",
    ]


def test_owner_can_read_every_resource(client, world):
    for path in _read_paths(world):
        assert client.get(path, headers=world.a.headers).status_code == 200, path


def test_other_tenant_gets_404_on_reads(client, world):
    for path in _read_paths(world):
        r = client.get(path, headers=world.b.headers)
        assert r.status_code == 404, path
        assert "a-agent" not in r.text


def test_other_tenant_gets_404_on_writes(client, world):
    h = world.b.headers
    w = world
    calls = [
        ("post", "/eval-runs", {"agent_version_id": str(w.ver.id), "suite_id": str(w.suite.id)}),
        ("post", "/diffs", {"agent_id": str(w.agent.id), "suite_id": str(w.suite.id),
                            "version_a_id": str(w.ver.id), "version_b_id": str(w.ver2.id)}),
        ("post", "/load-runs", {"agent_version_id": str(w.ver.id), "suite_id": str(w.suite.id)}),
        ("post", f"/mining/{w.agent.id}/run", None),
        ("post", f"/mining/clusters/{w.cluster}/dismiss", None),
        ("post", f"/mining/candidates/{w.cand}/review", {"decision": "approve"}),
        ("post", f"/agents/{w.agent.id}/versions", {
            "version_label": "x", "model_name": "m", "prompt_text": "p", "content_hash": "h", "entrypoint": "a:b"}),
    ]
    for method, path, body in calls:
        r = getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (path, r.text)


def test_failed_cross_tenant_writes_leave_no_rows(client, db_session, world):
    from apps.api.models import EvalRun

    client.post("/eval-runs", headers=world.b.headers,
                json={"agent_version_id": str(world.ver.id), "suite_id": str(world.suite.id)})
    client.post(f"/mining/clusters/{world.cluster}/dismiss", headers=world.b.headers)
    client.post(f"/mining/candidates/{world.cand}/review", headers=world.b.headers, json={"decision": "reject"})
    db_session.expire_all()
    assert db_session.query(EvalRun).count() == 1
    assert db_session.get(FailureCluster, world.cluster).dismissed is False
    assert db_session.get(CandidateCase, world.cand).status == "pending"


def test_other_tenant_listings_are_empty(client, world):
    h = world.b.headers
    for path in ("/dashboard/agents", "/dashboard/runs", "/diffs", "/load-runs", "/eval-suites"):
        assert client.get(path, headers=h).json() == [], path
    s = client.get("/dashboard/summary", headers=h).json()
    assert s["total_agents"] == 0 and s["runs_last_7d"] == 0


def test_owner_listings_show_only_own_rows(client, world):
    assert [a["name"] for a in client.get("/dashboard/agents", headers=world.a.headers).json()] == ["a-agent"]
    assert len(client.get("/dashboard/runs", headers=world.a.headers).json()) == 1
    assert len(client.get("/diffs", headers=world.a.headers).json()) == 1


def test_same_agent_name_in_two_tenants_is_independent(client, world):
    r = client.post("/agents", headers=world.b.headers, json={"name": "a-agent"})
    assert r.status_code == 201
    assert r.json()["id"] != str(world.agent.id)


def test_cross_tenant_api_key_is_scoped(client, world, api_key):
    key = api_key.make(role="admin", tenant=world.tb)
    assert client.get(f"/dashboard/runs/{world.run.id}", headers=key.headers).status_code == 404
    own = api_key.make(role="admin", tenant=world.ta)
    assert client.get(f"/dashboard/runs/{world.run.id}", headers=own.headers).status_code == 200


# ---------------- roles ----------------
def _developer_calls(w):
    return [
        ("/eval-runs", {"agent_version_id": str(w.ver.id), "suite_id": str(w.suite.id)}),
        ("/diffs", {"agent_id": str(w.agent.id), "suite_id": str(w.suite.id),
                    "version_a_id": str(w.ver.id), "version_b_id": str(w.ver2.id)}),
        ("/load-runs", {"agent_version_id": str(w.ver.id), "suite_id": str(w.suite.id)}),
        ("/agents", {"name": "new-agent"}),
        (f"/agents/{w.agent.id}/versions", {
            "version_label": "x", "model_name": "m", "prompt_text": "p", "content_hash": "h", "entrypoint": "a:b"}),
        (f"/mining/{w.agent.id}/run", None),
        (f"/mining/clusters/{w.cluster}/dismiss", None),
        (f"/mining/candidates/{w.cand}/review", {"decision": "approve"}),
    ]


def test_viewer_gets_403_on_developer_endpoints(client, make_user, world):
    viewer = make_user("viewer", world.ta)
    for path, body in _developer_calls(world):
        r = client.post(path, headers=viewer.headers, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, path


def test_viewer_can_read(client, make_user, world):
    viewer = make_user("viewer", world.ta)
    for path in _read_paths(world):
        assert client.get(path, headers=viewer.headers).status_code == 200, path


def test_viewer_api_key_gets_403_on_developer_endpoints(client, api_key, world):
    key = api_key.make(role="viewer", tenant=world.ta)
    assert client.post("/eval-runs", headers=key.headers,
                       json={"agent_version_id": str(world.ver.id), "suite_id": str(world.suite.id)}).status_code == 403


def test_developer_can_create_eval_run_and_diff(client, make_user, world):
    dev = make_user("developer", world.ta)
    r = client.post("/eval-runs", headers=dev.headers,
                    json={"agent_version_id": str(world.ver.id), "suite_id": str(world.suite.id)})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    d = client.post("/diffs", headers=dev.headers, json={
        "agent_id": str(world.agent.id), "suite_id": str(world.suite.id),
        "version_a_id": str(world.ver.id), "version_b_id": str(world.ver2.id)})
    assert d.status_code == 201 and d.json()["status"] == "pending"


def test_eval_run_with_foreign_suite_for_own_version_is_404(client, db_session, make_user, world):
    other = seed_agent(db_session, world.ta, name="other-agent")
    other_suite = seed_suite(db_session, other, 1)
    r = client.post("/eval-runs", headers=world.a.headers,
                    json={"agent_version_id": str(world.ver.id), "suite_id": str(other_suite.id)})
    assert r.status_code == 404


# ---------------- unauthenticated ----------------
@pytest.mark.parametrize("method,path", [
    ("get", "/dashboard/summary"),
    ("get", "/dashboard/agents"),
    ("get", "/dashboard/runs"),
    ("get", "/diffs"),
    ("get", "/load-runs"),
    ("get", "/eval-suites"),
    ("get", f"/eval-runs/{uuid.uuid4()}"),
    ("get", f"/mining/{uuid.uuid4()}/clusters"),
    ("post", "/eval-runs"),
    ("post", "/diffs"),
    ("post", "/agents"),
    ("get", "/auth/api-keys"),
])
def test_unauthenticated_is_401(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 401
    r2 = getattr(client, method)(path, headers={"Authorization": "Bearer rl_bogus"})
    assert r2.status_code == 401
