"""Shared helpers for the dispatch tests.

`make_job` builds a `Job` with test-friendly defaults so the dispatch tests can
state only the field they are exercising. Jobs built here never touch the real
registry, the host schedulers or the filesystem.
"""

from __future__ import annotations

from typing import Any

from packages.dispatch.registry import Job


def make_job(action: str = "ok.sh", **overrides: Any) -> Job:
    """A `Job` for `action` (name = action minus `.sh`), with `overrides` applied."""
    fields: dict[str, Any] = {
        "name": action.removesuffix(".sh"),
        "action": action,
        "group": "t",
        "summary": "",
        "sudo": False,
        "timeout": 10,
        "mutates": False,
        "concurrency": "allow",
        "schedule_hint": None,
        "replaces": [],
    }
    fields.update(overrides)
    return Job(**fields)
