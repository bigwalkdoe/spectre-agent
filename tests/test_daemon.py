"""Tests for the Spectre daemon."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from apps.daemon.main import SpectreDaemon


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
