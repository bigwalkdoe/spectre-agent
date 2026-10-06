"""Tests for tiered retention of run records, and the growth figures it reports.

Retention is the only thing standing between a five-minute job and an unbounded
table, and the table is not hypothetical: the live `~/.config/spectre/memory.db` is
28 MB with 140,385 rows in it. So the rules are pinned here as behaviour — which rows
survive a prune, which go, and what the caller is told about it — rather than as the
two constants they are built from.

Three of these tests exist because the obvious version of them would have passed for
the wrong reason:

* **the set of high-frequency jobs is checked against the registry.** A typo in a
  policy list produces a rule that never fires and nothing else, so the assertion is
  that every name in it resolves;
* **the keys are full job names, not bare stems.** `MaintenanceRecord.action` holds
  the job name, and `performance/check-performance` and `maintenance/check-performance`
  are two registered jobs whose stems are both `check-performance` — so keying by stem
  would match both or neither, and neither is right;
* **the `"unknown"` bucket is tested as the ordinary case, not an edge case.** Not one
  of the 22 `action` values on the live database matches a registered job, because the
  registry names are `group/name` and those rows were written by the legacy agent with
  bare names. Every live row therefore lands in this bucket, and it is the only path
  that will run on this host until Plan 3 migrates the schedulers.

Nothing here touches the live database. Each test is given a database of its own, wired
in over both modules' engines, so `prune` here cannot delete a row any other test made.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

from packages.dispatch import retention
from packages.dispatch.envelope import Envelope, Status
from packages.dispatch.registry import JOBS, get_job
from packages.dispatch.retention import (
    HIGH_FREQUENCY_JOBS,
    STANDARD_RETENTION,
    UNKNOWN_JOB,
    cutoff_for,
    prune,
    record_growth,
    rows_past_cutoff,
)
from packages.memory import db as db_module
from packages.memory.db import MaintenanceRecord, save_run

# A fixed instant, so a row placed exactly on a cutoff is placed exactly on it.
# `datetime.now()` would drift under the test's own runtime and turn the boundary
# assertions into a coin toss.
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)

# Both names exist in the registry. `performance/…` is the high-frequency one,
# which is what makes the pair useful: they differ only by group.
HIGH_FREQUENCY_JOB = "performance/check-performance"
STANDARD_JOB = "backups/backup-all"

# A bare agent action name, of the kind the legacy agent wrote. Registered names are
# `group/name`, so this matches no job — which is exactly the point.
LEGACY_ACTION = "collect-metrics"


@pytest.fixture()
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """A database of this test's own, wired in wherever retention looks for one.

    Both `retention`'s and `db`'s engine are replaced, so `save_run` writes here too
    and a test can pin the link between what `save_run` stores in `action` and what
    `prune` groups by — without going anywhere near the session-wide throwaway
    database the rest of the suite shares, or the live one.
    """
    isolated = create_engine(f"sqlite:///{tmp_path / 'runs.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(isolated)
    monkeypatch.setattr(retention, "engine", isolated)
    monkeypatch.setattr(db_module, "engine", isolated)
    yield isolated


def _put(store: Engine, action: str, when: datetime) -> int:
    """One run record with an explicit `action` and `timestamp`."""
    with Session(store) as session:
        record = MaintenanceRecord(
            timestamp=when,
            agent="dispatch",
            action=action,
            status="success",
            log_output="",
            duration_ms=1,
        )
        session.add(record)
        session.commit()
        # A raise rather than an `assert`, which `python -O` strips.
        if record.id is None:
            raise RuntimeError("a committed MaintenanceRecord has an id")
        return record.id


def _rows(store: Engine, action: str) -> list[int]:
    """The ids of `action`'s surviving records, in insertion order.

    Read through the table rather than the model attribute, as in `retention`:
    SQLModel's fields are `Any`, so `MaintenanceRecord.id` is not something
    `order_by` will accept from a type checker.
    """
    table = SQLModel.metadata.tables[str(MaintenanceRecord.__tablename__)]
    with Session(store) as session:
        found = session.execute(select(table.c.id).where(table.c.action == action).order_by(table.c.id)).scalars().all()
    return sorted(found)


def _envelope(job: str, started_at: datetime) -> Envelope:
    """The envelope a run of `job` starting at `started_at` would produce."""
    return Envelope(
        job=job,
        trigger="cron",
        started_at=started_at,
        duration_ms=1,
        exit_code=0,
        resolved_path=f"/x/{job}.sh",
        git_commit="",
        git_dirty=False,
        stdout_tail="",
        stderr_tail="",
        status=Status.SUCCESS,
        payload=None,
    )


# ── the policy ───────────────────────────────────────────────────────────────


def test_every_high_frequency_name_is_a_registered_job() -> None:
    """The set is a list of names, and a name that matches no job is a rule that
    never fires.

    Nothing else would notice: `cutoff_for` asks only whether a name is in the set,
    so a misspelled entry silently declines to apply its own tier to anything, and a
    retention rule that quietly does nothing is worse than no rule at all — it reads
    in the source as protection. The check also forces the two Prometheus exporters,
    which are not registry jobs yet, to be added deliberately when they become ones.
    """
    assert HIGH_FREQUENCY_JOBS, "an empty set applies the 90-day tier to nothing"
    registered = {job.name for job in JOBS}
    assert sorted(HIGH_FREQUENCY_JOBS - registered) == []


def test_high_frequency_jobs_keep_90_days() -> None:
    job = get_job(HIGH_FREQUENCY_JOB)
    assert job.name in HIGH_FREQUENCY_JOBS
    assert cutoff_for(job, NOW) == NOW - timedelta(days=90)


def test_other_jobs_keep_a_year() -> None:
    """Exactly a year, not "at least a year": the caller has to be able to reason
    about the instant, and `>=` would pass for a rule that kept nothing at all."""
    job = get_job(STANDARD_JOB)
    assert job.name not in HIGH_FREQUENCY_JOBS
    assert cutoff_for(job, NOW) == NOW - STANDARD_RETENTION


def test_two_jobs_sharing_a_stem_are_told_apart() -> None:
    """`maintenance/check-performance` and `performance/check-performance` are two
    registered jobs, and both stems are `check-performance`.

    So the set cannot be keyed by the stem the plan's first draft used: doing so
    would either exempt both jobs or neither, and `prune` — which deletes with
    `WHERE action = ?` against the full name `save_run` stored — would match neither.
    """
    twin = get_job("maintenance/check-performance")
    job = get_job(HIGH_FREQUENCY_JOB)
    assert twin.name.split("/")[-1] == job.name.split("/")[-1]
    assert twin.name != job.name
    assert twin.name not in HIGH_FREQUENCY_JOBS
    assert cutoff_for(twin, NOW) == NOW - STANDARD_RETENTION
    assert cutoff_for(job, NOW) == NOW - timedelta(days=90)


# ── prune ────────────────────────────────────────────────────────────────────


def test_prune_keeps_a_high_frequency_job_to_ninety_days(engine: Engine) -> None:
    """A row exactly on the cutoff is kept; one a second older is not.

    The two rows straddle the boundary deliberately. `timestamp < cutoff` is the rule,
    and a row stamped at the cutoff instant has not yet aged past it — so testing only
    "100 days old went" and "1 day old stayed" would pass against a rule that deleted
    far more than it should.
    """
    cutoff = cutoff_for(get_job(HIGH_FREQUENCY_JOB), NOW)
    on_the_line = _put(engine, HIGH_FREQUENCY_JOB, cutoff)
    past_it = _put(engine, HIGH_FREQUENCY_JOB, cutoff - timedelta(seconds=1))
    recent = _put(engine, HIGH_FREQUENCY_JOB, NOW - timedelta(hours=1))

    assert prune(NOW) == {HIGH_FREQUENCY_JOB: 1}
    assert sorted(_rows(engine, HIGH_FREQUENCY_JOB)) == sorted([on_the_line, recent])
    assert past_it not in _rows(engine, HIGH_FREQUENCY_JOB)


def test_prune_keeps_a_standard_job_to_a_year(engine: Engine) -> None:
    """A year of history, not ninety days.

    The 90-day-old row is here to be the assertion: it is the age a high-frequency
    job's row is deleted at, and it survives here because this job's tier is longer.
    A prune that applied one limit to everything would keep the year-old row and drop
    this one, which is backwards.
    """
    cutoff = cutoff_for(get_job(STANDARD_JOB), NOW)
    on_the_line = _put(engine, STANDARD_JOB, cutoff)
    past_it = _put(engine, STANDARD_JOB, cutoff - timedelta(seconds=1))
    ninety_days_old = _put(engine, STANDARD_JOB, NOW - timedelta(days=90))

    assert prune(NOW) == {STANDARD_JOB: 1}
    assert sorted(_rows(engine, STANDARD_JOB)) == sorted([on_the_line, ninety_days_old])
    assert past_it not in _rows(engine, STANDARD_JOB)


def test_prune_leaves_a_job_with_no_old_rows_out_of_its_report(engine: Engine) -> None:
    """The report is what a caller prints, so it names what changed.

    A job that had nothing to delete is not mentioned: a report listing every
    registered job would be 61 lines, 59 of which say nothing happened.
    """
    _put(engine, STANDARD_JOB, NOW)
    _put(engine, HIGH_FREQUENCY_JOB, NOW)
    assert prune(NOW) == {}


def test_prune_groups_rows_the_way_save_run_stores_them(engine: Engine) -> None:
    """`save_run` writes `action = envelope.job` — the job name, not the script path.

    So a prune keyed by the action string, the `.sh` path or the bare stem would match
    no row this code path creates and delete nothing, silently. Going through
    `save_run` rather than inserting rows directly is what makes this the assertion:
    it fails if the two ever stop agreeing.
    """
    save_run(_envelope(HIGH_FREQUENCY_JOB, NOW - timedelta(days=200)))
    save_run(_envelope(HIGH_FREQUENCY_JOB, NOW - timedelta(days=10)))

    assert prune(NOW) == {HIGH_FREQUENCY_JOB: 1}
    assert len(_rows(engine, HIGH_FREQUENCY_JOB)) == 1


def test_prune_folds_rows_with_no_registered_job_into_unknown(engine: Engine) -> None:
    """The bucket is the whole population on the live database, so it is the case.

    None of the 22 `action` values in the host's 140,385 rows matches a registered
    job: the registry says `group/name` and the legacy agent wrote bare names. They
    are still run history, so they are still pruned — at the year tier, the
    conservative one — and they are reported under one key so a caller can see the
    job that owns no rows at all. Several unmatched names are summed: a report with a
    key per legacy action would not be a count of anything.
    """
    year = NOW - STANDARD_RETENTION
    _put(engine, LEGACY_ACTION, year - timedelta(seconds=1))
    _put(engine, "system-health-check", year - timedelta(days=2))
    within_the_year = _put(engine, LEGACY_ACTION, year + timedelta(days=1))

    assert prune(NOW) == {UNKNOWN_JOB: 2}
    assert _rows(engine, LEGACY_ACTION) == [within_the_year]
    assert _rows(engine, "system-health-check") == []


def test_prune_does_not_fold_a_registered_job_into_unknown(engine: Engine) -> None:
    """The two buckets mean different things: one is a job with a tier, the other is
    a row with no job. A registered job's row reported as unknown would send an
    operator looking for a missing job that is present."""
    _put(engine, STANDARD_JOB, NOW - STANDARD_RETENTION - timedelta(seconds=1))
    assert prune(NOW) == {STANDARD_JOB: 1}


def test_prune_is_idempotent(engine: Engine) -> None:
    """Running it twice must not report removing the same rows twice.

    The report is what an operator reconciles a row count against, so a prune that
    counted rows it had already deleted would make the database look smaller than it
    is.
    """
    _put(engine, STANDARD_JOB, NOW - STANDARD_RETENTION - timedelta(days=1))
    _put(engine, LEGACY_ACTION, NOW - STANDARD_RETENTION - timedelta(days=1))
    assert sum(prune(NOW).values()) == 2
    assert prune(NOW) == {}
    assert sum(prune(NOW).values()) == 0


def test_prune_raises_on_a_database_with_no_run_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A store that cannot be read is a failure, not an empty result.

    `prune` is a deliberate maintenance call and it does not create the database: an
    empty dict here would be indistinguishable from "nothing was old", on the one host
    where running it means something is wrong.
    """
    target = tmp_path / "empty.db"
    empty = create_engine(f"sqlite:///{target}")
    SQLModel.metadata.create_all(empty)
    empty.dispose()
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("DROP TABLE maintenancerecord")
    monkeypatch.setattr(retention, "engine", create_engine(f"sqlite:///{target}"))
    with pytest.raises(OperationalError, match="maintenancerecord"):
        prune(NOW)


def test_prune_refuses_to_create_a_store_that_is_not_there(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sweep asked of a host with no database must not hand it one.

    The obvious implementation connects, and connecting is what creates the file — so
    `prune` against a fresh host would leave an empty database behind and report that
    nothing was old, which is a fabrication on both counts. The file check happens
    before any connection is opened, which is the only order in which "asking" is free.
    """
    target = tmp_path / "cfg" / "memory.db"
    monkeypatch.setattr(retention, "engine", create_engine(f"sqlite:///{target}"))

    with pytest.raises(FileNotFoundError, match="no run store"):
        prune(NOW)
    assert not target.exists()
    assert not (tmp_path / "cfg").exists(), "connecting is what creates a SQLite file"


def test_record_growth_refuses_to_create_a_store_that_is_not_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same property on the read path, which is the one `spectre actions list` takes.

    `actions list` is how an operator finds out what they can run. A command that
    answers that question by creating a 4 KiB file in a config directory it was only
    reading is a regression, and it is one that also fails outright wherever the config
    directory cannot be created at all.
    """
    target = tmp_path / "cfg" / "memory.db"
    monkeypatch.setattr(retention, "engine", create_engine(f"sqlite:///{target}"))

    with pytest.raises(FileNotFoundError, match="no run store"):
        record_growth()
    assert not (tmp_path / "cfg").exists()


# ── rows_past_cutoff ──────────────────────────────────────────────────────────


def test_rows_past_cutoff_reports_the_sweep_without_deleting(engine: Engine) -> None:
    """The measurement is the guard before a sweep, so it has to be exact and inert.

    Exact: the same keys and the same counts `prune` then reports, which is only true
    because both read one plan — a measurement that drifted from the sweep would be
    worse than none, since it would be believed. Inert: every row still there
    afterwards.
    """
    year = NOW - STANDARD_RETENTION
    expired = _put(engine, STANDARD_JOB, year - timedelta(days=1))
    kept = _put(engine, STANDARD_JOB, NOW)
    _put(engine, HIGH_FREQUENCY_JOB, NOW - timedelta(days=200))
    _put(engine, LEGACY_ACTION, year - timedelta(days=1))

    predicted = {STANDARD_JOB: 1, HIGH_FREQUENCY_JOB: 1, UNKNOWN_JOB: 1}
    assert rows_past_cutoff(NOW) == predicted
    # Inert: both rows of the expired job are still there, the old one included.
    assert _rows(engine, STANDARD_JOB) == [expired, kept]
    assert prune(NOW) == predicted, "the sweep must match what it promised"
    assert rows_past_cutoff(NOW) == {}


def test_rows_past_cutoff_does_not_create_a_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "cfg" / "memory.db"
    monkeypatch.setattr(retention, "engine", create_engine(f"sqlite:///{target}"))
    with pytest.raises(FileNotFoundError, match="no run store"):
        rows_past_cutoff(NOW)
    assert not (tmp_path / "cfg").exists()


def test_the_measurement_holds_the_store_read_only(engine: Engine) -> None:
    """Proven by trying to write through the session, not by reading a URL string.

    A read-only *connection* is the difference between a measurement that cannot change
    the data and one that merely issued no DELETE, and only SQLite can say which one
    this is. Without the `mode=ro` this still passes every "did not delete" assertion,
    because `rows_past_cutoff` would simply not be issuing the write.
    """
    _put(engine, STANDARD_JOB, NOW)
    with retention._read_only_session() as session:
        assert (
            session.execute(select(func.count()).select_from(SQLModel.metadata.tables["maintenancerecord"])).scalar()
            == 1
        )
        with pytest.raises(OperationalError, match="readonly"):
            session.execute(delete(MaintenanceRecord))


# ── record_growth ────────────────────────────────────────────────────────────


def test_record_growth_counts_each_job(engine: Engine) -> None:
    _put(engine, STANDARD_JOB, NOW)
    _put(engine, STANDARD_JOB, NOW - timedelta(days=1))
    _put(engine, HIGH_FREQUENCY_JOB, NOW)
    assert record_growth() == {STANDARD_JOB: 2, HIGH_FREQUENCY_JOB: 1}


def test_record_growth_folds_unmatched_actions_into_unknown(engine: Engine) -> None:
    """Same keying as `prune`, deliberately: the two are read side by side, and one
    reporting 140,385 rows while the other could not name where they went would be a
    worse answer than either alone."""
    _put(engine, LEGACY_ACTION, NOW)
    _put(engine, "system-health-check", NOW)
    assert record_growth() == {UNKNOWN_JOB: 2}


def test_record_growth_is_empty_when_there_are_no_rows(engine: Engine) -> None:
    """An empty mapping, which the caller reads as "every job has none" — the case a
    fresh install is in, and the one a missing table would wrongly look like."""
    assert record_growth() == {}
