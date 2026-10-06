"""Tests for the run records dispatch writes, and for the migration that made room.

Two things are being pinned here, and the second is the one that could hurt a host.

A run record has to carry the provenance an operator needs to answer "which revision
of this checkout ran this, was the tree dirty, and what did the action say". The old
`maintenancerecord` had nowhere to put any of that, so a run recorded only that a job
succeeded — which is exactly the record that cannot be diagnosed after the fact.

That is also why the migration is the interesting half. The live
`~/.config/spectre/memory.db` is 28 MB with 140,385 rows and this repo has no Alembic,
so declaring the six columns is not enough: `SQLModel.metadata.create_all()` does not
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
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

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
) -> Envelope:
    return Envelope(
        job=job,
        trigger=trigger,
        started_at=datetime.now(UTC),
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
    already in it, and so is any host that took the previous six-column migration.
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


def test_ensure_schema_preserves_existing_rows_and_their_values(tmp_path: Path) -> None:
    """The property the 140,385 rows on the host depend on.

    Not the count — the values. Every column that existed before the migration must
    come back byte for byte, because a migration that quietly normalised a
    `log_output` would be a data-loss bug that counting rows cannot see. And the six
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

    Claiming six columns here would report a migration that never happened, and a
    caller printing that would tell an operator a table was altered when it was not.
    """
    with closing(sqlite3.connect(tmp_path / "empty.db")):
        pass
    assert ensure_schema(db_path=tmp_path / "empty.db") == []


def test_init_db_runs_the_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring: `create_all` alone leaves an existing table untouched.

    Without this call the six columns are declared but never added to the host's
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
