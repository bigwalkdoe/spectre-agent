from datetime import UTC, datetime
from pathlib import Path
from typing import Generator

from sqlmodel import Field, Session, SQLModel, create_engine, select

# Define the database path in the user's home or local workspace directory
DB_DIR = Path.home() / ".config" / "spectre"
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
        stmt = select(Configuration).where(
            Configuration.key == key, Configuration.profile == profile
        )
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
        stmt = stmt.order_by(Report.timestamp.desc()).limit(limit)
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
        stmt = stmt.order_by(WorkflowRun.timestamp.desc()).limit(limit)
        return list(session.exec(stmt))


def save_decision(decision: Decision) -> None:
    with Session(engine) as session:
        session.add(decision)
        session.commit()


def get_decisions(limit: int = 50) -> list[Decision]:
    with Session(engine) as session:
        stmt = select(Decision).order_by(Decision.timestamp.desc()).limit(limit)
        return list(session.exec(stmt))


# ── New table helpers ─────────────────────────────────────────────────────


def save_machine(machine: Machine) -> None:
    with Session(engine) as session:
        session.add(machine)
        session.commit()


def get_machines() -> list[Machine]:
    with Session(engine) as session:
        stmt = select(Machine).order_by(Machine.last_seen.desc())
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
        stmt = stmt.order_by(AgentRecord.timestamp.desc()).limit(limit)
        return list(session.exec(stmt))


def save_plugin_record(record: PluginRecord) -> None:
    with Session(engine) as session:
        session.add(record)
        session.commit()


def get_plugin_records(limit: int = 50) -> list[PluginRecord]:
    with Session(engine) as session:
        stmt = select(PluginRecord).order_by(PluginRecord.timestamp.desc()).limit(limit)
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
        stmt = stmt.order_by(EventLog.timestamp.desc()).limit(limit)
        return list(session.exec(stmt))
