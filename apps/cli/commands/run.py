import time
from pathlib import Path

import tomli
import typer
from rich.console import Console
from rich.table import Table

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()
POLL_INTERVAL = 3


def _load_agentbench_yaml() -> dict:
    p = Path("agentbench.yaml")
    if not p.exists():
        raise FileNotFoundError("agentbench.yaml not found -- run `agentbench init` first")
    return tomli.loads(p.read_text())


def run_cmd(
    suite: str = typer.Option("baseline", "--suite"),
) -> None:
    """Trigger a manual eval run and poll until complete, then print results."""
    try:
        cfg = _load_agentbench_yaml()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if "version_id" not in cfg:
        console.print("[red]No version_id in agentbench.yaml -- run `agentbench register-version` first[/red]")
        raise typer.Exit(1)

    if "suite_id" not in cfg:
        console.print("[red]No suite_id in agentbench.yaml -- run `agentbench push-suite` first[/red]")
        raise typer.Exit(1)

    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    client = RedLineClient(base_url, api_key)
    try:
        run = client.post("/eval-runs", {
            "agent_version_id": cfg["version_id"],
            "suite_id": cfg["suite_id"],
            "triggered_by": "manual",
        })
    except APIError as e:
        console.print(f"[red]Failed to create eval run:[/red] {e.detail}")
        raise typer.Exit(1)

    run_id = run["id"]
    console.print(f"Eval run created: [cyan]{run_id}[/cyan]")

    with console.status("Running..."):
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                run = client.get(f"/eval-runs/{run_id}")
            except APIError as e:
                console.print(f"[red]Poll error:[/red] {e.detail}")
                raise typer.Exit(1)
            if run["status"] in ("completed", "failed"):
                break

    if run["status"] == "failed":
        console.print("[red]Eval run failed (worker error -- check worker logs)[/red]")
        raise typer.Exit(1)

    gate = run.get("gate_result", {})
    gate_passed = gate.get("passed", False)
    reasons = gate.get("reasons", [])

    _print_summary(run_id, gate_passed, reasons)


def _print_summary(run_id: str, gate_passed: bool, reasons: list[str]) -> None:
    if gate_passed:
        console.print(f"\n[green]GATE PASSED[/green]  run={run_id}")
    else:
        console.print(f"\n[red]GATE FAILED[/red]  run={run_id}")
        for r in reasons:
            console.print(f"  [red]✗[/red] {r}")