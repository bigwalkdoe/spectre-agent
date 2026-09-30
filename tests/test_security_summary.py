"""Tests for security incident retrieval and the monitoring summary.

Two properties matter more than the counting itself:

1. `SecurityIncident` was write-only. Findings could be recorded but never read
   back, so nothing could count or alert on them.
2. `get_security_summary` must never invent a scan time. The monitoring suite
   publishes `last_scan_timestamp`, and an earlier exporter set it to the current
   time on every poll, which asserted that a scan had just completed when none
   had. These tests pin it to recorded data only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.memory.db import (
    MaintenanceRecord,
    SecurityIncident,
    get_security_incidents,
    get_security_summary,
    save_maintenance_record,
    save_security_incident,
)


def _clear() -> None:
    """Start from an empty slate; the suite shares one database."""
    from sqlmodel import Session, select

    from packages.memory.db import engine

    with Session(engine) as session:
        for incident in session.exec(select(SecurityIncident)).all():
            session.delete(incident)
        for record in session.exec(select(MaintenanceRecord)).all():
            session.delete(record)
        session.commit()


def test_no_incidents_means_no_exposure() -> None:
    _clear()
    assert get_security_incidents() == []
    summary = get_security_summary()
    assert summary["unresolved_total"] == 0
    assert summary["unresolved_by_severity"] == {}
    assert summary["oldest_unresolved_timestamp"] is None


def test_summary_reports_no_scan_rather_than_fabricating_one() -> None:
    """The property that matters most for monitoring.

    With no security maintenance record, the summary must say it has never
    scanned. Returning the current time here would make a monitoring consumer
    report a fresh scan on every poll, forever, with nothing having run.
    """
    _clear()
    summary = get_security_summary()
    assert summary["has_ever_scanned"] is False
    assert summary["last_scan_timestamp"] is None


def test_last_scan_comes_from_the_record_not_from_now() -> None:
    _clear()
    recorded = datetime.now(UTC) - timedelta(days=3)
    save_maintenance_record(
        MaintenanceRecord(
            agent="security",
            action="selinux-audit",
            status="success",
            log_output="ok",
            duration_ms=5,
        )
    )
    summary = get_security_summary()
    assert summary["has_ever_scanned"] is True
    stamped = datetime.fromisoformat(str(summary["last_scan_timestamp"]))
    # Timezone-aware: SQLite returns naive datetimes, and a monitoring consumer
    # subtracting this from an aware now() would raise TypeError.
    assert stamped.tzinfo is not None
    # Close to the record we just wrote, and emphatically not a fresh reading.
    assert abs((datetime.now(UTC) - stamped).total_seconds()) < 60
    assert recorded < datetime.now(UTC)


def test_unresolved_counts_by_severity() -> None:
    _clear()
    for severity in ("low", "medium", "high", "high"):
        save_security_incident(SecurityIncident(severity=severity, rule_id="R", message="finding"))
    summary = get_security_summary()
    assert summary["unresolved_total"] == 4
    assert summary["unresolved_by_severity"] == {"low": 1, "medium": 1, "high": 2}
    assert summary["oldest_unresolved_timestamp"] is not None


def test_resolved_incidents_are_excluded() -> None:
    _clear()
    save_security_incident(SecurityIncident(severity="high", rule_id="A", message="open"))
    save_security_incident(SecurityIncident(severity="critical", rule_id="B", message="closed", resolved=True))
    assert get_security_incidents(resolved=False)[0].rule_id == "A"
    assert get_security_incidents(resolved=True)[0].rule_id == "B"
    # resolved=None means "either", which is what a raw listing wants.
    assert len(get_security_incidents()) == 2
    summary = get_security_summary()
    assert summary["unresolved_total"] == 1
    assert summary["unresolved_by_severity"] == {"high": 1}


def test_getter_filters_by_severity_and_time() -> None:
    _clear()
    save_security_incident(
        SecurityIncident(
            severity="low",
            rule_id="OLD",
            message="old",
            timestamp=datetime.now(UTC) - timedelta(days=10),
        )
    )
    save_security_incident(SecurityIncident(severity="high", rule_id="NEW", message="new"))
    assert [i.rule_id for i in get_security_incidents(severity="low")] == ["OLD"]
    recent = get_security_incidents(since=datetime.now(UTC) - timedelta(hours=1))
    assert [i.rule_id for i in recent] == ["NEW"]
    assert get_security_incidents(since=datetime.now(UTC) - timedelta(days=30)) != []


def test_newest_first_ordering() -> None:
    _clear()
    save_security_incident(SecurityIncident(severity="low", rule_id="FIRST", message="a"))
    save_security_incident(SecurityIncident(severity="low", rule_id="SECOND", message="b"))
    assert [i.rule_id for i in get_security_incidents(limit=10)] == ["SECOND", "FIRST"]
