"""Tiered retention for run records, and the growth figures `actions list` reports.

Nothing here bounds the database on its own — it is the rule, and `spectre` gains a
caller later. What it does is make the rule stateable: which rows are past due, which
are not, and what each of those decisions cost.

**The tiering is about frequency, not about importance.** A run record is about 200
bytes, and a job that runs every five minutes writes 288 of them a day where a weekly
job writes one — so at a year per row the table grows to roughly 630,000 rows and
126 MB, and at ninety days it stops near 155,000 rows and 31 MB. The frequent jobs are
the ones whose oldest rows nobody will read and whose volume is what makes the table a
problem, so they get the shorter window; the rest keep a year, which is longer than
anyone keeps a job's output by hand.

**`HIGH_FREQUENCY_JOBS` is a policy list, not a measurement of the registry.** As of
this writing no registered job declares a `schedule_hint` more frequent than
`0 1 * * *`, so deriving the set from the hints would produce an empty one and 90 days
would apply to nothing. The two entries below are jobs that report on performance and
disk every few minutes by hand, and are the tier's intended first members. The two
five-minute Prometheus exporters — `collect-metrics` and `check-thresholds` — are what
this tier is *for*, and they are not registry jobs yet: they are the legacy agent's
collectors, which a later plan replaces. Add them here when they become jobs. The test
that asserts every name in this set resolves through `get_job` is what forces that to
be deliberate, since a name matching nothing produces a rule that never fires and no
other symptom.

**Everything is keyed by the full job name**, because that is what
`MaintenanceRecord.action` holds — `save_run` stores `envelope.job`, not the script
path — and it is what `prune`'s `DELETE ... WHERE action = ?` matches against. It is
also what keeps two registered jobs apart: `performance/check-performance` and
`maintenance/check-performance` share the stem `check-performance` and are different
jobs on different schedules.

**The `"unknown"` bucket is the ordinary case, not an edge case.** On the host this was
written against, the live database holds 140,385 run records under 22 distinct
`action` values and *not one of them is a registered job name*: the registry says
`group/name`, and those rows were written by the legacy agent with bare names.
134,256 of them — 95.6% — are the two five-minute collectors. So every live row falls
into this bucket, the 90-day tier reaches none of them, and the retention rule as
specified cannot delete a single row on this host until Plan 3 migrates the schedulers.
The bucket exists so those rows are still bounded rather than immortal: a rule that
only ever named registered jobs would leave a removed job's history behind forever, and
the oldest row here is already older than the table is wide. Deciding what happens to
the legacy collectors' rows — migrate them, name them, or delete them — belongs to the
plan that replaces the legacy agent, not here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlmodel import Session, SQLModel

from packages.dispatch.registry import JOBS, Job, get_job
from packages.memory.db import MaintenanceRecord, engine

# The run-record table as SQLAlchemy sees it. Every column reference below goes
# through it rather than through the model attribute, and that is a typing
# decision: SQLModel declares its fields as `Any`, so `MaintenanceRecord.action == x`
# is a plain `bool` to a checker, which no `where()` will accept. Going through the
# table keeps the SQL bound to the same model the store writes through, and a renamed
# field raises here at import rather than deleting the wrong rows later.
_TABLE = SQLModel.metadata.tables[str(MaintenanceRecord.__tablename__)]

# The key rows are reported under when their `action` names no registered job.
UNKNOWN_JOB = "unknown"

# The two age limits. Ninety days is long enough to compare last month's behaviour,
# and short enough that a five-minute job stays inside a database a laptop can hold.
HIGH_FREQUENCY_RETENTION = timedelta(days=90)
STANDARD_RETENTION = timedelta(days=365)

# Job names, as `save_run` stores them — see the module docstring for why not stems.
HIGH_FREQUENCY_JOBS: frozenset[str] = frozenset(
    {
        # Reports on performance every few minutes when run, and is the first job the
        # 90-day tier exists for.
        "performance/check-performance",
        # Same shape: a periodic report rather than a repair, so its history is a
        # trend line rather than a log of things that broke.
        "maintenance/check-disk-space",
        # The two five-minute Prometheus exporters belong here — see the module
        # docstring. They are legacy agent actions today, and adding them before they
        # are registry jobs would create a rule against names no job has.
    }
)


def cutoff_for(job: Job, now: datetime) -> datetime:
    """The instant before which `job`'s run records may be deleted.

    Exactly `now` minus the tier rather than a rounded or relative figure, so a caller
    passing a fixed `now` gets a fixed answer — which is what lets a caller (or a test)
    place a row exactly on the boundary and know which side of it it is on.
    """
    return now - (HIGH_FREQUENCY_RETENTION if job.name in HIGH_FREQUENCY_JOBS else STANDARD_RETENTION)


def prune(now: datetime | None = None) -> dict[str, int]:
    """Delete every run record past its job's cutoff, and report what went.

    `now` defaults to the moment of the call and exists so a caller can prune against
    a stated instant; the tests use it to sit exactly on a boundary. The return value
    is `{job name or "unknown": rows deleted}`, carrying only the buckets that lost
    rows — a report naming every registered job would be 61 lines, 59 of which would
    say nothing happened.

    One `DELETE` per `action` value that has rows, each bounded by that job's cutoff,
    rather than one statement per registered job: 61 unconditional deletes would take
    an index probe each on a host where two of those jobs write every five minutes,
    and the values that need deleting are exactly the ones the first query returns.

    A single commit for the whole pass, so a prune that fails partway leaves the table
    as it was rather than deleting some of what it was going to delete. The statements
    are index range deletes on a table that is indexed on both columns (`action` and
    `timestamp`, from `ensure_schema`), so the pass is short enough to hold the write
    lock without making a concurrent `save_run` wait out its timeout.

    The comparison is on the wall clock SQLite stored, as `timestamp < ?` is a string
    comparison of an ISO-ish column: a row stamped in a local time is judged by that
    clock, which is hours of error against a ninety-day window.

    It does not create the database. A store that cannot be read raises, because an
    empty report from a host whose database is missing is indistinguishable from a
    report saying nothing was old, and the second is the answer an operator needs.
    """
    moment = now if now is not None else datetime.now(UTC)
    with Session(engine) as session:
        removed: dict[str, int] = {}
        for action, _rows_present in _counts_by_action(session):
            deleted = _delete_older_than(session, action, _cutoff_for_action(action, moment))
            if deleted:
                key = _key_for(action)
                removed[key] = removed.get(key, 0) + deleted
        session.commit()
    # Sorted so the report reads the same way twice, whatever order SQLite grouped in.
    return dict(sorted(removed.items()))


def record_growth() -> dict[str, int]:
    """Current run-record count per job, keyed exactly as `prune` keys its report.

    One grouped pass over the table rather than a count per job: this runs on the
    `actions list` path, against the same table `prune` exists to keep small, and 61
    separate counts would be 61 index probes to answer a question one pass answers.

    Actions belonging to no registered job are summed under `UNKNOWN_JOB`, which is what
    makes the figure honest on the host this was written against — where every row is
    one of those, and a per-job count would report 61 zeroes under a table holding
    140,385 rows.
    """
    with Session(engine) as session:
        counts = _counts_by_action(session)
    return dict(sorted(_fold(counts).items()))


def _counts_by_action(session: Session) -> list[tuple[str, int]]:
    """`(action, rows)` for every `action` that has rows, from one grouped pass.

    SQLAlchemy hands back `Row` objects; unpacking them into plain pairs here means
    neither caller has to cast at its own loop.
    """
    rows = session.execute(select(_TABLE.c.action, func.count()).group_by(_TABLE.c.action)).all()
    return [(str(action), int(count)) for action, count in rows]


def _registered() -> frozenset[str]:
    """Every registered job name, read on each call rather than frozen at import.

    `get_job`, `jobs_in_group` and `groups` all read the module-level `JOBS` when they
    are called, so a caller that replaces it is honoured by all four; freezing the set
    here would make retention the one function that disagrees. Sixty-one names make
    the rebuild free.
    """
    return frozenset(job.name for job in JOBS)


def _key_for(action: str) -> str:
    """The job name an `action` belongs to, or `UNKNOWN_JOB`.

    One place, because `prune`'s report and `record_growth`'s figure are read side by
    side and have to agree on which rows are unattributed — a bucket that named the
    same rows differently in each would make the first look like it had missed some.
    """
    return action if action in _registered() else UNKNOWN_JOB


def _cutoff_for_action(action: str, now: datetime) -> datetime:
    """The cutoff for one `action` value, by the job it names or by the default.

    An unmatched action gets the year tier. It is the conservative choice twice over:
    the rows are the oldest thing in the table, and some of them were written before
    there was a registry at all, so assuming they are as frequent as the jobs would be
    assuming a fact nobody recorded.
    """
    try:
        return cutoff_for(get_job(action), now)
    except KeyError:
        return now - STANDARD_RETENTION


def _delete_older_than(session: Session, action: str, cutoff: datetime) -> int:
    """Delete `action`'s rows older than `cutoff`, and say how many went."""
    result = session.execute(
        delete(MaintenanceRecord).where(
            _TABLE.c.action == action,
            _TABLE.c.timestamp < cutoff,
        )
    )
    # `Session.execute` is typed as returning `Result`, which does not carry a
    # `rowcount`; a DELETE's result is a `CursorResult` and has one. SQLite reports the
    # exact count, not -1, for this statement.
    return cast("CursorResult[Any]", result).rowcount


def _fold(counts: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Group `(action, count)` pairs by job name, summing the rest under `UNKNOWN_JOB`.

    One definition of the summing, so the figure `record_growth` reports and the
    buckets `prune` reports it in cannot drift apart.
    """
    folded: dict[str, int] = {}
    for action, count in counts:
        key = _key_for(action)
        folded[key] = folded.get(key, 0) + count
    return folded
