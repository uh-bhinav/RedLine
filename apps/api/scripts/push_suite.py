"""
Loads an eval suite YAML file into the eval_suites / eval_cases tables.

Phase 1's standalone stand-in for the future `agentbench push-suite` CLI command
(Section 13) -- the same upsert logic this script uses is what that command will
wrap. Idempotent: re-running on the same file updates existing rows in place
rather than duplicating them, using the same uq_* constraints already in the schema.

Usage (from the repo root):
    python -m apps.api.scripts.push_suite eval-suites/rag-agent/baseline.yaml
"""
import sys
from pathlib import Path

import yaml

from apps.api.core.db import SessionLocal
from apps.api.models import Agent, EvalCase, EvalSuite, Tenant
from apps.api.schemas.eval_suite_yaml import EvalSuiteYAML


def push_suite(yaml_path: Path) -> None:
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    suite_def = EvalSuiteYAML.model_validate(raw)

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if tenant is None:
            raise RuntimeError("no tenant found -- run `python -m apps.api.scripts.seed` first")

        agent = (
            db.query(Agent)
            .filter(Agent.tenant_id == tenant.id, Agent.name == suite_def.agent)
            .first()
        )
        if agent is None:
            agent = Agent(tenant_id=tenant.id, name=suite_def.agent)
            db.add(agent)
            db.flush()
            print(f"  created agent '{agent.name}' (id={agent.id})")

        suite = (
            db.query(EvalSuite)
            .filter(EvalSuite.agent_id == agent.id, EvalSuite.name == suite_def.suite)
            .first()
        )
        if suite is None:
            suite = EvalSuite(agent_id=agent.id, name=suite_def.suite)
            db.add(suite)
            db.flush()
            print(f"  created suite '{suite.name}' (id={suite.id})")

        for case_def in suite_def.cases:
            case = (
                db.query(EvalCase)
                .filter(EvalCase.suite_id == suite.id, EvalCase.case_key == case_def.case_key)
                .first()
            )
            turns_data = [t.model_dump() for t in case_def.turns]
            expectations_data = case_def.expectations.model_dump(exclude_none=True)

            if case is None:
                case = EvalCase(
                    suite_id=suite.id,
                    case_key=case_def.case_key,
                    description=case_def.description,
                    turns=turns_data,
                    expectations=expectations_data,
                )
                db.add(case)
                print(f"  + added case '{case_def.case_key}'")
            else:
                case.description = case_def.description
                case.turns = turns_data
                case.expectations = expectations_data
                print(f"  ~ updated case '{case_def.case_key}'")

        db.commit()
        print(
            f"Pushed suite '{suite_def.suite}' for agent '{suite_def.agent}' "
            f"({len(suite_def.cases)} cases)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m apps.api.scripts.push_suite <path-to-suite.yaml>")
        sys.exit(1)
    push_suite(Path(sys.argv[1]))