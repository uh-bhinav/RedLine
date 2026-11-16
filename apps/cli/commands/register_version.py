import hashlib
import importlib
import sys
from pathlib import Path

import tomli
import typer
from rich.console import Console

from apps.cli.api_client import APIError, RedLineClient
from apps.cli.config import ConfigError, get_config

console = Console()


def _load_agentbench_yaml() -> dict:
    p = Path("agentbench.yaml")
    if not p.exists():
        raise FileNotFoundError("agentbench.yaml not found -- run `agentbench init` first")
    return tomli.loads(p.read_text())


HTTP_SCHEMES = ("http://", "https://")


def is_http_entrypoint(entrypoint: str) -> bool:
    return entrypoint.strip().startswith(HTTP_SCHEMES)


def _compute_content_hash(entrypoint: str) -> str:
    """Hashes the agent's source so a behavioural change can be attributed to a code
    change (or, more interestingly, to the absence of one -- see Phase 4.2).

    For an HTTP agent we cannot see the source. Hashing the URL is the honest
    fallback: it makes "the code changed" permanently false for that agent, which is
    correct, because we genuinely do not know. Pass --content-hash (e.g. your git SHA)
    to give the diff engine a real code axis.
    """
    if is_http_entrypoint(entrypoint):
        return hashlib.sha256(entrypoint.strip().encode()).hexdigest()

    module_path, _ = entrypoint.rsplit(":", 1)
    if "." not in sys.path[0]:
        sys.path.insert(0, ".")
    module = importlib.import_module(module_path)
    return hashlib.sha256(open(module.__file__, "rb").read()).hexdigest()


def register_version_cmd(
    version_label: str = typer.Option(..., "--version-label", prompt="Version label (e.g. v1)"),
    model_name: str = typer.Option(..., "--model", prompt="Model name (e.g. gemini-2.5-flash)"),
    git_commit_sha: str = typer.Option(None, "--git-commit-sha"),
    content_hash_override: str = typer.Option(
        None,
        "--content-hash",
        help="Explicit content hash. Recommended for HTTP agents, whose source RedLine "
             "cannot read -- pass your git commit SHA so version diffing has a code axis.",
    ),
) -> None:
    """Compute content_hash from agent source and register the version via the API."""
    try:
        cfg = _load_agentbench_yaml()
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    try:
        base_url, api_key = get_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    entrypoint = cfg["entrypoint"]
    if content_hash_override:
        content_hash = content_hash_override
    else:
        try:
            content_hash = _compute_content_hash(entrypoint)
        except Exception as e:
            console.print(f"[red]Failed to compute content_hash:[/red] {e}")
            raise typer.Exit(1)

        if is_http_entrypoint(entrypoint):
            console.print(
                "[yellow]Note:[/yellow] this is an HTTP agent, so the content hash is "
                "derived from its URL, not its source. Version diffing cannot detect "
                "code changes for it. Pass --content-hash <git-sha> to fix that."
            )

    client = RedLineClient(base_url, api_key)
    try:
        version = client.post(
            f"/agents/{cfg['agent_id']}/versions",
            {
                "version_label": version_label,
                "model_name": model_name,
                "prompt_text": "(see agent source for live prompt)",
                "tool_schema": [],
                "content_hash": content_hash,
                "entrypoint": cfg["entrypoint"],
                "git_commit_sha": git_commit_sha,
            },
        )
    except APIError as e:
        console.print(f"[red]Failed to register version:[/red] {e.detail}")
        raise typer.Exit(1)

    console.print(f"[green]Version registered.[/green]")
    console.print(f"  version_id  = {version['id']}")
    console.print(f"  content_hash = {content_hash[:12]}...")

    # write version_id back to agentbench.yaml so `run` and `ci-check` can read it
    cfg["version_id"] = version["id"]
    from pathlib import Path
    import tomli_w
    Path("agentbench.yaml").write_text(
        tomli_w.dumps(cfg),
        encoding="utf-8",
    )