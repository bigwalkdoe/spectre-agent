"""Shared pytest fixtures for the Spectre test suite."""

from __future__ import annotations

import pytest

from packages.memory.db import init_db


@pytest.fixture(autouse=True, scope="session")
def _initialize_database() -> None:
    """Ensure all database tables exist before tests run."""
    init_db()
