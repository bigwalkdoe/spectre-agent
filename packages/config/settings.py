from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "spectre" / "settings.yaml"
WORKSPACE_CONFIG_PATH = Path("config/settings.yaml")


class OllamaConfig(BaseModel):
    url: str = "http://localhost:11434"
    benchmark_model: str = "llama3.2:3b"


class MonitoringConfig(BaseModel):
    interval_seconds: int = 30
    enabled: bool = True


class WorkflowSchedule(BaseModel):
    name: str
    schedule: str  # cron or interval expression
    enabled: bool = True


class AgentConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 300


class SpectreSettings(BaseModel):
    profile: str = "laptop"  # "development", "production", "laptop", "server"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    schedules: list[WorkflowSchedule] = Field(default_factory=list)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    plugins_dir: str | None = None
    log_level: str = "INFO"
    data_dir: str | None = None


def load_settings(config_path: Path | None = None) -> SpectreSettings:
    """Loads configuration settings from YAML, falling back to defaults."""
    paths_to_try = []
    if config_path:
        paths_to_try.append(config_path)
    paths_to_try.extend([WORKSPACE_CONFIG_PATH, DEFAULT_CONFIG_PATH])

    raw_data: dict[str, Any] = {}
    for p in paths_to_try:
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as f:
                    raw_data = yaml.safe_load(f) or {}
                break
            except Exception:
                pass

    return SpectreSettings(**raw_data)


def save_settings(settings: SpectreSettings, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Saves settings configuration out to file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings.model_dump(), f)
