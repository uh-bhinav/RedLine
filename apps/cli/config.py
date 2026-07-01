"""
Reads and writes ~/.agentbench/config.toml.
All CLI commands call get_config() to resolve base_url and api_key -- never
reading env vars or hardcoded values directly, so `agentbench login` is
the single place that captures credentials.
"""
from __future__ import annotations

from pathlib import Path

import tomli
import tomli_w

CONFIG_DIR = Path.home() / ".agentbench"
CONFIG_FILE = CONFIG_DIR / "config.toml"


class ConfigError(Exception):
    pass


def save_config(base_url: str, api_key: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    CONFIG_FILE.write_text(
        tomli_w.dumps(
            {
                "api": {
                    "base_url": base_url,
                    "key": api_key,
                }
            }
        ),
        encoding="utf-8",
    )

    CONFIG_FILE.chmod(0o600)  # credentials file, owner-read-only


def get_config() -> tuple[str, str]:
    """Returns (base_url, api_key). Raises ConfigError if not configured."""
    if not CONFIG_FILE.exists():
        raise ConfigError(
            "not logged in -- run `agentbench login` first"
        )
    data = tomli.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    try:
        return data["api"]["base_url"], data["api"]["key"]
    except KeyError:
        raise ConfigError("config.toml is malformed -- run `agentbench login` to reset it")