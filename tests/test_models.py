"""Tests for memory database models and operations."""

from __future__ import annotations

from packages.memory.db import (
    Configuration,
    Decision,
    KVStore,
    MaintenanceRecord,
    Report,
    SecurityIncident,
    SystemMetric,
    WorkflowRun,
)


def test_system_metric_creation() -> None:
    m = SystemMetric(cpu_percent=50.0, memory_percent=60.0, swap_percent=10.0, disk_percent=70.0)
    assert m.cpu_percent == 50.0
    assert m.memory_percent == 60.0
    assert m.id is None


def test_system_metric_with_optional() -> None:
    m = SystemMetric(
        cpu_percent=50.0,
        memory_percent=60.0,
        swap_percent=10.0,
        disk_percent=70.0,
        battery_percent=85.0,
        temperature_c=45.0,
    )
    assert m.battery_percent == 85.0
    assert m.temperature_c == 45.0


def test_maintenance_record_creation() -> None:
    r = MaintenanceRecord(
        agent="linux",
        action="dnf-check-update",
        status="success",
        log_output="No updates available",
        duration_ms=1200,
    )
    assert r.agent == "linux"
    assert r.status == "success"
    assert r.duration_ms == 1200


def test_security_incident_creation() -> None:
    i = SecurityIncident(
        severity="high",
        rule_id="FIREWALL_OFF",
        message="Firewall is not running",
    )
    assert i.severity == "high"
    assert i.resolved is False


def test_configuration_creation() -> None:
    c = Configuration(key="theme", value="dark", profile="laptop")
    assert c.key == "theme"
    assert c.value == "dark"
    assert c.profile == "laptop"


def test_report_creation() -> None:
    r = Report(report_type="daily", content="# Daily Report", format="markdown")
    assert r.report_type == "daily"
    assert r.format == "markdown"


def test_workflow_run_creation() -> None:
    w = WorkflowRun(
        workflow="morning-startup",
        status="success",
        duration_ms=5000,
        details='{"linux": {}}',
    )
    assert w.workflow == "morning-startup"
    assert w.status == "success"


def test_decision_creation() -> None:
    d = Decision(
        context="system maintenance",
        decision="run weekly cleanup",
        rationale="Disk usage above 80%",
        outcome="completed",
    )
    assert d.decision == "run weekly cleanup"
    assert d.outcome == "completed"


def test_kv_store_creation() -> None:
    kv = KVStore(key="last_boot", value="2024-01-01")
    assert kv.key == "last_boot"
    assert kv.value == "2024-01-01"
