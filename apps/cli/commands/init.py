from pathlib import Path

import tomli_w
import typer
from rich.console import Console

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()
AGENTBENCH_YAML = "agentbench.yaml"


def init_cmd(
    agent_name: str = typer.Option(..., "--agent", prompt="Agent name"),
    entrypoint: str = typer.Option(..., "--entrypoint", prompt="Entrypoint (e.g. agents.rag_agent.agent:run_turn)"),
) -> None:
    """Register this agent via the API and write agentbench.yaml in the current directory."""
    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    client = RedLineClient(base_url, api_key)
    try:
        agent = client.post("/agents", {"name": agent_name})
    except APIError as e:
        console.print(f"[red]Failed to register agent:[/red] {e.detail}")
        raise typer.Exit(1)

    config = {
        "agent_name": agent_name,
        "agent_id": str(agent["id"]),
        "entrypoint": entrypoint,
        "api_base_url": base_url,
    }
    Path(AGENTBENCH_YAML).write_text(
        tomli_w.dumps(config),
        encoding="utf-8",
    )
    console.print(f"[green]Initialized.[/green] agent_id={agent['id']}")
    console.print(f"  wrote {AGENTBENCH_YAML}")