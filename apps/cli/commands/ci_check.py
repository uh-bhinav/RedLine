"""
`agentbench ci-check` -- runs only inside GitHub Actions.

This command owns the entire GitHub Check Run lifecycle (create → update) using
the ambient GITHUB_TOKEN from the Actions environment. The API server never sees
or calls GitHub. See the corrected Section 12 design note in routers/ci.py.
"""
import os
import sys
import time
from pathlib import Path

import tomli
import typer
from rich.console import Console

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.commands.github_api import create_check_run, update_check_run
from apps.cli.config import ConfigError, get_config

console = Console()
POLL_INTERVAL = 5


def ci_check_cmd(
    agent: str = typer.Option(..., "--agent"),
    suite: str = typer.Option(..., "--suite"),
) -> None:
    """Used inside GitHub Actions only. Creates a Check Run, triggers eval, polls,
    updates the Check Run, exits 0 (pass) or 1 (fail)."""
    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_repo = os.environ.get("GITHUB_REPOSITORY", "")
    commit_sha = os.environ.get("GITHUB_SHA", "")
    pr_number_str = os.environ.get("PR_NUMBER", "")

    if not all([github_token, github_repo, commit_sha]):
        console.print("[red]GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_SHA must all be set.[/red]")
        console.print("This command is only meant to run inside a GitHub Actions job.")
        raise typer.Exit(1)

    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Step 1: create the Check Run -- only possible here, with the Actions-ambient token
    try:
        check_run_id = create_check_run(github_repo, commit_sha, github_token)
        console.print(f"Check Run created: id={check_run_id}")
    except Exception as e:
        console.print(f"[red]Failed to create GitHub Check Run:[/red] {e}")
        raise typer.Exit(1)

    # Step 2: look up agent_id and suite_id by name
    client = RedLineClient(base_url, api_key)
    try:
        agent_row = client.post("/agents", {"name": agent})
        agent_id = agent_row["id"]
    except APIError as e:
        _fail_check(github_repo, check_run_id, github_token, [f"agent lookup failed: {e.detail}"])
        raise typer.Exit(1)

    agentbench_yaml = Path("agentbench.yaml")
    if not agentbench_yaml.exists():
        _fail_check(github_repo, check_run_id, github_token, ["agentbench.yaml not found"])
        raise typer.Exit(1)

    cfg = tomli.loads(agentbench_yaml.read_text())
    version_id = cfg.get("version_id")
    suite_id = cfg.get("suite_id")

    if not version_id or not suite_id:
        _fail_check(github_repo, check_run_id, github_token,
                    ["version_id or suite_id missing from agentbench.yaml"])
        raise typer.Exit(1)

    pr_number = int(pr_number_str) if pr_number_str.isdigit() else None

    # Step 3: kick off the eval run
    try:
        run = client.post("/ci/check", {
            "agent_version_id": version_id,
            "suite_id": suite_id,
            "pr_number": pr_number,
        })
        run_id = run["eval_run_id"]
        console.print(f"Eval run created: {run_id}  poll: {run['poll_url']}")
    except APIError as e:
        _fail_check(github_repo, check_run_id, github_token, [f"eval trigger failed: {e.detail}"])
        raise typer.Exit(1)

    # Step 4: poll until done
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            result = client.get(f"/eval-runs/{run_id}")
        except APIError as e:
            _fail_check(github_repo, check_run_id, github_token, [f"poll error: {e.detail}"])
            raise typer.Exit(1)
        if result["status"] in ("completed", "failed"):
            break
        console.print(f"  status: {result['status']}...")

    if result["status"] == "failed":
        _fail_check(github_repo, check_run_id, github_token, ["eval worker error -- check worker logs"])
        raise typer.Exit(1)

    gate = result.get("gate_result", {})
    passed = gate.get("passed", False)
    reasons = gate.get("reasons", [])

    # Step 5: update the Check Run with the real verdict
    try:
        update_check_run(github_repo, check_run_id, passed, reasons, github_token)
    except Exception as e:
        console.print(f"[yellow]Warning: failed to update Check Run:[/yellow] {e}")
        # don't let a GitHub API hiccup shadow the actual eval result

    if passed:
        console.print("[green]GATE PASSED[/green]")
        raise typer.Exit(0)
    else:
        console.print("[red]GATE FAILED[/red]")
        for r in reasons:
            console.print(f"  ✗ {r}")
        raise typer.Exit(1)


def _fail_check(repo: str, check_run_id: int, token: str, reasons: list[str]) -> None:
    """Best-effort: mark the Check Run failed before exiting on an internal error."""
    try:
        update_check_run(repo, check_run_id, passed=False, reasons=reasons, token=token)
    except Exception:
        pass