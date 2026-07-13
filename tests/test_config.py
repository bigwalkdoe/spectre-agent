from __future__ import annotations

from pathlib import Path

from spectre.config import (
    load_environments,
    load_services,
    resolve_environment,
    resolve_service,
)


def test_load_services_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "services.toml"
    cfg.write_text("""
[api]
build_type = "docker"
deploy_type = "docker-compose"
port = 8000
""")
    services = load_services(str(cfg))
    assert "api" in services
    assert services["api"].build_type == "docker"
    assert services["api"].port == 8000


def test_load_services_json(tmp_path: Path) -> None:
    cfg = tmp_path / "services.json"
    cfg.write_text('{"api": {"build_type": "docker", "port": 8000}}')
    services = load_services(str(cfg))
    assert "api" in services
    assert services["api"].port == 8000


def test_load_services_missing_file() -> None:
    assert load_services("/nonexistent/path.toml") == {}


def test_load_environments_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "envs.toml"
    cfg.write_text("""
[staging]
compose_file = "docker-compose.yml"

[production]
kube_namespace = "prod"
""")
    envs = load_environments(str(cfg))
    assert "staging" in envs
    assert "production" in envs
    assert envs["production"].kube_namespace == "prod"


def test_resolve_service_from_config(tmp_path: Path) -> None:
    cfg = tmp_path / "services.toml"
    cfg.write_text('[api]\nbuild_type = "pip"\n')
    svc = resolve_service("api", str(cfg))
    assert svc.name == "api"
    assert svc.build_type == "pip"
    assert svc.deploy_type == "docker-compose"  # default


def test_resolve_service_fallback_defaults(tmp_path: Path) -> None:
    cfg = tmp_path / "services.toml"
    cfg.write_text("")
    svc = resolve_service("unknown", str(cfg))
    assert svc.name == "unknown"
    assert svc.build_type == "docker"


def test_resolve_service_with_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / "services.toml"
    cfg.write_text('[api]\nbuild_type = "docker"\nport = 8000\n')
    svc = resolve_service("api", str(cfg), {"build_type": "pip"})
    assert svc.build_type == "pip"  # override wins
    assert svc.port == 8000  # from config


def test_resolve_environment_with_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / "envs.toml"
    cfg.write_text('[staging]\ncompose_file = "dc.yml"\n')
    env = resolve_environment("staging", str(cfg), {"kube_namespace": "test"})
    assert env.compose_file == "dc.yml"  # from config
    assert env.kube_namespace == "test"  # override


def test_resolve_environment_fallback(tmp_path: Path) -> None:
    cfg = tmp_path / "envs.toml"
    cfg.write_text("")
    env = resolve_environment("missing", str(cfg))
    assert env.name == "missing"
    assert env.compose_file == "docker-compose.yml"
