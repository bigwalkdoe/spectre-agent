from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spectre.models import Deployment

_STATE_DIR = Path(".spectre")


def _state_file(service: str | None = None) -> Path:
    if service:
        return _STATE_DIR / "state" / f"{service}.json"
    return _STATE_DIR / "deployments.json"


def load_state() -> list[Deployment]:
    path = _state_file()
    if not path.is_file():
        return []
    try:
        data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return [Deployment.from_dict(d) for d in data]
    except (json.JSONDecodeError, OSError):
        return []


def save_state(deployments: list[Deployment]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [d.to_dict() for d in deployments]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def append_deployment(deployment: Deployment) -> None:
    state = load_state()
    state.append(deployment)
    save_state(state)


def current_deployment(service: str, environment: str) -> Deployment | None:
    state = load_state()
    filtered = [d for d in state if d.service == service and d.environment == environment]
    if not filtered:
        return None
    filtered.sort(key=lambda d: d.started_at, reverse=True)
    return filtered[0]


def list_deployments(
    service: str | None = None, environment: str | None = None
) -> list[Deployment]:
    state = load_state()
    result = state
    if service:
        result = [d for d in result if d.service == service]
    if environment:
        result = [d for d in result if d.environment == environment]
    result.sort(key=lambda d: d.started_at, reverse=True)
    return result
