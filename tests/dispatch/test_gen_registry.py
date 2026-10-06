"""Tests for the registry generator's pure helpers.

`tools/gen_registry.py` regenerates the registry from the real maintenance
suite, so `main()` is never called here — it would read a checkout this test
suite must not touch. What is tested is the part that decides *what* gets
written: grouping, the override table, the schedule hint and the
omit-everything-default rule. Those are pure functions over a script list, so
they are testable without the suite tree.

The one test that reads `registry_data.json` is here rather than in
`test_registry.py` because it asserts the *same* rule as the table-level one
below it, and the reason it needs stating twice is a gap: the table's rule
cannot see what the table does not reach. Both halves are one invariant, and
the pair is kept adjacent so neither is deleted as apparently redundant.
"""

from __future__ import annotations

from typing import Any

import pytest

from packages.dispatch import registry
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
    assert gen_registry.overrides_for("network/setup-vpn") == {
        "sudo": True,
        "mutates": True,
        "concurrency": "forbid",
    }
    assert gen_registry.overrides_for("maintenance/check-disk-space") == {}


def test_the_network_monitor_keeps_the_read_only_defaults() -> None:
    """The one `network/` job the group sweep must not claim.

    `network/` used to sweep the monitor into `sudo`/`mutates`/`concurrency: forbid`,
    which contradicted the audit recorded three paragraphs above the table and cost
    two overlapping manual runs an exit 4 on a read-only monitor. Asserted at three
    levels, because they fail differently: what the table decides for the name, what
    the group predicate claims, and — the one that is actually shipped — what
    `build_entries` emits for the script.

    The group predicate is pinned because the exclusion is carried by it, but its
    verdict alone is not the property: re-widening the predicate while the explicit
    row still comes first changes no entry and is not a regression, so the generated
    entry is what makes the claim hold.
    """
    assert gen_registry.overrides_for("network/network-monitor") == {}
    assert gen_registry.overrides_for("maintenance/network-monitor") == {}
    assert not gen_registry.is_mutating_network_job("network/network-monitor")
    # ...and the rest of the group still mutates, so this is not a group disabled.
    assert gen_registry.is_mutating_network_job("network/setup-vpn")
    assert gen_registry.overrides_for("network/setup-vpn") == {
        "sudo": True,
        "mutates": True,
        "concurrency": "forbid",
    }

    entries = gen_registry.build_entries(["network/network-monitor.sh", "network/setup-vpn.sh"])
    monitor = next(e for e in entries if e["name"] == "network/network-monitor")
    assert "sudo" not in monitor
    assert "mutates" not in monitor
    assert "concurrency" not in monitor
    assert next(e for e in entries if e["name"] == "network/setup-vpn")["concurrency"] == "forbid"


def test_every_override_that_mutates_also_locks() -> None:
    """The table cannot express "this job mutates but takes no lock".

    Four rows used to pair `mutates` with `concurrency: "forbid"` and four did not,
    which left eleven jobs mutating without a lock. The hazard is not those eleven
    on their own — none declared a `schedule_hint`, so nothing automated could fire
    them — it is that the answer depended on which row you read, so the next job
    added to either column inherits the question. `concurrency` is the only field in
    the registry that changes what a run does, so `mutates` without it is a flag
    nothing reads.

    Stated over the table rather than over the committed data, because the table is
    where the decision is made and the data is only its output.
    """
    for matcher, values in gen_registry.OVERRIDES:
        if values.get("mutates"):
            assert values.get("concurrency") == "forbid", f"a mutating override does not lock: {matcher}"


def test_the_committed_registry_holds_the_same_invariant() -> None:
    """The invariant over the data the table produced, which is the half that was unproven.

    `test_every_override_that_mutates_also_locks` reads the table and calls the data
    "only its output", which is true of how the data is *made* and false of what the
    table can *reach*: a job that is reachable only through one row — `network-monitor`
    came in through the `network/` sweep and nowhere else — has its whole metadata
    decided by that row. Narrow that row and forget `concurrency` and the table rule
    cannot see the omission, because the job no longer matches it at all; and
    `verify`'s `unlocked-mutation`, the other half of this invariant, exempts the job
    for being read-only, so a monitor the data calls mutating is not the thing it
    reports on. Nothing in the suite would have noticed.

    Stated over every job rather than only the scheduled ones, because the narrower
    version would have missed exactly this: `network-monitor` has no `schedule_hint`,
    so it is invisible to the gated half by construction. A job with a lock it does not
    need is left allowed, since requiring `mutates` for every lock would forbid a
    deliberate answer to the exit-4 noise the `unlocked-mutation` docstring describes.

    Read through `registry.JOBS` rather than the raw JSON, so the comparison runs on
    the values the registry actually serves — a mistyped `"mutates": "true"` is a
    truthy string, and a test that read the JSON directly would compare against it.
    """
    unlocked = [job.name for job in registry.JOBS if job.mutates and job.concurrency != "forbid"]
    assert unlocked == []
    # The gated subset of the same rule, so this cannot pass while `spectre actions
    # verify` reports on the nine `schedule_hint` values only.
    scheduled = [job.name for job in registry.JOBS if job.schedule_hint and job.mutates and job.concurrency != "forbid"]
    assert scheduled == []


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
