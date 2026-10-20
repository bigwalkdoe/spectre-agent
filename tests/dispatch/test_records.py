"""Tests for the run records dispatch writes, and for the migration that made room.

Two things are being pinned here, and the second is the one that could hurt a host.

A run record has to carry the provenance an operator needs to answer "which revision
of this checkout ran this, was the tree dirty, and what did the action say". The old
`maintenancerecord` had nowhere to put any of that, so a run recorded only that a job
succeeded — which is exactly the record that cannot be diagnosed after the fact.

That is also why the migration is the interesting half. The live
`~/.config/spectre/memory.db` is 28 MB with 140,385 rows and this repo has no Alembic,
so declaring the seven columns is not enough: `SQLModel.metadata.create_all()` does not
alter an existing table, and every query against the host's database would then raise
`OperationalError: no such column: maintenancerecord.trigger`. `ensure_schema` exists
to add them, and the properties that matter are that it adds them to a table it did not
create, that it leaves the rows already there alone — every value, not merely every
count — and that running it again changes nothing at all.

Nothing here touches the live database. `tests/conftest.py` has already pointed
`SPECTRE_CONFIG_DIR` at a throwaway tree before `packages.memory.db` was imported, and
the migration tests build their own databases under `tmp_path`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from packages.dispatch.envelope import Envelope, Status
from packages.memory import db as db_module
from packages.memory.db import (
    SecurityIncident,
    ensure_schema,
    get_security_incidents,
    init_db,
    recent_runs,
    save_run,
)

# The seven columns the dispatch layer adds, written out here rather than imported
# from the module so the test states the contract instead of restating the code.
_ADDED = {
    "trigger",
    "exit_code",
    "resolved_path",
    "git_commit",
    "git_dirty",
    "payload",
    "stderr_tail",
}

# The columns that existed before the migration, and the only ones a preservation
# check may read back: the point is that nothing here changed.
_LEGACY_COLUMNS = "id, timestamp, agent, action, status, log_output, duration_ms"

# Rows in the pre-migration fixture. Large enough that a rewrite rather than an
# in-place ALTER would be caught by the length of the write, small enough to build
# on every run.
_LEGACY_ROWS = 500

# The shape four simultaneous writers take. Every one of the resulting records must
# land, at exactly this many copies per job.
_WRITERS = 4
_WRITES_PER_WRITER = 5

# A default payload built by name rather than inline, so it is a value rather than a
# mutable literal in the signature (ruff B006) and `payload=None` stays expressible.
_DEFAULT_PAYLOAD: dict[str, Any] = {"metrics": {"bytes": 42}}


def _env(
    job: str = "backups/backup-all",
    status: Status = Status.SUCCESS,
    trigger: str = "cron",
    exit_code: int | None = 0,
    payload: dict[str, Any] | None = _DEFAULT_PAYLOAD,
    started_at: datetime | None = None,
) -> Envelope:
    return Envelope(
        job=job,
        trigger=trigger,
        started_at=started_at if started_at is not None else datetime.now(UTC),
        duration_ms=5,
        exit_code=exit_code,
        resolved_path="/x/backup-all.sh",
        git_commit="f493805",
        git_dirty=True,
        stdout_tail="out",
        stderr_tail="err",
        status=status,
        payload=payload,
    )


def _aware_utc(value: datetime) -> datetime:
    """The instant `value` names, with UTC attached if SQLite returned it naive.

    SQLModel 0.0.48 returns timestamps as aware UTC; older versions returned them
    naive. These tests care that the first-seen instant survives, not which of the
    two the installed SQLModel happens to produce.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _pre_migration_db(db: Path) -> Path:
    """Build the seven-column `maintenancerecord` a host has today.

    Every column carries a value unique to its row — `log_output` says which row it
    belongs to and `duration_ms` is the row number — so a migration that rewrote or
    reordered rows would be visible, which a row count alone could not show. The
    text includes non-ASCII and a quote because TEXT that survives a round trip
    through the migration is part of the claim being made.
    """
    with closing(sqlite3.connect(db)) as con:
        con.execute(
            "CREATE TABLE maintenancerecord (id INTEGER PRIMARY KEY, timestamp DATETIME, "
            "agent VARCHAR, action VARCHAR, status VARCHAR, log_output VARCHAR, duration_ms INTEGER)"
        )
        con.executemany(
            f"INSERT INTO maintenancerecord ({_LEGACY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    index,
                    f"2026-01-{(index % 28) + 1:02d} 00:00:00.{index:06d}",
                    f"agent-{index % 3}",
                    f"job-{index}",
                    "success" if index % 2 else "failed",
                    f"log output for row {index} — \u00e9\u4e2d\u6587 and a 'quote'",
                    index,
                )
                for index in range(1, _LEGACY_ROWS + 1)
            ],
        )
        con.commit()
    return db


def _read(db: Path, columns: str) -> list[tuple[Any, ...]]:
    # `ORDER BY id` so a comparison of two reads is about the values rather than
    # about whatever order the table happened to be scanned in.
    with closing(sqlite3.connect(db)) as con:
        return con.execute(f"SELECT {columns} FROM maintenancerecord ORDER BY id").fetchall()


def _columns(db: Path) -> set[str]:
    with closing(sqlite3.connect(db)) as con:
        return {row[1] for row in con.execute("PRAGMA table_info(maintenancerecord)")}


def _indexes(db: Path) -> set[str]:
    with closing(sqlite3.connect(db)) as con:
        return {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def _incidents(rule_id: str, resolved: bool = False) -> list[SecurityIncident]:
    return [i for i in get_security_incidents(resolved=resolved, limit=200) if i.rule_id == rule_id]


def _resolve(rule_id: str) -> None:
    """Mark a rule's rows resolved, as an operator closing an incident would."""
    with Session(db_module.engine) as session:
        for row in session.exec(select(SecurityIncident).where(SecurityIncident.rule_id == rule_id)).all():
            row.resolved = True
        session.commit()


class _ScriptedConnection:
    """A real SQLite connection with the outcome of its first `ALTER` replaced.

    The migration reads the column list and only then issues each `ALTER`, so both
    the "another process migrated this in between" case and the "the database is
    unavailable" case live entirely inside that gap — a window no test can reach from
    outside. Substituting the connection is how either is produced deterministically
    rather than by timing. Everything else, including the `PRAGMA table_info` read the
    migration bases its decision on, is the real connection doing real work.
    """

    def __init__(self, real: sqlite3.Connection, before_alter: Callable[[sqlite3.Connection], None]) -> None:
        self._real = real
        self._before_alter = before_alter
        self._armed = True

    def execute(self, sql: str) -> sqlite3.Cursor:
        if sql.startswith("ALTER TABLE") and self._armed:
            self._armed = False
            self._before_alter(self._real)
        return self._real.execute(sql)

    def commit(self) -> None:
        self._real.commit()

    def close(self) -> None:
        self._real.close()


@contextmanager
def _scripted_connection(
    monkeypatch: pytest.MonkeyPatch, before_alter: Callable[[sqlite3.Connection], None]
) -> Iterator[None]:
    """Hand `ensure_schema` the scripted connection for the length of the block."""
    real = sqlite3.connect
    with monkeypatch.context() as patch:
        patch.setattr(
            db_module.sqlite3,
            "connect",
            lambda target: _ScriptedConnection(real(target), before_alter),
        )
        yield


# ── the records ──────────────────────────────────────────────────────────────


def test_save_run_round_trips_provenance() -> None:
    rid = save_run(_env())
    row = next(r for r in recent_runs(limit=10) if r.id == rid)
    assert row.action == "backups/backup-all"
    assert row.agent == "dispatch"
    assert row.status == "success"
    assert row.exit_code == 0
    assert row.trigger == "cron"
    assert row.resolved_path == "/x/backup-all.sh"
    assert row.git_commit == "f493805"
    assert row.git_dirty is True
    assert row.payload is not None and "bytes" in row.payload


def test_a_run_that_never_reached_an_exit_code_records_none() -> None:
    """A refused job never ran, so it has no exit code — and must not be given one.

    Storing `0` would make a refusal indistinguishable from a success to anything
    reading the column back.
    """
    rid = save_run(_env(status=Status.REFUSED, trigger="api", exit_code=None))
    row = next(r for r in recent_runs(limit=10) if r.id == rid)
    assert row.status == "refused"
    assert row.exit_code is None
    assert row.trigger == "api"


def test_save_run_round_trips_the_stderr_tail() -> None:
    """A failure's diagnostic is on stderr, so the record has to keep it.

    `log_output` is stdout and other code already reads it, so the stderr tail gets
    its own column rather than being appended to that one. Keeping only one of the
    two streams is the failure this is here to catch: the record still looks
    complete, so the missing half is invisible until it is the half being needed.
    """
    rid = save_run(_env(status=Status.FAILED, exit_code=1))
    row = next(r for r in recent_runs(limit=10) if r.id == rid)
    assert row.status == "failed"
    assert row.stderr_tail == "err"
    # stdout still lands in its own column, untouched.
    assert row.log_output == "out"


def test_a_run_with_no_payload_stores_none() -> None:
    rid = save_run(_env(payload=None))
    assert next(r for r in recent_runs(limit=10) if r.id == rid).payload is None


def test_a_payload_json_cannot_encode_still_gets_a_record() -> None:
    """The payload is optional extra; the fact that the run happened is not.

    A `datetime`, a `Path` and a `set` are what a payload can legitimately carry and
    `json` cannot encode. Falling back to `str` keeps the run recorded, where raising
    would drop the only evidence that it happened at all — the same rule a malformed
    finding inside that payload already follows.
    """
    rid = save_run(
        _env(
            job="unserialisable/payload",
            payload={"at": datetime.now(UTC), "path": Path("/x/backup-all.sh"), "tags": {"a", "b"}},
        )
    )
    row = next(r for r in recent_runs(limit=10) if r.id == rid)
    assert row.status == "success"
    assert row.payload is not None
    decoded = json.loads(row.payload)
    assert decoded["path"] == "/x/backup-all.sh"
    assert decoded["at"]
    # Stringified rather than dropped; a set has no JSON form and no stable order,
    # so this only claims the elements survived.
    assert "a" in decoded["tags"] and "b" in decoded["tags"]


def test_recent_runs_filters_by_job() -> None:
    save_run(_env(job="a/one"))
    save_run(_env(job="b/two"))
    got = recent_runs(job="b/two")
    assert got and all(r.action == "b/two" for r in got)


def test_recent_runs_is_newest_first() -> None:
    """Newest record first — asserted on one result, not on two joined together.

    A per-job filter returns each job's own rows, so joining two of those results
    produces `[older job's rows, newer job's rows]` whatever the order inside each
    and says nothing about the ordering being claimed.
    """
    ids = [save_run(_env(job=f"order/{index}")) for index in range(3)]
    assert [r.id for r in recent_runs(limit=3)] == list(reversed(ids))


def test_recent_runs_respects_limit() -> None:
    for index in range(4):
        save_run(_env(job=f"limit/{index}"))
    assert len(recent_runs(limit=2)) == 2


def test_a_second_run_of_the_same_job_is_its_own_record() -> None:
    """Two runs of one job are two records, and the first must survive the second.

    A run is evidence, not a slot: the second run must not rewrite the first one's
    payload, and must not be stored twice either. Both are checked against the rows
    that existed beforehand, so the assertion is about what this test added.
    """
    before = {r.id for r in recent_runs(job="repeat/one", limit=50)}
    first = save_run(_env(job="repeat/one", payload={"metrics": {"bytes": 1}}))
    second = save_run(_env(job="repeat/one", payload={"metrics": {"bytes": 2}}))

    rows = recent_runs(job="repeat/one", limit=50)
    added = [r for r in rows if r.id not in before]
    assert {r.id for r in added} == {first, second}

    payloads = {r.id: r.payload for r in added}
    first_payload = payloads[first]
    second_payload = payloads[second]
    assert first_payload is not None and second_payload is not None
    assert json.loads(first_payload) == {"metrics": {"bytes": 1}}
    assert json.loads(second_payload) == {"metrics": {"bytes": 2}}


def test_concurrent_writers_all_land() -> None:
    """Review Focus 5: exporters and a cron job write simultaneously.

    The barrier is what makes this a concurrency test rather than a loop — without
    it the four threads would be scheduled one after another and would never overlap.

    It pins that all twenty writes land and none raises. It does not prove WAL, and
    should not be read as doing so: SQLite serialises writer against writer behind the
    busy timeout whatever the journal mode, so a rollback journal passes this too —
    measured, with the pragma removed. The journal mode is pinned separately, by the
    read-in-flight test below.
    """
    errors: list[BaseException] = []
    barrier = threading.Barrier(_WRITERS)

    def worker(n: int) -> None:
        try:
            barrier.wait()
            for i in range(_WRITES_PER_WRITER):
                save_run(_env(job=f"a/{n}-{i}"))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(_WRITERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    expected = {f"a/{n}-{i}" for n in range(_WRITERS) for i in range(_WRITES_PER_WRITER)}
    counts = Counter(r.action for r in recent_runs(limit=500))
    assert expected <= set(counts), sorted(expected - set(counts))
    # Every one of the twenty writes, not merely twenty rows: a writer that lost a
    # commit to another thread would leave its name present but short of a copy.
    assert sum(counts[job] for job in expected) == _WRITERS * _WRITES_PER_WRITER, counts


def test_a_read_in_flight_does_not_block_a_write() -> None:
    """Why WAL is turned on at all, asserted as behaviour rather than as a pragma.

    An exporter reading the run history while a cron job records its result is the
    ordinary case: one reader and one writer at the same moment. Under SQLite's
    default rollback journal the writer cannot take its exclusive lock until that
    reader finishes, and it gives up with `database is locked` once the busy timeout
    expires; under WAL the write appends to the log and both carry on. So this
    returns in milliseconds with the pragma in place and spends the lock timeout
    failing without it — which makes it the test that would notice the pragma
    going away.
    """
    with closing(sqlite3.connect(db_module.DB_FILE, isolation_level=None)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM maintenancerecord").fetchone()
        rid = save_run(_env(job="wal/read-then-write"))
        reader.execute("ROLLBACK")

    assert any(r.id == rid for r in recent_runs(limit=50))


# ── the migration ────────────────────────────────────────────────────────────


def test_ensure_schema_adds_columns_to_a_pre_migration_table(tmp_path: Path) -> None:
    """The live DB has 140k rows and no migration tooling. create_all will
    NOT alter it, so ensure_schema must issue the ALTER TABLEs itself."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE maintenancerecord (id INTEGER PRIMARY KEY, timestamp DATETIME, "
        "agent VARCHAR, action VARCHAR, status VARCHAR, log_output VARCHAR, duration_ms INTEGER)"
    )
    con.execute(
        "INSERT INTO maintenancerecord (timestamp, agent, action, status, log_output, duration_ms) "
        "VALUES ('2026-01-01 00:00:00', 'linux', 'dnf-upgrade', 'success', 'x', 1)"
    )
    con.commit()
    con.close()

    added = ensure_schema(db_path=db)
    assert {"trigger", "git_commit", "stderr_tail"} <= set(added)

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(maintenancerecord)")}
    assert _ADDED <= cols
    assert "stderr_tail" in cols
    assert con.execute("SELECT count(*) FROM maintenancerecord").fetchone()[0] == 1
    con.close()


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    """Running it again must change nothing — and it must have something to skip.

    Against an empty database the very first call already returns nothing, because
    `create_all` owns the table, so the assertion would hold whether or not the
    function did anything at all. So this starts from the pre-migration table, where
    the first call has seven columns of real work to do and the second has none.
    """
    db = _pre_migration_db(tmp_path / "legacy.db")
    added = ensure_schema(db_path=db)
    assert set(added) == _ADDED
    # The count as well as the names, so dropping one from the migration is a failure
    # here rather than a column the host turns out not to have.
    assert len(added) == 7, sorted(added)
    assert "stderr_tail" in added
    assert ensure_schema(db_path=db) == []
    assert ensure_schema(db_path=db) == []
    assert _ADDED <= _columns(db)


def test_ensure_schema_adds_only_what_a_partly_migrated_table_is_missing(tmp_path: Path) -> None:
    """A host already carrying the earlier columns gets just the new one, safely.

    This is not a hypothetical state: a database migrated by an earlier build is
    already in it, and so is any host that took the earlier six-column migration.
    So the migration has to be incremental rather than all-or-nothing, and its second
    pass over a populated table has to be as non-destructive as its first.
    """
    db = _pre_migration_db(tmp_path / "partial.db")
    assert set(ensure_schema(db_path=db)) == _ADDED

    # Back to "migrated except for the newest column", which is what the table looks
    # like on a host that has not seen this change yet.
    with closing(sqlite3.connect(db)) as con:
        con.execute("ALTER TABLE maintenancerecord DROP COLUMN stderr_tail")
        con.commit()

    before = _read(db, _LEGACY_COLUMNS)
    assert ensure_schema(db_path=db) == ["stderr_tail"]
    assert _read(db, _LEGACY_COLUMNS) == before
    assert _read(db, "stderr_tail") == [(None,)] * _LEGACY_ROWS


def test_ensure_schema_indexes_the_run_history_read_path(tmp_path: Path) -> None:
    """`ORDER BY timestamp DESC LIMIT n` over 140,385 rows is a full scan without this.

    And `recent_runs(job=...)` filters on `action`, so that column needs one too. Both
    are on the read path an API or TUI polls, and both would otherwise scan and sort
    the whole table on every call.
    """
    db = _pre_migration_db(tmp_path / "indexed.db")
    ensure_schema(db_path=db)
    names = _indexes(db)
    assert "ix_maintenancerecord_timestamp" in names
    assert "ix_maintenancerecord_action" in names


def test_ensure_schema_is_idempotent_with_the_indexes(tmp_path: Path) -> None:
    db = _pre_migration_db(tmp_path / "indexed.db")
    ensure_schema(db_path=db)
    before = _indexes(db)
    assert ensure_schema(db_path=db) == []
    assert ensure_schema(db_path=db) == []
    assert _indexes(db) == before, "a later pass added a second index under another name"


def test_a_fresh_database_gets_the_same_indexes_from_create_all() -> None:
    """The model and the migration have to agree on the names.

    `create_all` builds these from `index=True` and `ensure_schema` issues the SQL
    itself, so a rename on one side alone would leave a migrated database and a fresh
    one holding the same index under two names — and `IF NOT EXISTS` would then add a
    second copy rather than skip. This reads the suite's own database, which
    `create_all` built.
    """
    names = _indexes(db_module.DB_FILE)
    assert "ix_maintenancerecord_timestamp" in names
    assert "ix_maintenancerecord_action" in names


def test_ensure_schema_survives_another_process_migrating_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four subsystems call `init_db()`, so two can migrate at the same time.

    Both read the column list, both conclude `trigger` is missing, and both issue the
    same `ALTER`. The loser used to take `duplicate column name` as an unhandled error
    out of `init_db()` — a hard startup failure on the live database, which is the one
    outcome this migration exists to make impossible.
    """

    # Captured before the patch below, so the competing connection is a real one
    # rather than a second scripted double that would recurse into itself.
    real_connect = sqlite3.connect

    def competing_migration(_: sqlite3.Connection) -> None:
        with closing(real_connect(tmp_path / "raced.db")) as other:
            other.execute("ALTER TABLE maintenancerecord ADD COLUMN trigger TEXT NOT NULL DEFAULT ''")
            other.commit()

    db = _pre_migration_db(tmp_path / "raced.db")
    with _scripted_connection(monkeypatch, competing_migration):
        added = ensure_schema(db_path=db)

    assert "trigger" not in added, "another process added that column, not this call"
    assert set(added) == _ADDED - {"trigger"}
    assert _ADDED <= _columns(db), "the losing process must leave the column in place"
    assert ensure_schema(db_path=db) == [], "and still be idempotent afterwards"


def test_ensure_schema_surfaces_a_database_it_cannot_migrate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A locked or corrupt database is not a lost race, and must still fail loudly.

    Recovering from every `OperationalError` would turn a real failure into a quiet
    success — the schema half-migrated, and an entry point reporting that it started.
    """

    def locked(_: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("database is locked")

    db = _pre_migration_db(tmp_path / "locked.db")
    with _scripted_connection(monkeypatch, locked), pytest.raises(sqlite3.OperationalError, match="locked"):
        ensure_schema(db_path=db)


def test_ensure_schema_preserves_existing_rows_and_their_values(tmp_path: Path) -> None:
    """The property the 140,385 rows on the host depend on.

    Not the count — the values. Every column that existed before the migration must
    come back byte for byte, because a migration that quietly normalised a
    `log_output` would be a data-loss bug that counting rows cannot see. And the seven
    new columns must read as the defaults their `ALTER` declared, since that is what
    every pre-existing row now holds.
    """
    db = _pre_migration_db(tmp_path / "legacy.db")
    before = _read(db, _LEGACY_COLUMNS)
    assert len(before) == _LEGACY_ROWS

    assert set(ensure_schema(db_path=db)) == _ADDED

    assert _read(db, _LEGACY_COLUMNS) == before
    # Every row reading back as one tuple means every row took the default its own
    # `ALTER` declared: '' for the strings, 0 for the flag, NULL for the three
    # nullable ones — including stderr_tail, which a run from before the column
    # existed cannot have had any of.
    with_defaults = _read(db, "trigger, exit_code, resolved_path, git_commit, git_dirty, payload, stderr_tail")
    assert with_defaults == [("", None, "", "", 0, None, None)] * _LEGACY_ROWS


def test_ensure_schema_ignores_a_database_with_no_table(tmp_path: Path) -> None:
    """A fresh database is `create_all`'s to make, already carrying every column.

    Claiming seven columns here would report a migration that never happened, and a
    caller printing that would tell an operator a table was altered when it was not.
    """
    with closing(sqlite3.connect(tmp_path / "empty.db")):
        pass
    assert ensure_schema(db_path=tmp_path / "empty.db") == []


def test_init_db_runs_the_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring: `create_all` alone leaves an existing table untouched.

    Without this call the seven columns are declared but never added to the host's
    database, and every query against it raises `OperationalError: no such column:
    maintenancerecord.trigger` — so the call is pinned here rather than discovered
    in production.
    """
    calls: list[object] = []
    monkeypatch.setattr(db_module, "ensure_schema", lambda: calls.append("called"))
    init_db()
    assert calls == ["called"]


# ── findings ─────────────────────────────────────────────────────────────────


def test_findings_in_a_payload_become_security_incidents() -> None:
    """Spec 6.3: bash findings feed the same store the Python agent uses,
    so /api/security/summary and the exporter see both producers.

    Recorded unresolved — `resolved=False` — because a finding a scan just produced
    is open exposure by definition. Marking it resolved on the way in would hide
    the very exposure the summary exists to report.
    """
    save_run(
        _env(
            payload={
                "findings": [
                    {"severity": "high", "rule": "backup-stale", "message": "last dump is 9 days old"},
                    {"severity": "low", "rule": "log-noise", "message": "…"},
                ]
            }
        )
    )
    incidents = get_security_incidents(resolved=False, limit=200)
    assert {"backup-stale", "log-noise"} <= {i.rule_id for i in incidents}
    assert next(i for i in incidents if i.rule_id == "backup-stale").severity == "high"
    assert next(i for i in incidents if i.rule_id == "backup-stale").resolved is False


def test_run_without_findings_creates_no_incidents() -> None:
    before = len(get_security_incidents())
    save_run(_env())
    assert len(get_security_incidents()) == before


def test_a_malformed_finding_costs_the_finding_not_the_run() -> None:
    """A payload is optional extra written by the code a job runs.

    Nothing in it may cost the record of a run that actually happened: the run is
    recorded, the entries that make sense are kept with their documented defaults,
    and the ones that do not are dropped rather than raised over.
    """
    rid = save_run(
        _env(
            payload={
                "findings": [
                    "not a finding",
                    {"rule": "no-severity"},
                    {"severity": "high", "rule": "no-message"},
                ]
            }
        )
    )
    assert any(r.id == rid for r in recent_runs(limit=200))

    incidents = get_security_incidents(resolved=False, limit=200)
    by_rule = {i.rule_id: i for i in incidents}
    assert {"no-severity", "no-message"} <= set(by_rule)
    assert by_rule["no-severity"].severity == "medium"
    assert by_rule["no-message"].message == ""


def test_findings_that_are_not_a_list_are_ignored() -> None:
    """`findings: 5` is uniterable, so it must be skipped rather than raised on."""
    rid = save_run(_env(payload={"findings": 5}))
    assert any(r.id == rid for r in recent_runs(limit=200))


def test_a_repeating_finding_keeps_one_row_and_its_first_seen_time() -> None:
    """A standing condition must not append a row, nor lose track of how long it stood.

    `get_security_summary` publishes `oldest_unresolved_timestamp` and the Prometheus
    exporter consumes it to report how long the oldest unresolved condition has been
    standing. Refreshing that on every observation would make a nine-day-old backup
    problem report as freshly seen, so the fix for unbounded growth must not buy its
    deduplication by making a chronic condition look new.
    """
    first_seen = datetime.now(UTC) - timedelta(days=9)
    save_run(
        _env(
            job="dedup/one",
            payload={"findings": [{"severity": "high", "rule": "repeats", "message": "9 days"}]},
            started_at=first_seen,
        )
    )
    rows = _incidents("repeats")
    assert len(rows) == 1
    assert rows[0].message == "9 days"
    assert rows[0].severity == "high"
    assert _aware_utc(rows[0].timestamp) == first_seen

    save_run(
        _env(
            job="dedup/one",
            payload={"findings": [{"severity": "medium", "rule": "repeats", "message": "12 days"}]},
            started_at=first_seen + timedelta(days=3),
        )
    )

    rows = _incidents("repeats")
    assert len(rows) == 1, f"a second open row was appended: {rows}"
    # The detail follows the latest observation...
    assert rows[0].message == "12 days"
    assert rows[0].severity == "medium"
    # ...while the age the summary publishes stays the age of the condition.
    assert _aware_utc(rows[0].timestamp) == first_seen, "first-seen time was refreshed"


def test_first_seen_survives_many_re_observations() -> None:
    """Repeated runs must not slowly walk a chronic condition's age back towards zero.

    One refresh would be a rounding error; a job reporting every five minutes would
    reset it a thousand times a day, and the published age would be the age of the last
    observation rather than of the problem.
    """
    first_seen = datetime.now(UTC) - timedelta(days=9)
    save_run(
        _env(
            job="dedup/many",
            payload={"findings": [{"severity": "high", "rule": "chronic", "message": "9 days"}]},
            started_at=first_seen,
        )
    )
    for hour in range(1, 6):
        save_run(
            _env(
                job="dedup/many",
                payload={"findings": [{"severity": "high", "rule": "chronic", "message": f"{9 + hour} days"}]},
                started_at=first_seen + timedelta(hours=hour),
            )
        )

    rows = _incidents("chronic")
    assert len(rows) == 1
    assert rows[0].message == "14 days", "the latest detail should win"
    assert _aware_utc(rows[0].timestamp) == first_seen


def test_a_reoccurrence_after_resolution_opens_a_fresh_row() -> None:
    """A finding that was resolved and came back is a real re-occurrence.

    Merging into the resolved row would leave it continuously open, erasing both that
    it had been dealt with and that the problem came back.
    """
    save_run(_env(job="dedup/two", payload={"findings": [{"severity": "high", "rule": "returns", "message": "first"}]}))
    _resolve("returns")

    save_run(
        _env(job="dedup/two", payload={"findings": [{"severity": "high", "rule": "returns", "message": "second"}]})
    )

    assert [r.message for r in _incidents("returns")] == ["second"]
    assert [r.message for r in _incidents("returns", resolved=True)] == ["first"]


def test_two_findings_for_one_rule_in_one_payload_collapse_onto_one_row() -> None:
    """A single payload must not reintroduce the duplication the upsert removes."""
    save_run(
        _env(
            job="dedup/three",
            payload={
                "findings": [
                    {"severity": "low", "rule": "twice", "message": "first"},
                    {"severity": "high", "rule": "twice", "message": "second"},
                ]
            },
        )
    )
    rows = _incidents("twice")
    assert len(rows) == 1
    assert rows[0].message == "second"
    assert rows[0].severity == "high"


def test_a_run_and_its_findings_are_written_in_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the findings half fails, the run record must not be left behind.

    The two are written in one session so they cannot diverge: a record of a run
    whose findings never landed understates the exposure for exactly as long as
    nothing notices, which is the failure this store exists to prevent.

    Faulted at the mapping step because that is the only place the two halves meet:
    a payload is built from JSON, so nothing in it can otherwise make the second half
    of the write fail, and the property would be untestable rather than merely true.
    """

    def explode(payload: dict[str, Any] | None) -> list[SecurityIncident]:
        raise ValueError("findings half-written")

    monkeypatch.setattr(db_module, "_incidents_from_payload", explode)
    before = len(recent_runs(limit=1000))
    with pytest.raises(ValueError, match="findings half-written"):
        save_run(_env(job="atomic/one", payload={"findings": [{"rule": "r"}]}))
    assert len(recent_runs(limit=1000)) == before
