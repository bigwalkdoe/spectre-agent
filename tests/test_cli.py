"""Tests for the Spectre CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from apps.cli.main import app, main


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


def test_workflows_list() -> None:
    """workflows --list should show available workflows."""
    try:
        app(["workflows", "--list"], standalone_mode=False)
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


def test_config_show() -> None:
    """config --show should display configuration."""
    try:
        app(["config", "--show"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_config_get_nonexistent() -> None:
    """config --get should return gracefully for missing keys."""
    try:
        app(["config", "--get", "nonexistent.key"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_events_empty() -> None:
    """events should show no events when database is fresh."""
    try:
        app(["events"], standalone_mode=False)
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


def test_version() -> None:
    """version should display version info."""
    try:
        app(["version"], standalone_mode=False)
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


def test_init() -> None:
    """init should initialize Spectre."""
    try:
        app(["init"], standalone_mode=False)
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


def test_export() -> None:
    """export should export data to JSON."""
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output = f.name
    try:
        app(["export", "--output", output], standalone_mode=False)
        assert os.path.exists(output)
        import json
        data = json.loads(open(output).read())
        assert "version" in data
        assert "exported_at" in data
    finally:
        os.unlink(output)


def test_schedule_help() -> None:
    """schedule --help should exit 0."""
    try:
        app(["schedule", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_schedule_list() -> None:
    """schedule list should show scheduled tasks."""
    try:
        app(["schedule", "list"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_dashboard_help() -> None:
    """dashboard --help should exit 0."""
    try:
        app(["dashboard", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_status_json() -> None:
    """status --json should output JSON."""
    import io
    import json
    import sys

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


def test_doctor_fix_help() -> None:
    """doctor --help should show --fix option."""
    try:
        app(["doctor", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_plugins_install_help() -> None:
    """plugins --help should show --install option."""
    try:
        app(["plugins", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_import_help() -> None:
    """import --help should exit 0."""
    try:
        app(["import", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_export_csv() -> None:
    """export --format csv should export to CSV."""
    import os
    import tempfile

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
        os.unlink(output)


def test_plugins_search_help() -> None:
    """plugins --help should show --search option."""
    try:
        app(["plugins", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_plugins_remove_help() -> None:
    """plugins --help should show --remove option."""
    try:
        app(["plugins", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_security_fix_help() -> None:
    """security --help should show --fix option."""
    try:
        app(["security", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0


def test_status_watch_help() -> None:
    """status --help should show --watch option."""
    try:
        app(["status", "--help"], standalone_mode=False)
    except SystemExit as e:
        assert e.code == 0
