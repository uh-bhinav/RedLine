from pathlib import Path

import tomli
import tomli_w
import typer
import yaml
from rich.console import Console

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()


def push_suite_cmd(
    suite_file: Path = typer.Argument(..., help="Path to suite YAML file (e.g. eval-suites/rag-agent/baseline.yaml)"),
) -> None:
    """Push an eval suite YAML file to the API and record the suite_id in agentbench.yaml."""
    if not suite_file.exists():
        console.print(f"[red]File not found:[/red] {suite_file}")
        raise typer.Exit(1)

    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    raw = yaml.safe_load(suite_file.read_text())
    client = RedLineClient(base_url, api_key)
    try:
        result = client.post("/eval-suites", raw)
    except APIError as e:
        console.print(f"[red]Failed to push suite:[/red] {e.detail}")
        raise typer.Exit(1)

    console.print(f"[green]Suite pushed.[/green]")
    console.print(f"  suite_id     = {result['suite_id']}")
    console.print(f"  created_suite = {result['created_suite']}")
    console.print(f"  cases_added  = {result['cases_added']}")
    console.print(f"  cases_updated = {result['cases_updated']}")

    # write suite_id back to agentbench.yaml so `run` and `ci-check` can read it
    yaml_path = Path("agentbench.yaml")
    if yaml_path.exists():
        cfg = tomli.loads(yaml_path.read_text())
        cfg["suite_id"] = result["suite_id"]
        yaml_path.write_text(
            tomli_w.dumps(cfg),
            encoding="utf-8",
        )
        console.print(f"  suite_id written to agentbench.yaml")