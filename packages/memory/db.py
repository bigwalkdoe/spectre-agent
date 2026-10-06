from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Generator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, desc, select

if TYPE_CHECKING:
    # Only the type is needed: an envelope is built by the dispatch layer and handed
    # in, so importing it for real would make this low-level store depend on the
    # package that consumes it — and on GitPython, which the resolver pulls in.
    from packages.dispatch.envelope import Envelope

# State lives in the user's config directory by default. SPECTRE_CONFIG_DIR
# overrides it so the test suite can run against a throwaway tree instead of
# writing into the real ~/.config/spectre/memory.db.
DB_DIR = Path(os.environ.get("SPECTRE_CONFIG_DIR") or (Path.home() / ".config" / "spectre")).expanduser()
DB_FILE = DB_DIR / "memory.db"

# Create directory if it does not exist
DB_DIR.mkdir(parents=True, exist_ok=True)

sqlite_url = f"sqlite:///{DB_FILE}"
engine = create_engine(sqlite_url, echo=False, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _configure_connection(dbapi_connection: sqlite3.Connection, connection_record: object) -> None:
    """Put every new SQLite connection into WAL mode with a lock timeout.

    Spectre writes to this database from more than one process at a time — two
    five-minute exporters, a cron job, a hand-run — and SQLite's default rollback
    journal takes an exclusive lock for the whole database on every write, so
    concurrent runs serialise at best and fail with `database is locked` at worst.
    WAL lets readers work while one writer commits, which is the shape Spectre
    actually has. The busy timeout then turns the remaining writer-writer collision
    into a short wait rather than an error.

    On the "connect" event rather than once at import, because both settings belong
    to a connection: WAL is durable once the database has it, but the timeout is
    per connection, so a hook is what makes it true for every pooled connection
    rather than only the one that happened to be open when this module loaded.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


class SystemMetric(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    cpu_percent: float
    memory_percent: float
    swap_percent: float
    disk_percent: float
    battery_percent: float | None = None
    temperature_c: float | None = None


class MaintenanceRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        # Indexed because this is the run-history read path: `recent_runs` asks for
        # the newest rows and an API or TUI polls it, so an unindexed ORDER BY would
        # scan and sort the whole table — 140,385 rows on the host's database — per
        # call. `SystemMetric.timestamp` has always been indexed for the same reason.
        index=True,
    )
    agent: str  # e.g., "linux", "security"
    action: str = Field(index=True)  # e.g., "dnf-upgrade", "flatpak-cleanup"
    status: str  # "success", "failed"
    log_output: str
    duration_ms: int
    # What a dispatched run knows about itself beyond "it finished": what triggered
    # it, whether it got as far as an exit code, and which revision of the checkout
    # ran. Every one has a default, so the agents that predate dispatch keep
    # constructing records without naming any of them.
    trigger: str = "legacy"
    # NULL rather than 0 for a run that never reached an exit code — a refused or
    # missing action has no code, and 0 would read back as a success.
    exit_code: int | None = None
    resolved_path: str = ""
    git_commit: str = ""
    git_dirty: bool = False
    # The envelope's structured payload as JSON, when the action emitted one.
    payload: str | None = None
    # The action's stderr tail, which is the half a failure usually states itself in.
    # Its own column rather than appended to `log_output`, so a record can carry both
    # streams and the code already reading stdout out of `log_output` is undisturbed.
    # Ordered to match `_DISPATCH_COLUMNS`, which is append-only.
    stderr_tail: str | None = None


class SecurityIncident(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    severity: str  # "low", "medium", "high", "critical"
    rule_id: str
    message: str
    resolved: bool = False
    resolution_notes: str | None = None


class KVStore(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str


class Configuration(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    key: str = Field(index=True)
    value: str
    profile: str = "default"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Report(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    report_type: str  # "daily", "weekly", "security", "maintenance"
    content: str
    format: str  # "markdown", "json"


class WorkflowRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    workflow: str
    status: str  # "success", "failed", "partial"
    duration_ms: int
    details: str  # JSON string


class Decision(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    context: str
    decision: str
    rationale: str
    outcome: str | None = None


class Machine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    hostname: str = Field(index=True)
    platform: str
    python_version: str
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata_json: str = "{}"


class AgentRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_name: str = Field(index=True)
    action: str
    status: str
    input_json: str = "{}"
    output_json: str = "{}"
    duration_ms: int = 0


class PluginRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    name: str = Field(index=True)
    version: str = ""
    enabled: bool = True
    permissions: str = "[]"
    status: str = "active"


class EventLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    event_type: str = Field(index=True)
    source: str = ""
    data_json: str = "{}"
    severity: str = "info"


# The provenance columns dispatch added to `maintenancerecord`, each with the exact
# `ALTER` that adds it. The declarations live here rather than being derived from the
# model because SQLite cannot add a NOT NULL column to a populated table without
# being told a default, and this is the only place that can name it: a column added
# to the model without a line here fails at query time on any host that already has
# the table. `exit_code`, `payload` and `stderr_tail` are nullable, so the rows
# already on a host satisfy them as NULL — an exit code a run never earned, no
# payload at all, and no stderr from an action that predates the column.
#
# Appended to, never reordered: a host that has already migrated the earlier columns
# picks up only what is still missing, which is what makes adding one safe after the
# fact rather than a rewrite of the list.
_DISPATCH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("trigger", "TEXT NOT NULL DEFAULT ''"),
    ("exit_code", "INTEGER"),
    ("resolved_path", "TEXT NOT NULL DEFAULT ''"),
    ("git_commit", "TEXT NOT NULL DEFAULT ''"),
    ("git_dirty", "INTEGER NOT NULL DEFAULT 0"),
    ("payload", "TEXT"),
    ("stderr_tail", "TEXT"),
)

# The indexes `recent_runs` needs, named exactly as SQLAlchemy names the ones it
# creates for the `index=True` fields above, so a database built by `create_all` and
# one migrated by this function arrive at the same names and `IF NOT EXISTS` makes
# the second pass a no-op rather than a duplicate index under a second name.
#
# `CREATE INDEX` is in the same additive class as the `ALTER TABLE`s above — nothing
# is rewritten, dropped or deleted, and the rows are untouched. It is also the one
# statement here that has to read the whole table, once, on the first run against a
# database that did not already have it.
_RUN_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_maintenancerecord_timestamp ON maintenancerecord (timestamp)",
    "CREATE INDEX IF NOT EXISTS ix_maintenancerecord_action ON maintenancerecord (action)",
)

# The one table this migration touches, so the statements above cannot disagree with
# the `PRAGMA` below about which table they are reading.
_TABLE = "maintenancerecord"


def _columns_in(connection: sqlite3.Connection) -> set[str]:
    """The column names `connection` reports for `_TABLE`, empty if there is no table.

    Re-read rather than cached, because the second read is what tells a lost migration
    race apart from a real failure: by then the column may genuinely be there.
    """
    return {row[1] for row in connection.execute(f"PRAGMA table_info({_TABLE})")}


def ensure_schema(db_path: Path | None = None) -> list[str]:
    """Add the dispatch provenance columns to an existing `maintenancerecord`.

    **`SQLModel.metadata.create_all()` cannot do this.** It creates tables that are
    missing and leaves existing ones exactly as they are, with no `ALTER` step, and
    this project has no Alembic. So on a host that already has the seven-column
    table — and the live `~/.config/spectre/memory.db` is 28 MB with 140,385 rows in
    it — declaring the seven new fields on the model is not enough: the model and the
    table then disagree, and every query against that database raises
    `OperationalError: no such column: maintenancerecord.trigger` with nothing to
    say why. This issues the `ALTER TABLE`s the ORM will not.

    Raw `sqlite3` rather than the engine, because it has to work against a path
    whatever state the engine is in, and because a migration failure should read as
    a `sqlite3` error instead of arriving wrapped in a SQLAlchemy stack trace.

    It only ever adds a column or an index. No table is rebuilt, dropped or emptied, so
    the rows already on the host are untouched and come back reading the default each
    `ALTER` declared — which is what makes this safe to run without a backup.

    Also creates the two indexes `recent_runs` reads through. They are named as
    SQLAlchemy names the ones `create_all` builds from `index=True`, so a fresh
    database and a migrated one agree and `IF NOT EXISTS` makes every pass after the
    first a no-op. Creating an index on an existing table is the one statement here
    that reads the whole table, and it does so once.

    Idempotent, and safe on every `init_db()`: it reads the columns that exist and
    adds only what is missing. A database with no `maintenancerecord` yet returns
    nothing, because `create_all` is about to make that table with every column
    already in it, and reporting seven names there would announce a migration that did
    not happen.

    **Safe against two processes migrating at once.** Four subsystems call `init_db()`
    and the WAL hook's own rationale is multi-process access, so two can read the same
    column list, both conclude a column is missing, and both issue the same `ALTER` —
    where the loser would otherwise take `duplicate column name` as an unhandled error
    out of `init_db()` and fail that entry point on the live database. A column that
    turns out to be there anyway is treated as done, because it is. Any other
    `OperationalError` — a locked or corrupt database — is still raised, since calling
    that a race would be exactly the kind of quiet success this task exists to prevent.

    Returns the column names **this call** added, which is empty once the schema is
    current. A column another process added in the gap is not reported as ours, though
    it is left in place. Indexes are ensured but not reported: they are not columns,
    and after the first pass there is nothing to report anyway.
    """
    target = DB_FILE if db_path is None else Path(db_path)
    with closing(sqlite3.connect(target)) as connection:
        present = _columns_in(connection)
        if not present:
            return []
        # Identifiers come from this module's own constants, never from a caller.
        added: list[str] = []
        for name, declaration in _DISPATCH_COLUMNS:
            if name in present:
                continue
            try:
                connection.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {declaration}")
            except sqlite3.OperationalError:
                # Re-read rather than pattern-match the message: what distinguishes
                # the lost race is the column being there now, not the wording.
                if name not in _columns_in(connection):
                    raise
                continue
            added.append(name)
        for statement in _RUN_INDEXES:
            connection.execute(statement)
        connection.commit()
    return added


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # create_all is done and the table a host already had is still the old one, so
    # the migration is what actually gives it the provenance columns. Without this
    # line every query on such a host fails with `no such column`.
    ensure_schema()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


# DB helper functions
def save_metric(metric: SystemMetric) -> None:
    with Session(engine) as session:
        session.add(metric)
        session.commit()


def save_maintenance_record(record: MaintenanceRecord) -> None:
    with Session(engine) as session:
        session.add(record)
        session.commit()


def _incidents_from_payload(payload: dict[str, Any] | None) -> list[SecurityIncident]:
    """The `findings` in a payload, as unresolved `SecurityIncident` rows.

    A payload is written by the code a dispatched job runs, so it is untrusted input
    on the same footing as that action's stdout: an entry that is not a dict is
    dropped and a missing field takes a default rather than raising, because a
    malformed finding must never cost the record of a run that actually happened.

    Every finding is stored unresolved, which is what a scan reporting one means — a
    severity is stored as given and defaults to `"medium"`, since a finding with no
    severity is still a finding and dropping it would under-report rather than over.
    """
    if payload is None:
        return []
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return []
    incidents: list[SecurityIncident] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        incidents.append(
            SecurityIncident(
                severity=str(finding.get("severity") or "medium"),
                rule_id=str(finding.get("rule") or ""),
                message=str(finding.get("message") or ""),
                resolved=False,
            )
        )
    return incidents


def _incident_with_rule(session: Session, rule_id: str, resolved: bool = False) -> SecurityIncident | None:
    """The incident for `rule_id` in the given resolution state, if there is one.

    Open only by default, and `_store_findings` asks for the open one: a resolved row
    is a finding that was dealt with, and merging a re-occurrence into it would erase
    both the resolution and the fact that the problem came back. Compared against a
    named value rather than a literal for the same reason `get_security_incidents`
    takes `resolved` as an argument — `== False` is both a lint error and, to a type
    checker, a comparison on a plain `bool` rather than on a column.
    """
    return session.exec(
        select(SecurityIncident).where(
            SecurityIncident.rule_id == rule_id,
            SecurityIncident.resolved == resolved,
        )
    ).first()


def _store_findings(session: Session, payload: dict[str, Any] | None, observed_at: datetime) -> None:
    """Record a payload's findings, keeping one open row per `rule_id`.

    A condition that persists — `backup-stale` reporting a nine-day-old dump on every
    run — must not append a fresh open incident every time it is observed.
    `get_security_summary` counts unresolved **rows**, so appending would inflate
    `unresolved_total` in proportion to how often the job runs, and once open rows
    pass its own thousand-row limit the summary would truncate the newest of them:
    recurring dispatch findings would push genuine security-agent findings out of the
    window and the endpoint would report the truncated set as if it were the whole. So
    a finding whose rule already has an open row refreshes that row — the same standing
    exposure, seen again — rather than adding a second.

    The upsert is also what makes §6.3's "the same store the Python agent uses" true:
    a store holding a duplicate of every recurring finding is not a shared store.

    Two findings for one rule inside a single payload collapse onto the same row, so a
    payload cannot reintroduce the duplication it is being deduplicated for. They are
    held in `pending` rather than relying on the session to flush and see its own
    pending rows, so that collapse does not depend on autoflush timing.
    """
    pending: dict[str, SecurityIncident] = {}
    for incident in _incidents_from_payload(payload):
        open_row = pending.get(incident.rule_id) or _incident_with_rule(session, incident.rule_id)
        if open_row is None:
            open_row = incident
            pending[incident.rule_id] = incident
            session.add(open_row)
        open_row.timestamp = observed_at
        open_row.message = incident.message
        open_row.severity = incident.severity


def _json_payload(payload: dict[str, Any] | None) -> str | None:
    """A payload as JSON, or None if it cannot be encoded at all.

    `default=str` covers what a payload can legitimately carry that JSON cannot — a
    `datetime`, a `Path`, a `set` from any Python producer — and keeps the run
    recorded, where raising here would drop the only evidence that it happened.

    The fallback for what `default` still cannot save, a self-referential structure,
    stores nothing rather than raising: a record with no payload is still a record,
    and the raw output stays in the log tails.
    """
    if payload is None:
        return None
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return None


def save_run(envelope: Envelope, agent: str = "dispatch") -> int:
    """Store one dispatched run as a `MaintenanceRecord`, with its findings.

    `action` is the job name and `agent` records which subsystem wrote the row, so a
    dispatched run and one an agent produced stay tellable apart in the one table
    both use without either being able to overwrite the other.

    The record is stamped with the envelope's `started_at` rather than the moment of
    writing, because the envelope already knows when the run began and the two differ
    by exactly the run's own duration — which is what a timed-out action has, and
    dating it to when its result was finally written would misdate the one run whose
    timing is the reason anyone is reading the list. Its findings are stamped the
    same way, since a finding was observed when the run that reported it happened.

    The row and any findings go in one session and one commit, so a run whose findings
    could not be written cannot be left behind claiming it had none: either the run
    and its findings are both stored, or neither is. Everything that can fail while
    building the row happens inside that session, so no failure can precede the record.

    `log_output` keeps the stdout tail, and the stderr tail goes to its own column
    rather than being appended to that one: stdout is what other code already reads
    out of `log_output`, and a failed action's diagnostic is usually on stderr. A
    record that kept one stream and dropped the other would still look complete, which
    is exactly how that loss goes unnoticed until someone needs the missing half.

    Returns the new row's id.
    """
    with Session(engine) as session:
        record = MaintenanceRecord(
            timestamp=envelope.started_at,
            agent=agent,
            action=envelope.job,
            status=envelope.status.value,
            log_output=envelope.stdout_tail,
            duration_ms=envelope.duration_ms,
            trigger=envelope.trigger,
            exit_code=envelope.exit_code,
            resolved_path=envelope.resolved_path,
            git_commit=envelope.git_commit,
            git_dirty=envelope.git_dirty,
            stderr_tail=envelope.stderr_tail,
            payload=_json_payload(envelope.payload),
        )
        session.add(record)
        _store_findings(session, envelope.payload, envelope.started_at)
        session.commit()
        # A raise rather than an `assert`, which `python -O` strips — after which
        # this would quietly return None from a function that promises an int.
        if record.id is None:
            raise RuntimeError("a committed MaintenanceRecord has an id")
        return record.id


def recent_runs(limit: int = 50, job: str | None = None) -> list[MaintenanceRecord]:
    """The newest run records, optionally only those of one job.

    Newest first, so a caller that only wants the current state of a job can read the
    first row instead of the whole history. `job` is the job name as dispatched, which
    is what lands in `action` — a name rather than the registry entry, so a record
    stays readable after the job is renamed or removed.
    """
    with Session(engine) as session:
        statement = select(MaintenanceRecord).order_by(desc(MaintenanceRecord.timestamp))
        if job:
            statement = statement.where(MaintenanceRecord.action == job)
        return list(session.exec(statement.limit(limit)).all())


def save_security_incident(incident: SecurityIncident) -> None:
    with Session(engine) as session:
        session.add(incident)
        session.commit()


def get_security_incidents(
    resolved: bool | None = None,
    severity: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[SecurityIncident]:
    """Return recorded incidents, newest first.

    SecurityIncident was write-only until this getter was added: every other
    persisted model had a reader, so findings could be recorded but never
    retrieved, counted or alerted on. `resolved=None` means "either", which is
    what a caller counting current exposure wants; pass True or False to filter.
    """
    with Session(engine) as session:
        statement = select(SecurityIncident).order_by(desc(SecurityIncident.timestamp))
        if resolved is not None:
            statement = statement.where(SecurityIncident.resolved == resolved)
        if severity is not None:
            statement = statement.where(SecurityIncident.severity == severity)
        if since is not None:
            statement = statement.where(SecurityIncident.timestamp >= since)
        return list(session.exec(statement.limit(limit)).all())


def _as_utc(value: datetime | None) -> datetime | None:
    """Re-attach UTC to a timestamp read back from SQLite.

    SQLite has no timezone-aware datetime type, so every timestamp comes back
    naive even though it was written as an aware UTC value. A monitoring consumer
    that parses this and compares it with an aware `now()` gets
    "can't subtract offset-naive and offset-aware datetimes", so the timezone is
    restored here rather than left for every caller to rediscover.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def get_security_summary() -> dict[str, object]:
    """Aggregate current security exposure for monitoring.

    `last_scan_timestamp` is derived from recorded data, never from the moment
    this function is called. It is the newest maintenance record for the security
    agent, so a summary served from a stale database reports a stale scan rather
    than claiming a scan just happened. Timestamps are returned as aware UTC
    ISO-8601 strings for the same reason as `_as_utc`.
    """
    unresolved = get_security_incidents(resolved=False, limit=1000)
    by_severity: dict[str, int] = {}
    oldest: datetime | None = None
    for incident in unresolved:
        by_severity[incident.severity] = by_severity.get(incident.severity, 0) + 1
        if oldest is None or incident.timestamp < oldest:
            oldest = incident.timestamp

    last_scan: datetime | None = None
    with Session(engine) as session:
        statement = (
            select(MaintenanceRecord)
            .where(MaintenanceRecord.agent == "security")
            .order_by(desc(MaintenanceRecord.timestamp))
            .limit(1)
        )
        record = session.exec(statement).first()
        if record is not None:
            last_scan = record.timestamp

    oldest_utc = _as_utc(oldest)
    last_scan_utc = _as_utc(last_scan)
    return {
        "unresolved_total": len(unresolved),
        "unresolved_by_severity": by_severity,
        "oldest_unresolved_timestamp": oldest_utc.isoformat() if oldest_utc else None,
        "last_scan_timestamp": last_scan_utc.isoformat() if last_scan_utc else None,
        "has_ever_scanned": last_scan is not None,
    }


def get_kv(key: str, default: str = "") -> str:
    with Session(engine) as session:
        obj = session.get(KVStore, key)
        return obj.value if obj else default


def set_kv(key: str, value: str) -> None:
    with Session(engine) as session:
        obj = session.get(KVStore, key)
        if obj:
            obj.value = value
        else:
            obj = KVStore(key=key, value=value)
        session.add(obj)
        session.commit()


def save_configuration(config: Configuration) -> None:
    with Session(engine) as session:
        session.add(config)
        session.commit()


def get_configuration(key: str, profile: str = "default") -> str | None:
    with Session(engine) as session:
        stmt = select(Configuration).where(Configuration.key == key, Configuration.profile == profile)
        result = session.exec(stmt).first()
        return result.value if result else None


def save_report(report: Report) -> None:
    with Session(engine) as session:
        session.add(report)
        session.commit()


def get_reports(report_type: str | None = None, limit: int = 50) -> list[Report]:
    with Session(engine) as session:
        stmt = select(Report)
        if report_type:
            stmt = stmt.where(Report.report_type == report_type)
        stmt = stmt.order_by(desc(Report.timestamp)).limit(limit)
        return list(session.exec(stmt))


def save_workflow_run(run: WorkflowRun) -> None:
    with Session(engine) as session:
        session.add(run)
        session.commit()


def get_workflow_runs(workflow: str | None = None, limit: int = 50) -> list[WorkflowRun]:
    with Session(engine) as session:
        stmt = select(WorkflowRun)
        if workflow:
            stmt = stmt.where(WorkflowRun.workflow == workflow)
        stmt = stmt.order_by(desc(WorkflowRun.timestamp)).limit(limit)
        return list(session.exec(stmt))


def save_decision(decision: Decision) -> None:
    with Session(engine) as session:
        session.add(decision)
        session.commit()


def get_decisions(limit: int = 50) -> list[Decision]:
    with Session(engine) as session:
        stmt = select(Decision).order_by(desc(Decision.timestamp)).limit(limit)
        return list(session.exec(stmt))


# ── New table helpers ─────────────────────────────────────────────────────


def save_machine(machine: Machine) -> None:
    with Session(engine) as session:
        session.add(machine)
        session.commit()


def get_machines() -> list[Machine]:
    with Session(engine) as session:
        stmt = select(Machine).order_by(desc(Machine.last_seen))
        return list(session.exec(stmt))


def save_agent_record(record: AgentRecord) -> None:
    with Session(engine) as session:
        session.add(record)
        session.commit()


def get_agent_records(agent_name: str | None = None, limit: int = 50) -> list[AgentRecord]:
    with Session(engine) as session:
        stmt = select(AgentRecord)
        if agent_name:
            stmt = stmt.where(AgentRecord.agent_name == agent_name)
        stmt = stmt.order_by(desc(AgentRecord.timestamp)).limit(limit)
        return list(session.exec(stmt))


def save_plugin_record(record: PluginRecord) -> None:
    with Session(engine) as session:
        session.add(record)
        session.commit()


def get_plugin_records(limit: int = 50) -> list[PluginRecord]:
    with Session(engine) as session:
        stmt = select(PluginRecord).order_by(desc(PluginRecord.timestamp)).limit(limit)
        return list(session.exec(stmt))


def save_event(event: EventLog) -> None:
    with Session(engine) as session:
        session.add(event)
        session.commit()


def get_events(event_type: str | None = None, limit: int = 100) -> list[EventLog]:
    with Session(engine) as session:
        stmt = select(EventLog)
        if event_type:
            stmt = stmt.where(EventLog.event_type == event_type)
        stmt = stmt.order_by(desc(EventLog.timestamp)).limit(limit)
        return list(session.exec(stmt))
