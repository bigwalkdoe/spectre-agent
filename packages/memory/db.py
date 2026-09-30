import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine, desc, select

# State lives in the user's config directory by default. SPECTRE_CONFIG_DIR
# overrides it so the test suite can run against a throwaway tree instead of
# writing into the real ~/.config/spectre/memory.db.
DB_DIR = Path(os.environ.get("SPECTRE_CONFIG_DIR") or (Path.home() / ".config" / "spectre")).expanduser()
DB_FILE = DB_DIR / "memory.db"

# Create directory if it does not exist
DB_DIR.mkdir(parents=True, exist_ok=True)

sqlite_url = f"sqlite:///{DB_FILE}"
engine = create_engine(sqlite_url, echo=False, connect_args={"check_same_thread": False})


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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent: str  # e.g., "linux", "security"
    action: str  # e.g., "dnf-upgrade", "flatpak-cleanup"
    status: str  # "success", "failed"
    log_output: str
    duration_ms: int


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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


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
