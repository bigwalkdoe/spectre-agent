"""Spectre Core — 4-level configuration hierarchy.

Priority: Runtime > Project > User > Global
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SpectreConfig(BaseModel):
    """Unified configuration model with 4-level hierarchy."""

    profile: str = "laptop"
    log_level: str = "INFO"
    data_dir: str | None = None
    plugins_dir: str | None = None

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    monitoring_interval: int = 30
    monitoring_enabled: bool = True

    schedules: list[dict[str, Any]] = Field(default_factory=list)
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)


# Configuration file locations (in priority order)
_RUNTIME_CONFIG = Path(os.environ.get("SPECTRE_CONFIG", ""))
_PROJECT_CONFIG = Path("config/settings.yaml")
_USER_CONFIG = Path.home() / ".config" / "spectre" / "settings.yaml"
_GLOBAL_CONFIG = Path("/etc/spectre/settings.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning empty dict on failure."""
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_config(config_path: Path | None = None) -> SpectreConfig:
    """Load configuration with 4-level hierarchy.

    Priority: Runtime > Project > User > Global
    Each level overrides the previous.
    """
    # Load in order (lowest priority first)
    merged: dict[str, Any] = {}

    for path in [_GLOBAL_CONFIG, _USER_CONFIG, _PROJECT_CONFIG, _RUNTIME_CONFIG]:
        data = _load_yaml(path)
        if data:
            merged.update(data)

    # Explicit config path overrides everything
    if config_path:
        data = _load_yaml(config_path)
        if data:
            merged.update(data)

    # Environment variable overrides
    env_overrides = {
        "SPECTRE_PROFILE": "profile",
        "SPECTRE_LOG_LEVEL": "log_level",
        "SPECTRE_OLLAMA_URL": "ollama_url",
        "SPECTRE_MONITORING_INTERVAL": "monitoring_interval",
    }
    for env_key, config_key in env_overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            merged[config_key] = val

    return SpectreConfig(**merged)


def save_config(config: SpectreConfig, path: Path | None = None) -> None:
    """Save configuration to a file."""
    target = path or _USER_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.model_dump(), f, default_flow_style=False)
