"""Tests for the dispatch job registry and the loader that validates its data."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from packages.dispatch import registry
from packages.dispatch.registry import JOBS, Job, get_job, groups, jobs_in_group


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
    assert jobs_in_group("backups") == sorted(
        (j for j in JOBS if j.group == "backups"), key=lambda j: j.name
    )


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
    with pytest.raises(ValueError, match="t/x"):
        _validated(name="t/y")


def test_missing_required_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="summary"):
        registry._job({"name": "t/x", "action": "t/x.sh", "group": "t"})


def test_misspelled_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown sudp"):
        _validated(sudp=True)


def test_jobs_without_a_superseded_scheduler_are_manual() -> None:
    j = get_job("maintenance/compliance-report")
    assert j.replaces == []
    assert j.schedule_hint is None


def test_jobs_are_frozen() -> None:
    j = get_job("backups/backup-all")
    with pytest.raises(FrozenInstanceError):
        j.mutates = False  # type: ignore[misc]