"""Tests for the registry generator's pure helpers.

`tools/gen_registry.py` regenerates the registry from the real maintenance
suite, so `main()` is never called here — it would read a checkout this test
suite must not touch. What is tested is the part that decides *what* gets
written: grouping, the override table, the schedule hint and the
omit-everything-default rule. Those are pure functions over a script list, so
they are testable without the suite tree.
"""

from __future__ import annotations

from typing import Any

import pytest

from packages.dispatch.registry import FIELD_DEFAULTS, REQUIRED_FIELDS
from tools import gen_registry

SCRIPTS = [
    "backups/backup-all.sh",
    "deploy-monitoring.sh",
    "maintenance/check-disk-space.sh",
    "maintenance/compliance-report.sh",
    "maintenance/vacuum-databases.sh",
    "security/run-security-hardening.sh",
]


def _entry(name: str) -> dict[str, Any]:
    return next(e for e in gen_registry.build_entries(SCRIPTS) if e["name"] == name)


def test_top_level_scripts_are_their_own_group() -> None:
    assert gen_registry.group_for("deploy-monitoring.sh") == "deploy-monitoring"
    assert gen_registry.group_for("maintenance/cleanup-temp.sh") == "maintenance"


def test_schedule_hint_is_the_superseded_cron_expression() -> None:
    assert gen_registry.schedule_hint_for(["crontab:0 1 * * *"]) == "0 1 * * *"
    assert gen_registry.schedule_hint_for(["user:maintenance.service"]) is None
    assert gen_registry.schedule_hint_for([]) is None


def test_override_table_matches_the_committed_registry() -> None:
    """The table is the single place job metadata is decided, so it is pinned
    here and cross-checked against what actually shipped."""
    assert gen_registry.overrides_for("backups/backup-all") == {"mutates": True, "concurrency": "forbid"}
    assert gen_registry.overrides_for("maintenance/vacuum-databases") == {"mutates": True, "concurrency": "forbid"}
    assert gen_registry.overrides_for("security/run-security-hardening") == {
        "sudo": True,
        "mutates": True,
        "concurrency": "forbid",
    }
    assert gen_registry.overrides_for("network/setup-vpn") == {"sudo": True, "mutates": True}
    assert gen_registry.overrides_for("maintenance/check-disk-space") == {}


def test_generated_entries_omit_every_default_valued_key() -> None:
    """A job with no override and no superseded scheduler carries only the keys
    it cannot omit, so the data file reads as 'everything absent is a default'."""
    entry = _entry("maintenance/compliance-report")
    assert set(entry) == set(REQUIRED_FIELDS)
    assert entry["summary"]


def test_a_default_valued_key_is_never_written_out() -> None:
    for entry in gen_registry.build_entries(SCRIPTS):
        for key in FIELD_DEFAULTS:
            if key in entry:
                assert entry[key] != FIELD_DEFAULTS[key], f"{entry['name']} wrote a default {key}"


def test_generated_entries_carry_only_real_deviations() -> None:
    entry = _entry("backups/backup-all")
    assert entry["mutates"] is True
    assert entry["concurrency"] == "forbid"
    assert entry["schedule_hint"] == "0 2 * * 6"
    assert entry["replaces"] == ["crontab:0 2 * * 6", "user:backup.service"]


def test_entries_are_sorted_and_omit_nothing_required() -> None:
    entries = gen_registry.build_entries(SCRIPTS)
    assert [e["name"] for e in entries] == sorted(e["name"] for e in entries)
    assert all(set(REQUIRED_FIELDS) <= set(e) for e in entries)


def test_a_script_with_no_summary_is_an_error_not_a_guess() -> None:
    with pytest.raises(ValueError, match="no summary for t/unknown"):
        gen_registry.build_entries(["t/unknown.sh"])
