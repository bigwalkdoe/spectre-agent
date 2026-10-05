"""Job registry — the declarative list of dispatchable maintenance actions.

The job list is checked-in data (`registry_data.json`), not a filesystem scan:
the metadata is the point, and a scan would make `sudo`/`mutates` implicit.
Each entry's `action` is a path relative to the actions root, which the
dispatcher's path resolver joins against.

An entry that omits a key takes its value from `FIELD_DEFAULTS`. Those two
constants, `REQUIRED_FIELDS` and `FIELD_DEFAULTS`, are the whole entry schema and
are public because `tools/gen_registry.py` generates data against them — a
mirrored copy is a copy that drifts.
`replaces` makes this registry the migration ledger — it names the crontab
entries and systemd units the job supersedes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

# Sibling file, so the registry resolves from an installed wheel too.
_DATA_FILE = Path(__file__).with_name("registry_data.json")

# A job either allows a concurrent run or forbids one; nothing in between.
_CONCURRENCY = frozenset({"allow", "forbid"})

# The keys a registry entry may not omit.
REQUIRED_FIELDS: tuple[str, ...] = ("name", "action", "group", "summary")

# What an entry takes for each key it omits.
FIELD_DEFAULTS: dict[str, Any] = {
    "sudo": False,
    "timeout": 1800,
    "mutates": False,
    "concurrency": "allow",
    "schedule_hint": None,
    "replaces": [],
}

# The type each key's value must have. Types are checked, not coerced: a quoted
# `"sudo": "false"` is a truthy string, so accepting it would silently escalate a
# read-only job to one that runs as root.
_FIELD_TYPES: dict[str, tuple[type, ...]] = {
    "name": (str,),
    "action": (str,),
    "group": (str,),
    "summary": (str,),
    "sudo": (bool,),
    "timeout": (int,),
    "mutates": (bool,),
    "concurrency": (str,),
    "schedule_hint": (str, type(None)),
    "replaces": (list,),
}


@dataclass(frozen=True)
class Job:
    """A single dispatchable action.

    All fields are required so there is exactly one place defaults live:
    `FIELD_DEFAULTS`.
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


# A field with no entry in _FIELD_TYPES is a field whose values are never
# validated, which is the failure that table exists to prevent — so a mismatch
# fails at import rather than silently.
if set(_FIELD_TYPES) != {f.name for f in fields(Job)}:
    raise RuntimeError(f"_FIELD_TYPES does not describe Job: {sorted(_FIELD_TYPES)}")


def _load_defaults() -> dict[str, Any]:
    """A fresh copy of FIELD_DEFAULTS. The copy is not shallow-only: `replaces`
    is a list, and a shared default would let one job's append leak into every
    later entry that omitted the key."""
    defaults = dict(FIELD_DEFAULTS)
    defaults["replaces"] = [*FIELD_DEFAULTS["replaces"]]
    return defaults


def _label(entry: dict[str, Any]) -> Any:
    """How an error names an entry: by its name when it has a usable one."""
    return entry.get("name", entry)


def _wrong_types(values: dict[str, Any]) -> list[str]:
    """One complaint per value whose type is wrong; empty when all are right."""
    problems = []
    for key, accepted in _FIELD_TYPES.items():
        value = values[key]
        wanted = " or ".join(kind.__name__ for kind in accepted)
        # isinstance(True, int) is True, so a JSON `true` would pass an int check.
        if isinstance(value, bool) and bool not in accepted:
            problems.append(f"{key} must be {wanted}, got bool")
        elif not isinstance(value, accepted):
            problems.append(f"{key} must be {wanted}, got {type(value).__name__}")

    if isinstance(values["replaces"], list):
        for item in values["replaces"]:
            if not isinstance(item, str):
                problems.append(f"replaces must hold str, got {type(item).__name__}")
                break
    return problems


def _job(entry: Any) -> Job:
    """Build and validate one decoded JSON entry.

    Any malformed entry raises ValueError naming the job: a registry whose whole
    purpose is explicit metadata must not fail with a bare TypeError, must not
    pass a misspelled key just because keys are optional, and must not accept a
    mistyped value.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"registry entry {entry!r} is not a JSON object")

    defaults = _load_defaults()
    known = {*REQUIRED_FIELDS, *defaults}
    missing = sorted(set(REQUIRED_FIELDS) - entry.keys())
    unknown = sorted(entry.keys() - known)
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown {', '.join(unknown)}")
        raise ValueError(f"job {_label(entry)!r} is {' and '.join(problems)}")

    values = {**defaults, **entry}
    mistyped = _wrong_types(values)
    if mistyped:
        raise ValueError(f"job {_label(entry)!r} has {', '.join(mistyped)}")

    job = Job(**values)
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


def get_job(name: str) -> Job:
    """The registered job, or KeyError naming the unknown job.

    Scans JOBS rather than an index frozen at import, so a replaced JOBS is
    honoured here exactly as it is by `jobs_in_group` and `groups`. Sixty-one
    entries make the scan free.
    """
    for job in JOBS:
        if job.name == name:
            return job
    raise KeyError(name)


def jobs_in_group(group: str) -> list[Job]:
    """Every job in `group`, sorted by name.

    Sorted here rather than relying on JOBS's order: callers may replace the
    module-level JOBS list, and the return order is part of this function's
    contract.
    """
    return sorted((job for job in JOBS if job.group == group), key=lambda job: job.name)


def groups() -> list[str]:
    """Every group that has at least one job, sorted."""
    return sorted({job.group for job in JOBS})
