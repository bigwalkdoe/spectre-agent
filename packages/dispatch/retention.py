"""Tiered retention for run records, and the growth figures `actions list` reports.

Nothing here bounds the database on its own — it is the rule, and `spectre` gains a
caller later. What it does is make the rule stateable: which rows are past due, which
are not, and what each of those decisions cost.

**The tiering is about frequency, not importance — and against this host's data it
currently buys nothing.** Measured on the live table (decimal MB throughout; 202.8 bytes
a row, so its 140,385 rows are 28.5 MB): the two legacy collectors ran at 1,886 rows a
day between them — 943 each — over the 71.2 days from 2026-07-20 to 2026-09-30, peaking
at about 2,620 a day between 2026-08-12 and 2026-09-01, 1,310 from each action, one every
66 seconds per action. *Were* those collectors registry jobs, the 90-day tier would hold
them near 236,000 rows / 48 MB where the 365-day tier would let them reach 956,000 rows /
194 MB — so the tiering is worth roughly four times on that one pair of jobs, and on
nothing else. The other twenty actions run at 24 rows a day (seven-day window), which is
8,760 rows / 1.8 MB at a year.

**None of that applies to the table as it stands.** Every live row is `"unknown"` (below),
so no row sits on a 90-day cutoff and the shorter tier bounds **nothing** here. And the
collectors have written 9 rows in the last seven days, so the 28.5 MB is a seven-week
burst that has already stopped rather than a table that is growing: retention is a guard
against that rate returning, not against current growth. Both numbers are worth having
before those collectors become jobs, because that is the moment the shorter tier starts
to apply — and the moment the first sweep gets big.

**`HIGH_FREQUENCY_JOBS` is a policy list, not a measurement of the registry.** As of
this writing no registered job declares a `schedule_hint` more frequent than
`0 1 * * *`, so deriving the set from the hints would produce an empty one and 90 days
would apply to nothing. The two entries below are jobs that report on performance and
disk every few minutes by hand, and are the tier's intended first members. The two
Prometheus exporters — `collect-metrics` and `check-thresholds` — are what this tier is
*for*, and they are not registry jobs yet: they are the legacy agent's collectors, which
a later plan replaces. Add them here when they become jobs. The test that asserts every
name in this set resolves through `get_job` is what forces that to be deliberate, since a
name matching nothing produces a rule that never fires and no other symptom.

**Everything is keyed by the full job name**, because that is what
`MaintenanceRecord.action` holds — `save_run` stores `envelope.job`, not the script
path — and it is what `prune`'s `DELETE ... WHERE action = ?` matches against. It is
also what keeps two registered jobs apart: `performance/check-performance` and
`maintenance/check-performance` share the stem `check-performance` and are different
jobs on different schedules.

**The `"unknown"` bucket is the ordinary case, not an edge case.** On the host this was
written against, the live database holds 140,385 run records under 22 distinct `action`
values and *not one of them is a registered job name*: the registry says `group/name`,
and those rows were written by the legacy agent with bare names. 134,256 of them — 95.6%
— are the two collectors. So every live row falls into this bucket, the 90-day tier
reaches none of them, and the rule as specified cannot delete a row here before
2027-07-20, when the oldest one — 78 days old — reaches the 365-day cutoff. Nothing is
anywhere near a cutoff today.

The bucket exists so those rows are still bounded rather than immortal. A rule that only
ever named registered jobs would leave a removed job's history behind forever, and
nothing about the collectors' having gone quiet is a promise they will stay quiet. If
their scheduler comes back at the rate they actually ran at, this bucket holds the table
near 140 MB after a year at their 1,886 rows a day, or 194 MB at their observed 2,620
peak — and a gigabyte is five years away at that peak, not one. That ceiling is the
bucket's doing: without it the table would grow without limit, and with it the first
sweep is a sweep of everything rather than of the last few days. Deciding what happens
to those rows — migrate them, name them, or delete them — belongs to the plan that
replaces the legacy agent, not here.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from sqlalchemy import CursorResult, delete, func, select
from sqlmodel import Session, SQLModel, create_engine

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
    rather than one statement per registered job: 61 unconditional deletes would take an
    index probe each on a table this code exists to keep small, and the values that need
    deleting are exactly the ones the one grouped query already returns.

    A single commit for the whole pass, so a prune that fails partway leaves the table
    as it was rather than deleting some of what it was going to delete. Both columns
    are indexed, so each statement is an index range scan. What that buys costs the
    write lock for the length of the pass, and on this host's 28.5 MB table that was
    measured at about 1.0 s to enumerate its 22 actions and delete nothing and about
    1.1 s to delete all 140,385 rows — so the lock is held for seconds, not minutes,
    but whether a first sweep that size should go in one transaction is the caller's
    call rather than this function's. `rows_past_cutoff` is how they get the number
    before making it.

    The comparison is on the wall clock SQLite stored, as `timestamp < ?` is a string
    comparison of an ISO-ish column: a row stamped in a local time is judged by that
    clock, which is hours of error against a ninety-day window.

    It never creates the store — a sweep asked of a host with no database would
    otherwise fabricate an empty one and report nothing to do. See `_require_store`.
    """
    _require_store()
    moment = now if now is not None else datetime.now(UTC)
    with Session(engine) as session:
        removed: dict[str, int] = {}
        for key, action, cutoff in _targets(session, moment):
            deleted = _delete_older_than(session, action, cutoff)
            if deleted:
                removed[key] = removed.get(key, 0) + deleted
        session.commit()
    # Sorted so the report reads the same way twice, whatever order SQLite grouped in.
    return dict(sorted(removed.items()))


def rows_past_cutoff(now: datetime | None = None) -> dict[str, int]:
    """What `prune` would delete right now, without deleting any of it.

    Same keys, same cutoffs, same enumeration — both read `_targets`, so the measurement
    cannot promise a different sweep from the one that runs. Its own reason to exist is
    the operator about to sweep 140,000 rows on a table that is the only record of what
    this machine did: `rows_past_cutoff()` answers "how much is this about to remove"
    without the answer requiring that it be removed.

    **It opens the store read-only**, so the measurement cannot write a row and cannot
    take the write lock. What that does *not* stop is SQLite creating a `-wal` and a
    `-shm` beside a WAL-mode database — shared memory belongs to the directory, not to
    the file's open mode. Measured on a copy of this host's table: the 28.5 MB file was
    byte-identical before and after (same sha256), and the two side files appeared with
    0 and 32 KiB in them. The guarantee a caller actually needs is the first one, and it
    is the one the tests pin. An in-memory engine has no file to open read-only and
    falls back to the ordinary engine, where "no row is deleted" is all that still
    holds.

    Raises on a missing store, like `prune`, because "nothing is old" and "there is
    nothing to be old" are different answers and this is the function whose whole
    purpose is to be believed.
    """
    _require_store()
    moment = now if now is not None else datetime.now(UTC)
    past: dict[str, int] = {}
    # No commit and no session-level write: every statement here is a SELECT.
    with _read_only_session() as session:
        for key, action, cutoff in _targets(session, moment):
            over = _count_older_than(session, action, cutoff)
            if over:
                past[key] = past.get(key, 0) + over
    return dict(sorted(past.items()))


def record_growth() -> dict[str, int]:
    """Current run-record count per job, keyed exactly as `prune` keys its report.

    One grouped pass over the table rather than a count per job: this runs on the
    `actions list` path, against the same table `prune` exists to keep small, and 61
    separate counts would be 61 index probes to answer a question one pass answers.

    Actions belonging to no registered job are summed under `UNKNOWN_JOB`, which is what
    makes the figure honest on the host this was written against — where every row is
    one of those, and a per-job count would report 61 zeroes under a table holding
    140,385 rows.

    It does not create the store either, which is why it checks first rather than
    letting the first query materialise a 4 KiB file: `actions list` is how an operator
    finds out what exists, and it must not leave anything behind to answer.
    """
    _require_store()
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


def _targets(session: Session, now: datetime) -> list[tuple[str, str, datetime]]:
    """`(report key, action, cutoff)` for every `action` that has rows.

    One plan, read by both `prune` and `rows_past_cutoff` — which is what makes the
    measurement trustworthy as a prediction of the sweep rather than merely a similar
    query.
    """
    return [
        (_key_for(action), action, _cutoff_for_action(action, now)) for action, _present in _counts_by_action(session)
    ]


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


def _count_older_than(session: Session, action: str, cutoff: datetime) -> int:
    """How many of `action`'s rows are older than `cutoff`. Reads, and counts."""
    counted = session.execute(
        select(func.count())
        .select_from(_TABLE)
        .where(
            _TABLE.c.action == action,
            _TABLE.c.timestamp < cutoff,
        )
    ).scalar_one()
    return int(counted)


def _store_database() -> str | None:
    """The SQLite file this module's engine points at, `None` if it has no file.

    Read from the engine rather than from `packages.memory.db`'s `DB_FILE`, because the
    engine is what the queries actually go through: an engine swapped in for a test's
    own carries its own path with the swap, and a module-level path would quietly check
    a file the test is not using.
    """
    return engine.url.database


def _has_store() -> bool:
    """Whether the run store exists as a file.

    An in-memory engine has no file to check and is taken to exist — SQLite made it,
    and there is nothing on disk to be missing.
    """
    database = _store_database()
    if not database or database == ":memory:":
        return True
    return Path(database).exists()


def _require_store() -> None:
    """Refuse rather than answer, when there is no store to answer from.

    Both would be lies if they did not: `prune` would fabricate a database and report
    that nothing was old, and `actions list` would leave a 4 KiB file behind a command
    that is supposed to be asking what exists. `FileNotFoundError` rather than
    `OperationalError` because it is a different problem with a different fix, and the
    two are told apart in the tests.

    The check is the file's existence, not a query, so that *asking* is what stays free:
    connecting is what creates the database, and the whole point is not to connect.
    """
    if _has_store():
        return
    raise FileNotFoundError(f"no run store at {_store_database()}; spectre creates it on the first dispatched run")


@contextmanager
def _read_only_session() -> Iterator[Session]:
    """A session on the store opened `mode=ro`, so a measurement cannot write it.

    Falls back to the ordinary engine when there is no file — an in-memory store has
    nothing to open read-only — which is the one case where the guarantee is weaker. The
    guarantee that still holds there is the one that matters to a caller: no row is
    deleted, because nothing here issues a DELETE.
    """
    database = _store_database()
    if not database or database == ":memory:":
        with Session(engine) as session:
            yield session
        return
    # `uri=true` in the query string rather than `connect_args={"uri": True}`: the
    # SQLite dialect parses it out of the URL itself, and handing the same flag to
    # `connect_args` as well makes it treat the `file:` prefix as a filename — which
    # fails as "unable to open database file" against a file that is right there.
    read_only = create_engine(f"sqlite:///file:{quote(database)}?mode=ro&uri=true")
    try:
        with Session(read_only) as session:
            yield session
    finally:
        read_only.dispose()


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
