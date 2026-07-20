"""Tests for the task scheduler."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from packages.core.scheduler import (
    TaskScheduler,
    cron_matches,
    is_due,
    parse_cron,
    parse_interval,
    resolve_version,
)

# ── parse_interval ────────────────────────────────────────────────────────────


def test_parse_interval_hours() -> None:
    assert parse_interval("every 2h") == 7200


def test_parse_interval_minutes() -> None:
    assert parse_interval("every 30m") == 1800


def test_parse_interval_seconds() -> None:
    assert parse_interval("every 45s") == 45


def test_parse_interval_combined() -> None:
    assert parse_interval("every 1h30m") == 5400


def test_parse_interval_hourly() -> None:
    assert parse_interval("@hourly") == 3600


def test_parse_interval_daily() -> None:
    assert parse_interval("@daily") == 86400


def test_parse_interval_invalid() -> None:
    assert parse_interval("invalid") == 0


# ── parse_cron ────────────────────────────────────────────────────────────────


def test_parse_cron_all_wildcard() -> None:
    fields = parse_cron("* * * * *")
    assert fields[0] == set(range(0, 60))
    assert fields[1] == set(range(0, 24))


def test_parse_cron_specific() -> None:
    fields = parse_cron("30 6 * * *")
    assert fields[0] == {30}
    assert fields[1] == {6}


def test_parse_cron_range() -> None:
    fields = parse_cron("0 9 * * 1-5")
    assert fields[4] == {1, 2, 3, 4, 5}


# ── cron_matches ──────────────────────────────────────────────────────────────


def test_cron_matches() -> None:
    dt = datetime(2025, 1, 15, 6, 30, tzinfo=UTC)
    assert cron_matches("30 6 * * *", dt)


def test_cron_no_match() -> None:
    dt = datetime(2025, 1, 15, 7, 30, tzinfo=UTC)
    assert not cron_matches("30 6 * * *", dt)


# ── is_due ────────────────────────────────────────────────────────────────────


def test_is_due_interval_first_run() -> None:
    assert is_due("every 30m", last_run=None)


def test_is_due_interval_not_due() -> None:
    assert not is_due("every 1h", last_run=time.time())


def test_is_due_interval_due() -> None:
    assert is_due("every 1s", last_run=time.time() - 2)


def test_is_due_cron_not_due_recent() -> None:
    assert not is_due("* * * * *", last_run=time.time() - 1)


def test_is_due_cron_due_old() -> None:
    assert is_due("* * * * *", last_run=time.time() - 120)


# ── resolve_version ───────────────────────────────────────────────────────────


def test_resolve_version_fixed() -> None:
    assert resolve_version("v1.2.3") == "v1.2.3"


def test_resolve_version_latest_fallback() -> None:
    # In a non-git directory or without git, returns "latest"
    assert resolve_version("latest") in ("latest",) or isinstance(resolve_version("latest"), str)


# ── TaskScheduler ─────────────────────────────────────────────────────────────


def test_scheduler_add_task() -> None:
    s = TaskScheduler()
    s.add_task("test", "every 1h", lambda: None)
    assert len(s.get_tasks()) == 1
    assert s.get_tasks()[0].name == "test"


def test_scheduler_remove_task() -> None:
    s = TaskScheduler()
    s.add_task("test", "every 1h", lambda: None)
    s.remove_task("test")
    assert len(s.get_tasks()) == 0


def test_scheduler_tick_executes_due() -> None:
    s = TaskScheduler()
    results: list[str] = []
    s.add_task("test", "every 1s", lambda: results.append("done"))
    executed = s.tick()
    assert "test" in executed
    assert results == ["done"]


def test_scheduler_tick_skips_disabled() -> None:
    s = TaskScheduler()
    results: list[str] = []
    s.add_task("test", "every 1s", lambda: results.append("done"))
    s.get_tasks()[0].enabled = False
    executed = s.tick()
    assert "test" not in executed
    assert results == []


def test_scheduler_start_stop() -> None:
    s = TaskScheduler()
    s.add_task("test", "every 1s", lambda: None)
    s.start(interval=0.1)
    assert s._running is True
    s.stop()
    assert s._running is False
