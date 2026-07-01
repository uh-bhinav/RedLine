"""
Registers an AgentVersion row for an agent that already exists (created via
push_suite.py). Phase 1's standalone stand-in for the future `agentbench
register-version` CLI command (Section 13) -- reads the entrypoint module's
source file, computes a content_hash from it, and is a no-op (prints "already
registered") if that exact hash is already registered for this agent, exactly
like the future CLI command is specified to behave.

Usage (from the repo root):
    python -m apps.api.scripts.register_agent_version \\
        --agent rag-agent \\
        --entrypoint agents.rag_agent.agent:run_turn \\
        --model gemini-2.5-flash \\
        --version-label v1
"""
import argparse
import hashlib
import importlib

from apps.api.core.db import SessionLocal
from apps.api.models import Agent, AgentVersion, Tenant


def _compute_content_hash(entrypoint: str) -> str:
    module_path, _ = entrypoint.rsplit(":", 1)
    module = importlib.import_module(module_path)
    source_bytes = open(module.__file__, "rb").read()
    return hashlib.sha256(source_bytes).hexdigest()


def register_agent_version(
    agent_name: str, entrypoint: str, model_name: str, version_label: str
) -> None:
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if tenant is None:
            raise RuntimeError("no tenant found -- run `python -m apps.api.scripts.seed` first")

        agent = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.name == agent_name).first()
        if agent is None:
            raise RuntimeError(
                f"agent '{agent_name}' not found -- run push_suite.py first to create it"
            )

        content_hash = _compute_content_hash(entrypoint)

        existing = (
            db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent.id, AgentVersion.content_hash == content_hash)
            .first()
        )
        if existing is not None:
            print(f"no-op, version already registered (id={existing.id}, hash={content_hash[:12]}...)")
            return

        version = AgentVersion(
            agent_id=agent.id,
            version_label=version_label,
            model_name=model_name,
            prompt_text="(see agents/rag_agent/agent.py for the live prompt template)",
            tool_schema=[{"name": "retrieve_documents", "description": "Searches the knowledge base"}],
            content_hash=content_hash,
            entrypoint=entrypoint,
        )
        db.add(version)
        db.commit()
        print(f"registered version '{version_label}' (id={version.id}, hash={content_hash[:12]}...)")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--version-label", required=True)
    args = parser.parse_args()
    register_agent_version(args.agent, args.entrypoint, args.model, args.version_label)