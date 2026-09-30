"""Shared pytest fixtures for the Spectre test suite.

The suite must be hermetic. Spectre shells out to package managers, container
engines and service managers, so an unguarded test run will happily prune
flatpaks, vacuum journals and `podman system prune` on whatever machine is
running it, then persist the results into the real ~/.config/spectre/memory.db.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Point Spectre state at a throwaway tree. This has to happen before anything
# imports packages.memory.db, because the database path is resolved at import
# time.
_TMP_CONFIG = Path(tempfile.mkdtemp(prefix="spectre-tests-"))
os.environ["SPECTRE_CONFIG_DIR"] = str(_TMP_CONFIG)
os.environ["SPECTRE_SCAN_ROOT"] = str(_TMP_CONFIG)

from packages.memory.db import init_db  # noqa: E402

# Modules that shell out to dnf, flatpak, journalctl, podman, docker, kubectl,
# git and friends.
_SUBPROCESS_CONSUMERS = (
    "packages.linux_agent.agent",
    "packages.devops_agent.agent",
    "packages.security_agent.agent",
    "packages.developer_agent.agent",
    "packages.publishing_agent.agent",
)


class _StubSubprocess:
    """Proxy the real subprocess module, but make `run` a harmless no-op.

    Everything else (TimeoutExpired, CompletedProcess, DEVNULL, ...) is passed
    through, so the agents' real error-handling paths still execute.
    """

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture(autouse=True, scope="session")
def _initialize_database() -> None:
    """Ensure all database tables exist before tests run."""
    init_db()


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop any test from executing real system commands."""
    stub = _StubSubprocess(subprocess)
    for name in _SUBPROCESS_CONSUMERS:
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "subprocess", stub, raising=False)
