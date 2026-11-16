from __future__ import annotations

from pathlib import Path

import tomli
import typer
from rich.console import Console
from rich.table import Table

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()

_STYLE = {
    "silent_drift": ("red", "SILENT DRIFT"),
    "expected_change": ("yellow", "EXPECTED CHANGE"),
    "safe_refactor": ("green", "SAFE REFACTOR"),
    "no_op": ("green", "NO CHANGE"),
    "insufficient_data": ("dim", "INSUFFICIENT DATA"),
}


def _load_agentbench_yaml() -> dict:
    p = Path("agentbench.yaml")
    if not p.exists():
        return {}
    return tomli.loads(p.read_text())


def diff_cmd(
    version_a_id: str = typer.Argument(..., help="Older agent version's UUID"),
    version_b_id: str = typer.Argument(..., help="Newer agent version's UUID"),
    suite: str = typer.Option(
        None, "--suite",
        help="Suite UUID to diff against. Defaults to agentbench.yaml's suite_id.",
    ),
) -> None:
    """Compare two agent versions' observed behavior on a shared suite.

    Requires both versions to already have a completed `agentbench run` against the
    suite -- this reads existing eval results, it does not trigger new ones.
    """
    suite_id = suite or _load_agentbench_yaml().get("suite_id")
    if not suite_id:
        console.print(
            "[red]No suite specified.[/red] Pass --suite <uuid>, or run this from a "
            "directory with a suite_id already in agentbench.yaml."
        )
        raise typer.Exit(1)

    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    client = RedLineClient(base_url, api_key)
    try:
        result = client.post("/diff-runs", {
            "version_a_id": version_a_id,
            "version_b_id": version_b_id,
            "suite_id": suite_id,
        })
    except APIError as e:
        console.print(f"[red]Diff failed:[/red] {e.detail}")
        raise typer.Exit(1)

    color, label = _STYLE.get(result["classification"], ("white", result["classification"]))
    console.print(f"\n[{color}]{label}[/{color}]")
    console.print(f"  {result['detail']}")
    console.print(
        f"  code_changed={result['code_changed']}  "
        f"behavior_changed={result['behavior_changed']}  "
        f"mean_similarity={result['mean_similarity']:.3f} "
        f"(threshold={result['threshold']:.2f})"
    )

    per_case = result.get("per_case_similarity") or {}
    if per_case:
        table = Table(title="Per-case similarity")
        table.add_column("case_key")
        table.add_column("cosine similarity", justify="right")
        for case_key, similarity in sorted(per_case.items()):
            flag = "[red]![/red] " if similarity < result["threshold"] else ""
            table.add_row(case_key, f"{flag}{similarity:.3f}")
        console.print(table)

    if result["classification"] == "silent_drift":
        # Nonzero exit on the alarm case only -- lets a CI pipeline treat
        # `agentbench diff` like any other gate: green unless something real fired.
        raise typer.Exit(1)
