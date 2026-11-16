from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()


def _client() -> RedLineClient:
    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    return RedLineClient(base_url, api_key)


def mine_cmd(agent_id: str = typer.Argument(..., help="Agent UUID to mine failure patterns for")) -> None:
    """Cluster this agent's eval history and surface recurring failure patterns
    as candidate regression tests, pending your review."""
    client = _client()
    try:
        clusters = client.post(f"/mining/{agent_id}/run", {})
    except APIError as e:
        console.print(f"[red]Mining failed:[/red] {e.detail}")
        raise typer.Exit(1)

    if not clusters:
        console.print("[green]No significant failure clusters found.[/green]")
        return

    table = Table(title=f"{len(clusters)} failure cluster(s) found")
    table.add_column("size", justify="right")
    table.add_column("bad outcome rate", justify="right")
    table.add_column("representative response")
    for c in clusters:
        table.add_row(
            str(c["size"]), f"{c['bad_outcome_rate']:.0%}",
            c["representative_text"][:80] + ("..." if len(c["representative_text"]) > 80 else ""),
        )
    console.print(table)
    console.print(
        "\nRun [cyan]agentbench candidates list --agent-id "
        f"{agent_id}[/cyan] to review the generated candidate cases."
    )


def candidates_list_cmd(
    agent_id: str = typer.Option(..., "--agent-id"),
    status: str = typer.Option("pending", "--status"),
) -> None:
    """List mined candidate regression cases for an agent."""
    client = _client()
    try:
        candidates = client.get(f"/mining/candidates?agent_id={agent_id}&status={status}")
    except APIError as e:
        console.print(f"[red]Failed to list candidates:[/red] {e.detail}")
        raise typer.Exit(1)

    if not candidates:
        console.print(f"No candidates with status='{status}'.")
        return

    table = Table(title=f"{len(candidates)} candidate case(s), status={status}")
    table.add_column("id")
    table.add_column("case_key")
    table.add_column("status")
    for c in candidates:
        table.add_row(c["id"], c["case_key"], c["status"])
    console.print(table)


def candidates_approve_cmd(candidate_id: str = typer.Argument(...)) -> None:
    """Promote a mined candidate into a real EvalCase in the agent's
    'mined-failures' suite."""
    client = _client()
    try:
        result = client.post(f"/mining/candidates/{candidate_id}/approve", {})
    except APIError as e:
        console.print(f"[red]Approve failed:[/red] {e.detail}")
        raise typer.Exit(1)
    console.print(f"[green]Approved.[/green] promoted_case_id={result['promoted_case_id']}")


def candidates_reject_cmd(candidate_id: str = typer.Argument(...)) -> None:
    """Reject a mined candidate -- it will not become a real eval case."""
    client = _client()
    try:
        client.post(f"/mining/candidates/{candidate_id}/reject", {})
    except APIError as e:
        console.print(f"[red]Reject failed:[/red] {e.detail}")
        raise typer.Exit(1)
    console.print("[yellow]Rejected.[/yellow]")
