"""Tests for configuration loading and settings."""

from __future__ import annotations

from pathlib import Path

from packages.config.settings import (
    SpectreSettings,
    OllamaConfig,
    MonitoringConfig,
    AgentConfig,
    WorkflowSchedule,
    load_settings,
    save_settings,
)


def test_default_settings() -> None:
    s = SpectreSettings()
    assert s.profile == "laptop"
    assert s.log_level == "INFO"
    assert s.plugins_dir is None
    assert s.data_dir is None


def test_ollama_config_defaults() -> None:
    o = OllamaConfig()
    assert o.url == "http://localhost:11434"
    assert o.benchmark_model == "llama3.2:3b"


def test_monitoring_config_defaults() -> None:
    m = MonitoringConfig()
    assert m.interval_seconds == 30
    assert m.enabled is True


def test_agent_config_defaults() -> None:
    a = AgentConfig()
    assert a.enabled is True
    assert a.interval_seconds == 300


def test_settings_with_agents() -> None:
    s = SpectreSettings(
        agents={"linux": AgentConfig(enabled=True), "security": AgentConfig(enabled=False)}
    )
    assert s.agents["linux"].enabled is True
    assert s.agents["security"].enabled is False


def test_settings_roundtrip(tmp_path: Path) -> None:
    settings = SpectreSettings(profile="server", log_level="DEBUG")
    path = tmp_path / "settings.yaml"
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.profile == "server"
    assert loaded.log_level == "DEBUG"


def test_load_settings_missing_file() -> None:
    s = load_settings(Path("/nonexistent/settings.yaml"))
    assert s.profile == "laptop"


def test_settings_with_schedules() -> None:
    s = SpectreSettings(
        schedules=[WorkflowSchedule(name="morning", schedule="every 24h")]
    )
    assert len(s.schedules) == 1
    assert s.schedules[0].name == "morning"
