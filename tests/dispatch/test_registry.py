"""Tests for the dispatch job registry and the loader that validates its data."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from packages.dispatch import registry
from packages.dispatch.registry import FIELD_DEFAULTS, JOBS, Job, get_job, groups, jobs_in_group


def test_registry_has_61_jobs() -> None:
    assert len(JOBS) == 61


def test_job_names_are_unique_and_sorted() -> None:
    names = [j.name for j in JOBS]
    assert len(names) == len(set(names))
    assert names == sorted(names)


def test_every_job_name_matches_its_action_path() -> None:
    # name is the action path minus the .sh suffix
    for j in JOBS:
        assert j.name == j.action.removesuffix(".sh")


def test_label_exec_context_helper_is_not_registered() -> None:
    assert not any("label-exec-context" in j.name for j in JOBS)


def test_get_job_raises_for_unknown() -> None:
    try:
        get_job("backups/nope")
    except KeyError as e:
        assert "backups/nope" in str(e)
    else:
        raise AssertionError("expected KeyError")


def test_jobs_in_group_and_groups_agree() -> None:
    assert set(groups()) == {j.group for j in JOBS}
    assert jobs_in_group("backups") == sorted((j for j in JOBS if j.group == "backups"), key=lambda j: j.name)


def test_a_replaced_registry_is_honoured_by_every_lookuper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 8 replaces JOBS to model a duplicate action. All three lookups must
    see the replacement, or `get_job` would answer from a stale index."""
    replacement = [Job("t/x", "t/x.sh", "t", "", False, 10, False, "allow", None, [])]
    monkeypatch.setattr(registry, "JOBS", replacement)
    assert get_job("t/x") is replacement[0]
    assert jobs_in_group("t") == replacement
    assert groups() == ["t"]
    with pytest.raises(KeyError):
        get_job("backups/backup-all")


def test_pinned_values() -> None:
    j = get_job("backups/backup-all")
    assert j.sudo is False
    assert j.mutates is True
    assert j.concurrency == "forbid"
    assert j.timeout == 1800

    j = get_job("maintenance/check-disk-space")
    assert j.mutates is False
    assert j.concurrency == "allow"


# The loader's own contract — the validation and the load-time defaults it
# applies to registry_data.json — which no assertion above can reach, because
# the committed data is all valid.


def _validated(**overrides: Any) -> Job:
    """A minimal registry entry — no optional keys — plus any overrides."""
    entry: dict[str, Any] = {"name": "t/x", "action": "t/x.sh", "group": "t", "summary": ""}
    entry.update(overrides)
    return registry._job(entry)


def test_omitted_keys_take_load_time_defaults() -> None:
    job = _validated()
    assert (job.sudo, job.timeout, job.mutates) == (False, 1800, False)
    assert (job.concurrency, job.schedule_hint, job.replaces) == ("allow", None, [])


def test_invalid_concurrency_names_the_offending_job() -> None:
    with pytest.raises(ValueError, match="t/x"):
        _validated(concurrency="maybe")


def test_name_disagreeing_with_action_names_the_offending_job() -> None:
    with pytest.raises(ValueError, match="t/y: name disagrees"):
        _validated(name="t/y")


def test_missing_required_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="summary"):
        registry._job({"name": "t/x", "action": "t/x.sh", "group": "t"})


def test_misspelled_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown sudp"):
        _validated(sudp=True)


def test_quoted_boolean_is_rejected() -> None:
    """`"sudo": "false"` is a truthy string, so accepting it would escalate a
    read-only job to one that runs as root."""
    with pytest.raises(ValueError, match="sudo must be bool, got str"):
        _validated(sudo="false")


def test_quoted_integer_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout must be int, got str"):
        _validated(timeout="1800")


def test_boolean_is_not_accepted_as_an_integer() -> None:
    with pytest.raises(ValueError, match="timeout must be int, got bool"):
        _validated(timeout=True)


def test_scalar_in_place_of_a_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="replaces must be list, got str"):
        _validated(replaces="crontab:0 1 * * *")


def test_non_string_inside_a_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="replaces must hold str, got int"):
        _validated(replaces=[1800])


def test_entry_that_is_not_an_object_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a JSON object"):
        registry._job(["t/x"])


def test_every_wrong_value_is_reported_at_once() -> None:
    with pytest.raises(ValueError) as excinfo:
        _validated(sudo="false", timeout="1800")
    assert "sudo must be bool" in str(excinfo.value)
    assert "timeout must be int" in str(excinfo.value)


def test_the_default_replaces_list_is_never_shared() -> None:
    """FIELD_DEFAULTS is public, so appending to one job's list must not reach
    the default another entry will be built from."""
    first = _validated()
    first.replaces.append("crontab:* * * * *")
    assert _validated().replaces == []
    assert FIELD_DEFAULTS["replaces"] == []


def test_jobs_without_a_superseded_scheduler_are_manual() -> None:
    j = get_job("maintenance/compliance-report")
    assert j.replaces == []
    assert j.schedule_hint is None


def test_scheduled_database_vacuum_is_protected() -> None:
    """VACUUM/ANALYZE is destructive. The plan's override table omitted this job,
    so it is pinned here rather than left to a table that could shrink again."""
    j = get_job("maintenance/vacuum-databases")
    assert j.mutates is True
    assert j.concurrency == "forbid"


def test_jobs_are_frozen() -> None:
    j = get_job("backups/backup-all")
    with pytest.raises(FrozenInstanceError):
        j.mutates = False  # type: ignore[misc]
