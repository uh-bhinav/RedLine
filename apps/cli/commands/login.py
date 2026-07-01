import typer
from rich.console import Console

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import save_config

console = Console()


def login_cmd(
    base_url: str = typer.Option("http://localhost:8000", prompt="API base URL"),
    api_key: str = typer.Option(..., prompt="API key", hide_input=True),
) -> None:
    """Store API base URL and key in ~/.agentbench/config.toml."""
    try:
        client = RedLineClient(base_url, api_key)
        client.get("/health")
    except APIError as e:
        console.print(f"[red]Login failed:[/red] {e.detail}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Cannot reach {base_url}:[/red] {e}")
        raise typer.Exit(1)

    save_config(base_url, api_key)
    console.print(f"[green]Logged in.[/green] Config saved to ~/.agentbench/config.toml")