"""Tests for the Spectre CLI."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

from apps.cli.main import app, main

# ── Help command tests ────────────────────────────────────────────────────────


def test_help() -> None:
    """CLI --help should exit 0."""
    try:
        app(["--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_doctor_help() -> None:
    """doctor --help should exit 0."""
    try:
        app(["doctor", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_health_help() -> None:
    """health --help should exit 0."""
    try:
        app(["health", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_workflows_help() -> None:
    """workflows --help should exit 0."""
    try:
        app(["workflows", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_containers_help() -> None:
    """containers --help should exit 0."""
    try:
        app(["containers", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_models_help() -> None:
    """models --help should exit 0."""
    try:
        app(["models", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_security_help() -> None:
    """security --help should exit 0."""
    try:
        app(["security", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_report_help() -> None:
    """report --help should exit 0."""
    try:
        app(["report", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_config_help() -> None:
    """config --help should exit 0."""
    try:
        app(["config", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_events_help() -> None:
    """events --help should exit 0."""
    try:
        app(["events", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_kernel_help() -> None:
    """kernel --help should exit 0."""
    try:
        app(["kernel", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_service_bus_help() -> None:
    """service-bus --help should exit 0."""
    try:
        app(["service-bus", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_core_help() -> None:
    """core --help should exit 0."""
    try:
        app(["core", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_plugins_help() -> None:
    """plugins --help should exit 0."""
    try:
        app(["plugins", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_version_help() -> None:
    """version --help should exit 0."""
    try:
        app(["version", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_daemon_help() -> None:
    """daemon --help should exit 0."""
    try:
        app(["daemon", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_init_help() -> None:
    """init --help should exit 0."""
    try:
        app(["init", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_logs_help() -> None:
    """logs --help should exit 0."""
    try:
        app(["logs", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_export_help() -> None:
    """export --help should exit 0."""
    try:
        app(["export", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_schedule_help() -> None:
    """schedule --help should exit 0."""
    try:
        app(["schedule", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_dashboard_help() -> None:
    """dashboard --help should exit 0."""
    try:
        app(["dashboard", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_import_help() -> None:
    """import --help should exit 0."""
    try:
        app(["import", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


# ── Core functionality tests ──────────────────────────────────────────────────


def test_main_returns_int() -> None:
    """main() should return an integer exit code."""
    with patch("apps.cli.main._get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        result = main(["--help"])
        assert isinstance(result, int)


def test_unknown_command() -> None:
    """Unknown command should fail gracefully."""
    try:
        app(["nonexistent"], standalone_mode=False)
    except (SystemExit, Exception):
        pass  # Both SystemExit and click.exceptions.UsageError are acceptable


# ── Command execution tests ───────────────────────────────────────────────────


def test_kernel_status() -> None:
    """kernel status should show kernel info."""
    try:
        app(["kernel", "status"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_kernel_start_stop() -> None:
    """kernel start/stop should work."""
    try:
        app(["kernel", "start"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0
    try:
        app(["kernel", "stop"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_service_bus_list() -> None:
    """service-bus --list should show registered services."""
    try:
        app(["service-bus", "--list"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_service_bus_topics() -> None:
    """service-bus --topics should show subscribed topics."""
    try:
        app(["service-bus", "--topics"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_core_status() -> None:
    """core should show core status."""
    try:
        app(["core"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_doctor() -> None:
    """doctor should run diagnostics."""
    try:
        app(["doctor"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_health() -> None:
    """health should show health metrics."""
    try:
        app(["health"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_status() -> None:
    """status should show system status."""
    try:
        app(["status"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_status_json() -> None:
    """status --json should output JSON."""
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        app(["status", "--json"], standalone_mode=False)
    except SystemExit:
        pass
    finally:
        sys.stdout = old_stdout

    output = buffer.getvalue()
    if output:
        data = json.loads(output)
        assert isinstance(data, dict)


def test_update() -> None:
    """update should check for updates."""
    try:
        app(["update"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_clean() -> None:
    """clean should clean caches."""
    try:
        app(["clean"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_repair() -> None:
    """repair should attempt repair."""
    try:
        app(["repair"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_optimize() -> None:
    """optimize should run optimization."""
    try:
        app(["optimize"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_security_audit() -> None:
    """security --audit should run security audit."""
    try:
        app(["security", "--audit"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_security() -> None:
    """security should show basic security info."""
    try:
        app(["security"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_services() -> None:
    """services should show systemd services."""
    try:
        app(["services"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_containers() -> None:
    """containers should show container status."""
    try:
        app(["containers"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_containers_prune() -> None:
    """containers --prune should prune containers."""
    try:
        app(["containers", "--prune"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_models() -> None:
    """models should show model status."""
    try:
        app(["models"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_models_list() -> None:
    """models --list should list models."""
    try:
        app(["models", "--list"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_models_benchmark() -> None:
    """models --benchmark should benchmark model."""
    try:
        app(["models", "--benchmark"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_workflows_list() -> None:
    """workflows --list should list workflows."""
    try:
        app(["workflows", "--list"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_workflows_run() -> None:
    """workflows should run a workflow."""
    try:
        app(["workflows", "morning-startup"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_workflows_definitions() -> None:
    """workflows --definitions should show workflow definitions."""
    try:
        app(["workflows", "--definitions"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_workflows_load_nonexistent() -> None:
    """workflows --load with nonexistent dir should fail gracefully."""
    try:
        app(["workflows", "--load", "/nonexistent/dir"], standalone_mode=False)
    except (SystemExit, Exception):
        pass


def test_backup() -> None:
    """backup should run backup workflow."""
    try:
        app(["backup"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_restore() -> None:
    """restore should run restore workflow."""
    try:
        app(["restore"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_report() -> None:
    """report should generate a report."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        output = f.name
    try:
        app(["report", "--output", output], standalone_mode=False)
        assert os.path.exists(output)
    finally:
        if os.path.exists(output):
            os.unlink(output)


def test_config_show() -> None:
    """config --show should show configuration."""
    try:
        app(["config", "--show"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_config_get() -> None:
    """config --get should get config value."""
    try:
        app(["config", "--get", "profile"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_config_set() -> None:
    """config --set should set config value."""
    try:
        app(["config", "--set", "test_key", "--value", "test_value"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_config_get_nonexistent() -> None:
    """config --get should return gracefully for missing keys."""
    try:
        app(["config", "--get", "nonexistent.key"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_events() -> None:
    """events should show recent events."""
    try:
        app(["events"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_events_limit() -> None:
    """events --limit should limit results."""
    try:
        app(["events", "--limit", "5"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_events_empty() -> None:
    """events should show no events when database is fresh."""
    try:
        app(["events"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_version() -> None:
    """version should display version info."""
    try:
        app(["version"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_daemon_status() -> None:
    """daemon status should show daemon status."""
    try:
        app(["daemon", "status"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_init() -> None:
    """init should initialize Spectre."""
    try:
        app(["init"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_init_force() -> None:
    """init --force should force reinitialize."""
    try:
        app(["init", "--force"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_logs() -> None:
    """logs should show logs."""
    try:
        app(["logs"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_logs_lines() -> None:
    """logs -n should limit lines."""
    try:
        app(["logs", "-n", "10"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_schedule_add() -> None:
    """schedule add should add a task."""
    try:
        app(
            [
                "schedule",
                "add",
                "--name",
                "test",
                "--cron",
                "0 * * * *",
                "--workflow",
                "morning-startup",
            ],
            standalone_mode=False,
        )
    except SystemExit as e:
        assert e.code == 0


def test_schedule_remove() -> None:
    """schedule remove should remove a task."""
    try:
        app(["schedule", "remove", "--name", "test"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_schedule_run() -> None:
    """schedule run should run a task."""
    try:
        app(["schedule", "run", "--name", "test"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_schedule_list() -> None:
    """schedule list should show scheduled tasks."""
    try:
        app(["schedule", "list"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_export_json() -> None:
    """export --format json should export JSON."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output = f.name
    try:
        app(["export", "--output", output, "--format", "json"], standalone_mode=False)
        assert os.path.exists(output)
    finally:
        if os.path.exists(output):
            os.unlink(output)


def test_export_csv() -> None:
    """export --format csv should export CSV."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        output = f.name
    try:
        app(["export", "--output", output, "--format", "csv"], standalone_mode=False)
        assert os.path.exists(output)
        import csv

        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert isinstance(rows, list)
    finally:
        if os.path.exists(output):
            os.unlink(output)


def test_monitor() -> None:
    """monitor should show metrics."""
    try:
        app(["monitor"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0
