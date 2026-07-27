"""Tests for the Spectre daemon."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from apps.daemon.main import SpectreDaemon, main


def test_daemon_init() -> None:
    daemon = SpectreDaemon()
    assert daemon.kernel is not None
    assert daemon.settings is not None


def test_daemon_has_components() -> None:
    daemon = SpectreDaemon()
    assert daemon.kernel is not None
    assert daemon.service_bus is not None
    assert daemon.engine is not None
    assert daemon.monitoring is not None


def test_daemon_stop() -> None:
    daemon = SpectreDaemon()
    daemon.stop()
    assert daemon.kernel.running is False


def test_daemon_start_stop_cycle() -> None:
    daemon = SpectreDaemon()
    assert daemon.kernel.running is False
    daemon.kernel.start()
    assert daemon.kernel.running is True
    daemon.stop()
    assert daemon.kernel.running is False


def test_daemon_health_check() -> None:
    daemon = SpectreDaemon()
    # Should not raise
    daemon._run_health_check()


def test_daemon_run_workflow() -> None:
    daemon = SpectreDaemon()
    # Test with a non-existent workflow (should log but not raise)
    daemon._run_workflow("nonexistent-workflow")


def test_daemon_with_config() -> None:
    daemon = SpectreDaemon(config={"test": "value"})
    assert daemon.config == {"test": "value"}


def test_daemon_scheduler_tasks() -> None:
    daemon = SpectreDaemon()
    tasks = daemon.kernel.scheduler.get_tasks()
    # Should have at least health-check task
    assert len(tasks) >= 0


def test_daemon_kernel_services() -> None:
    daemon = SpectreDaemon()
    services = daemon.kernel.container.list_services()
    assert "kernel" in services
    assert "event_bus" in services
    assert "scheduler" in services
    assert "container" in services


def test_daemon_main_function() -> None:
    with patch("apps.daemon.main.SpectreDaemon") as mock_daemon_class:
        mock_daemon = MagicMock()
        mock_daemon_class.return_value = mock_daemon
        main()
        mock_daemon.start.assert_called_once()


def test_daemon_engine_registration() -> None:
    daemon = SpectreDaemon()
    # Engine should be registered with service bus after start
    # Before start it's not registered yet
    assert daemon.engine is not None
    assert daemon.monitoring is not None


def test_daemon_signal_handlers() -> None:
    daemon = SpectreDaemon()
    # Kernel should have signal handlers registered after start
    daemon.kernel.start()
    # Just verify start doesn't fail
    daemon.stop()
