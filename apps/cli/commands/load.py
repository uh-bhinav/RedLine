from __future__ import annotations

import time

import typer
from rich.console import Console

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()
POLL_INTERVAL = 3


def load_cmd(
    version_id: str = typer.Argument(..., help="Agent version UUID to load-test"),
    message: str = typer.Option(
        "Hello, I have a question about my order.", "--message",
        help="Fixed message every simulated user sends repeatedly",
    ),
    users: int = typer.Option(10, "--users", help="Concurrent simulated users"),
    duration: int = typer.Option(30, "--duration", help="How long to run, in seconds"),
) -> None:
    """Load-test an agent version: N concurrent users for a fixed duration,
    reporting p50/p95/p99 latency, error rate, and cost per hour at that
    concurrency -- the number no eval run alone ever surfaces."""
    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    client = RedLineClient(base_url, api_key)
    try:
        run = client.post("/load-runs", {
            "agent_version_id": version_id,
            "message": message,
            "concurrency": users,
            "duration_seconds": duration,
        })
    except APIError as e:
        console.print(f"[red]Failed to create load run:[/red] {e.detail}")
        raise typer.Exit(1)

    run_id = run["id"]
    console.print(f"Load run created: [cyan]{run_id}[/cyan]  ({users} users, {duration}s)")

    with console.status("Running load test..."):
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                run = client.get(f"/load-runs/{run_id}")
            except APIError as e:
                console.print(f"[red]Poll error:[/red] {e.detail}")
                raise typer.Exit(1)
            if run["status"] in ("completed", "failed"):
                break

    if run["status"] == "failed":
        console.print(f"[red]Load run failed:[/red] {run.get('error', 'unknown error')}")
        raise typer.Exit(1)

    console.print(f"\n[green]Load test complete[/green]  run={run_id}")
    console.print(f"  requests        : {run['total_requests']} "
                  f"({run['successful_requests']} succeeded, "
                  f"{run['error_rate']:.1%} error rate)")
    console.print(f"  latency (p50/p95/p99): "
                  f"{run['p50_latency_ms']:.0f}ms / "
                  f"{run['p95_latency_ms']:.0f}ms / "
                  f"{run['p99_latency_ms']:.0f}ms")
    console.print(f"  throughput      : {run['throughput_rps']:.2f} req/s")
    console.print(f"  cost            : ${run['total_cost_usd']:.6f} total, "
                  f"${run['cost_per_hour_usd']:.4f}/hour at this concurrency")
