from __future__ import annotations

from pathlib import Path

import pytest

from spectre.models import Deployment
from spectre.state import (
    append_deployment,
    current_deployment,
    list_deployments,
    load_state,
    save_state,
)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    import spectre.state as mod
    original = mod._STATE_DIR
    mod._STATE_DIR = tmp_path / ".spectre"
    yield tmp_path / ".spectre"
    mod._STATE_DIR = original


def test_save_and_load_empty(tmp_path: Path) -> None:
    import spectre.state as mod
    original = mod._STATE_DIR
    mod._STATE_DIR = tmp_path / ".spectre"
    try:
        assert load_state() == []
    finally:
        mod._STATE_DIR = original


def test_append_and_list(tmp_path: Path) -> None:
    import spectre.state as mod
    original = mod._STATE_DIR
    mod._STATE_DIR = tmp_path / ".spectre"
    try:
        d1 = Deployment(
            service="api", environment="staging", version="v1",
            started_at="2024-01-01T00:00:00Z",
        )
        d2 = Deployment(
            service="api", environment="staging", version="v2",
            started_at="2024-01-02T00:00:00Z",
        )
        append_deployment(d1)
        append_deployment(d2)

        all_deps = list_deployments()
        assert len(all_deps) == 2
        assert all_deps[0].version == "v2"  # newest first

        filtered = list_deployments(service="api", environment="staging")
        assert len(filtered) == 2

        missing = list_deployments(service="nonexistent")
        assert missing == []

        current = current_deployment("api", "staging")
        assert current is not None
        assert current.version == "v2"
    finally:
        mod._STATE_DIR = original


def test_current_deployment_no_history(tmp_path: Path) -> None:
    import spectre.state as mod
    original = mod._STATE_DIR
    mod._STATE_DIR = tmp_path / ".spectre"
    try:
        assert current_deployment("api", "staging") is None
    finally:
        mod._STATE_DIR = original


def test_save_state_overwrites(tmp_path: Path) -> None:
    import spectre.state as mod
    original = mod._STATE_DIR
    mod._STATE_DIR = tmp_path / ".spectre"
    try:
        d = Deployment(service="api", environment="staging", version="v1")
        save_state([d])
        save_state([])
        assert load_state() == []
    finally:
        mod._STATE_DIR = original
