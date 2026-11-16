"""Row-seeding helpers shared by the DB-backed tests (imported as `seeding`; tests/ is on sys.path).

Everything commits, because services such as gate_engine / diff_engine open their own sessions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.api.models import (
    Agent,
    AgentVersion,
    ARSSnapshot,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def seed_agent(db, tenant, name: str | None = None, versions: int = 1):
    agent = Agent(tenant_id=tenant.id, name=name or f"agent-{uuid.uuid4().hex[:6]}", description="d")
    db.add(agent)
    db.flush()
    vers = []
    for i in range(versions):
        v = AgentVersion(
            agent_id=agent.id, version_label=f"v{i + 1}", model_name="m", prompt_text="p",
            content_hash=uuid.uuid4().hex, entrypoint="mod:fn",
        )
        db.add(v)
        vers.append(v)
    db.commit()
    return SimpleNamespace(id=agent.id, name=agent.name, versions=[SimpleNamespace(id=v.id, label=v.version_label, hash=v.content_hash) for v in vers])


def seed_suite(db, agent, n_cases: int = 2, expectations: dict | None = None):
    suite = EvalSuite(agent_id=agent.id, name=f"suite-{uuid.uuid4().hex[:6]}")
    db.add(suite)
    db.flush()
    case_ids = []
    for i in range(n_cases):
        c = EvalCase(
            suite_id=suite.id, case_key=f"case_{i}", description=f"case {i}",
            turns=[{"role": "user", "content": f"question {i}"}],
            expectations=expectations or {},
        )
        db.add(c)
        db.flush()
        case_ids.append(c.id)
    db.commit()
    return SimpleNamespace(id=suite.id, case_ids=case_ids)


def transcript(prompt: str, answer: str, **extra) -> list[dict]:
    return [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": answer, "latency_ms": 10, "cost_usd": 0.001, **extra},
    ]


def seed_run(db, tenant, version, suite, results, status: str = "completed", created_at=None):
    """results: list of dicts {case_id, passed, transcript?, scorer_results?, metrics?}."""
    run = EvalRun(
        tenant_id=tenant.id, agent_version_id=version.id, suite_id=suite.id,
        status=status, triggered_by="manual",
        created_at=created_at or datetime.now(timezone.utc),
        started_at=NOW, completed_at=NOW if status == "completed" else None,
    )
    db.add(run)
    db.flush()
    for r in results:
        db.add(
            EvalCaseResult(
                eval_run_id=run.id, case_id=r["case_id"], passed=r["passed"],
                metrics=r.get("metrics", {"cost_usd": 0.001, "latency_ms": 10}),
                transcript=r.get("transcript", transcript("q", "a")),
                scorer_results=r.get("scorer_results", {}),
            )
        )
    db.commit()
    return SimpleNamespace(id=run.id)


def seed_snapshot(db, version, run, ars: float, created_at=None, **parts):
    snap = ARSSnapshot(
        agent_version_id=version.id, eval_run_id=run.id, ars=ars,
        correctness=parts.get("correctness", ars), safety=parts.get("safety", ars),
        latency=parts.get("latency", ars), cost=parts.get("cost", ars),
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(snap)
    db.commit()
    return SimpleNamespace(id=snap.id, created_at=snap.created_at)


def seed_snapshots(db, tenant, agent, suite, ars_values: list[float]):
    """One completed run + snapshot per value, oldest first, one minute apart."""
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    out = []
    for i, ars in enumerate(ars_values):
        ts = base + timedelta(minutes=i)
        run = seed_run(db, tenant, agent.versions[0], suite,
                       [{"case_id": suite.case_ids[0], "passed": True}], created_at=ts)
        out.append(seed_snapshot(db, agent.versions[0], run, ars, created_at=ts))
    return out
