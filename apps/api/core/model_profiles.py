"""
Model profile resolver (Phase 2 Section 10).

Benchmarks and agents declare a profile name (e.g. 'standard').
This module resolves that name to concrete provider + model config.
Nothing outside this module should reference a model name directly.

Usage:
    from apps.api.core.model_profiles import get_profile
    profile = get_profile("standard")
    client = genai.Client(api_key=...)
    response = client.models.generate_content(model=profile.chat_model, ...)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

import yaml

_PROFILES_PATH = Path(__file__).parents[3] / "config" / "model_profiles.yaml"


@dataclass
class ModelProfile:
    name: str
    provider: str
    chat_model: str
    embedding_model: str
    rpm: int            # requests-per-minute limit for the rate limiter
    max_tokens: int
    daily_limit: int | None = None  # requests-per-day ceiling (Phase 3 Section 3)


@lru_cache(maxsize=None)
def _load_profiles() -> dict:
    path = Path(os.environ.get("MODEL_PROFILES_PATH", str(_PROFILES_PATH)))
    with open(path) as f:
        return yaml.safe_load(f)


def get_profile(name: str | None = None) -> ModelProfile:
    """
    Returns the ModelProfile for the given name.
    Falls back to the default_profile if name is None.
    Raises KeyError if the profile doesn't exist.
    """
    data = _load_profiles()
    profile_name = name or data["default_profile"]
    if profile_name not in data["profiles"]:
        raise KeyError(
            f"Unknown model profile '{profile_name}'. "
            f"Available: {list(data['profiles'].keys())}"
        )
    raw = data["profiles"][profile_name]
    return ModelProfile(
        name=profile_name,
        provider=raw["provider"],
        chat_model=raw["chat_model"],
        embedding_model=raw["embedding_model"],
        rpm=raw["rpm"],
        max_tokens=raw["max_tokens"],
        # Optional so a profile file written before Phase 3 still loads. A profile
        # with no daily_limit is treated as having no daily ceiling.
        daily_limit=raw.get("daily_limit"),
    )


def list_profiles() -> list[str]:
    return list(_load_profiles()["profiles"].keys())