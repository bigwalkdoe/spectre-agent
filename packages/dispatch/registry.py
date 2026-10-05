"""Job registry — the declarative list of dispatchable maintenance actions.

The job list is checked-in data (`registry_data.json`), not a filesystem scan:
the metadata is the point, and a scan would make `sudo`/`mutates` implicit.
Each entry's `action` is a path relative to the actions root, which the
dispatcher's path resolver joins against.

An entry that omits a key takes the load-time default from `_load_defaults()`.
`replaces` makes this registry the migration ledger — it names the crontab
entries and systemd units the job supersedes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Sibling file, so the registry resolves from an installed wheel too.
_DATA_FILE = Path(__file__).with_name("registry_data.json")

# A job either allows a concurrent run or forbids one; nothing in between.
_CONCURRENCY = frozenset({"allow", "forbid"})

# The four keys a registry entry may not omit; everything else takes a default.
_REQUIRED_FIELDS = ("name", "action", "group", "summary")


@dataclass(frozen=True)
class Job:
    """A single dispatchable action.

    All fields are required so there is exactly one place defaults live: the
    loader. Load-time defaults are `sudo=False`, `timeout=1800`, `mutates=False`,
    `concurrency="allow"`, `schedule_hint=None`, `replaces=[]`.
    """

    name: str
    action: str
    group: str
    summary: str
    sudo: bool
    timeout: int
    mutates: bool
    concurrency: str
    schedule_hint: str | None
    replaces: list[str]


def _load_defaults() -> dict[str, Any]:
    """Defaults for JSON entries that omit a key. A fresh dict each call, so no
    entry ever shares the default `replaces` list."""
    return {
        "sudo": False,
        "timeout": 1800,
        "mutates": False,
        "concurrency": "allow",
        "schedule_hint": None,
        "replaces": [],
    }


def _job(entry: dict[str, Any]) -> Job:
    """Build and validate one decoded JSON entry.

    Any malformed entry raises ValueError naming the job: a registry whose whole
    purpose is explicit metadata must not fail with a bare TypeError, and a
    misspelled key must not pass silently just because keys are optional.
    """
    defaults = _load_defaults()
    known = {*_REQUIRED_FIELDS, *defaults}
    missing = sorted(set(_REQUIRED_FIELDS) - entry.keys())
    unknown = sorted(entry.keys() - known)
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown {', '.join(unknown)}")
        raise ValueError(f"job {entry.get('name', entry)!r} is {' and '.join(problems)}")

    job = Job(**{**defaults, **entry})
    if job.concurrency not in _CONCURRENCY:
        raise ValueError(f"{job.name}: concurrency {job.concurrency!r} is not one of {sorted(_CONCURRENCY)}")

    expected = job.action.removesuffix(".sh")
    if job.name != expected:
        raise ValueError(f"{job.name}: name disagrees with action {job.action!r}, expected {expected!r}")

    return job


def _load(path: Path) -> list[Job]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, list):
        raise ValueError(f"{path.name}: expected a JSON array of job objects, got {type(decoded).__name__}")
    return sorted((_job(entry) for entry in decoded), key=lambda job: job.name)


JOBS: list[Job] = _load(_DATA_FILE)
_JOBS_BY_NAME: dict[str, Job] = {job.name: job for job in JOBS}


def get_job(name: str) -> Job:
    """The registered job, or KeyError naming the unknown job."""
    return _JOBS_BY_NAME[name]


def jobs_in_group(group: str) -> list[Job]:
    """Every job in `group`, sorted by name.

    Sorted here rather than relying on JOBS's order: callers are allowed to
    replace the module-level JOBS list, and the return order is part of this
    function's contract.
    """
    return sorted((job for job in JOBS if job.group == group), key=lambda job: job.name)


def groups() -> list[str]:
    """Every group that has at least one job, sorted."""
    return sorted({job.group for job in JOBS})