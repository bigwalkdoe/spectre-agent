"""The shipped systemd units must run through the interpreter install.sh creates.

`scripts/install.sh` installs the package into `%h/.config/spectre/venv` and
never touches the system python, so `ExecStart=/usr/bin/python3 ...` cannot
import `apps` on a clean host — the workflow engine, sqlmodel, typer and every
other dependency live only in the venv. Units like that degrade silently on a
machine where an older system-wide install left the imports resolvable and fail
loudly on one where it does not; this host produced the second half
(`ModuleNotFoundError: No module named 'apps'`) and a hand-patched copy of
`~/.config/systemd/user/spectre.service` masked the cause.

The pins here are structural, not "start the unit and assert it runs": starting
needs a user session, which the suite is hermetic about. What the suite can pin
is the exact reference the installer guarantees to exist before the unit is
copied, plus the two contracts these units already document — the API's bind
address expands from the (mandatory) environment file rather than is baked in,
and that file is required rather than tolerated-missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
VENV_PYTHON = "%h/.config/spectre/venv/bin/python"

UNIT_NAMES = ("spectre.service", "spectre-api.service")


def _unit_text(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _exec_start(name: str) -> str:
    """The one ExecStart line, prefix stripped. Drop-in overrides are out of
    scope for the same reason verify.py gives at
    packages/dispatch/verify.py:265 — real hosts may have them, shipped files
    once."""
    starts = [
        line[len("ExecStart=") :].strip()
        for line in _unit_text(name).splitlines()
        if line.startswith("ExecStart=")
    ]
    assert len(starts) == 1, f"{name} has {len(starts)} ExecStart lines"
    return starts[0]


@pytest.mark.parametrize("name", UNIT_NAMES)
def test_exec_start_runs_through_the_installed_venv(name: str) -> None:
    """The interpreter in ExecStart is the one the installer guarantees."""
    start = _exec_start(name)
    interpreter = start.split(maxsplit=1)[0]
    assert interpreter == VENV_PYTHON, (
        f"{name}: ExecStart runs {interpreter!r}; a shipped unit may only run "
        f"the interpreter install.sh creates ({VENV_PYTHON!r})"
    )


def test_api_bind_address_expands_from_the_environment() -> None:
    """SPECTRE_API_HOST/PORT reach uvicorn through ${VAR} expansion, not baked
    numbers — scripts/spectre-api.service deliberately ships no default so a
    port collision fails at start."""
    start = _exec_start("spectre-api.service")
    assert "--host ${SPECTRE_API_HOST}" in start
    assert "--port ${SPECTRE_API_PORT}" in start


def test_api_environment_file_is_required() -> None:
    """`EnvironmentFile=` without the `-` prefix fails the unit when the file
    is absent, which is the point: an unset key makes the API refuse to serve
    (AGENTS.md), so starting without the file must fail, not half-work."""
    assert (
        "EnvironmentFile=%h/.config/spectre/spectre.env"
        in _unit_text("spectre-api.service")
    )
