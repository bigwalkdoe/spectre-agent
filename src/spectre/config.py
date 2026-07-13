from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from spectre.models import Environment, Service


def _load_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return _load_toml(path)
    if suffix in (".json",):
        return _load_json(path)
    raise ValueError(f"unsupported config format: {suffix} (use .toml or .json)")


def load_services(path: str = "config/services.toml") -> dict[str, Service]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = _load_file(p)
    return {name: Service.from_dict({"name": name, **cfg}) for name, cfg in raw.items()}


def load_environments(path: str = "config/environments.toml") -> dict[str, Environment]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = _load_file(p)
    return {name: Environment.from_dict({"name": name, **cfg}) for name, cfg in raw.items()}


def resolve_service(
    name: str,
    services_path: str = "config/services.toml",
    overrides: dict[str, str] | None = None,
) -> Service:
    services = load_services(services_path)
    svc = services.get(name, Service(name=name))
    if overrides:
        for key, val in overrides.items():
            if hasattr(svc, key) and val is not None:
                setattr(svc, key, val)
    return svc


def resolve_environment(
    name: str,
    envs_path: str = "config/environments.toml",
    overrides: dict[str, str] | None = None,
) -> Environment:
    envs = load_environments(envs_path)
    env = envs.get(name, Environment(name=name))
    if overrides:
        for key, val in overrides.items():
            if hasattr(env, key) and val is not None:
                setattr(env, key, val)
    return env
