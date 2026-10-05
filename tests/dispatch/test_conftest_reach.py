"""The root conftest's fixtures must reach into the `tests.dispatch` package.

`tests/` and `tests/dispatch/` carry `__init__.py` so mypy gives their two
`conftest.py` files distinct module names. That is only safe if pytest still
applies `tests/conftest.py` to a test inside the nested package — the session
`_initialize_database` and the autouse `_no_real_subprocess`, which is what keeps
the suite from running real system commands. The imports in `tests/conftest.py`
also have to happen before anything reaches `packages.memory.db`, because the
database path is resolved at import time.

Both are asserted here, from inside the package that could have broken them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_root_conftest_fixtures_apply_inside_the_dispatch_package(request: pytest.FixtureRequest) -> None:
    applied = set(request.node.funcargs)
    assert "_initialize_database" in applied, f"tests/conftest.py fixtures not applied: {sorted(applied)}"
    assert "_no_real_subprocess" in applied, f"tests/conftest.py fixtures not applied: {sorted(applied)}"


def test_hermetic_state_environment_was_redirected() -> None:
    """Set at import time by `tests/conftest.py`, before `packages.memory.db` is
    imported. The real path here would be `~/.config/spectre`, and the suite
    writes to whatever it is pointed at."""
    assert Path(os.environ["SPECTRE_CONFIG_DIR"]).name.startswith("spectre-tests-")
