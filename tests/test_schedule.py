from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from spectre.schedule import (
    cron_matches,
    is_due,
    load_schedules,
    parse_cron,
    parse_interval,
    resolve_version,
)


def test_parse_interval_hours() -> None:
    assert parse_interval("every 2h") == 7200


def test_parse_interval_minutes() -> None:
    assert parse_interval("every 30m") == 1800


def test_parse_interval_seconds() -> None:
    assert parse_interval("every 45s") == 45


def test_parse_interval_combined() -> None:
    assert parse_interval("every 1h30m") == 5400


def test_parse_interval_at_hourly() -> None:
    assert parse_interval("@hourly") == 3600


def test_parse_interval_at_daily() -> None:
    assert parse_interval("@daily") == 86400


def test_parse_interval_invalid() -> None:
    assert parse_interval("invalid") == 0


def test_parse_cron_all_wildcard() -> None:
    fields = parse_cron("* * * * *")
    assert all(f == set(range(lo, hi + 1)) for f, lo, hi in [
        (fields[0], 0, 59), (fields[1], 0, 23),
        (fields[2], 1, 31), (fields[3], 1, 12),
        (fields[4], 0, 6),
    ])


def test_parse_cron_specific() -> None:
    fields = parse_cron("30 6 * * 1-5")
    assert fields[0] == {30}
    assert fields[1] == {6}
    assert fields[4] == {1, 2, 3, 4, 5}


def test_cron_matches() -> None:
    dt = datetime(2025, 1, 15, 6, 30, tzinfo=UTC)
    assert cron_matches("30 6 * * *", dt)


def test_cron_does_not_match() -> None:
    dt = datetime(2025, 1, 15, 7, 30, tzinfo=UTC)
    assert not cron_matches("30 6 * * *", dt)


def test_is_due_interval_first_run() -> None:
    assert is_due("every 30m", last_run=None)


def test_is_due_interval_not_due() -> None:
    import time
    assert not is_due("every 1h", last_run=time.time())


def test_is_due_interval_due() -> None:
    import time
    assert is_due("every 1s", last_run=time.time() - 2)


def test_is_due_cron_matches() -> None:
    dt = datetime(2025, 1, 15, 6, 30, tzinfo=UTC)
    with patch("spectre.schedule.datetime") as mock_dt:
        mock_dt.now.return_value = dt
        mock_dt.fromtimestamp.return_value = dt
        assert is_due("30 6 * * *")


def test_is_due_cron_not_due_within_60s() -> None:
    import time
    now = time.time()
    assert not is_due("* * * * *", last_run=now - 1)


def test_is_due_cron_due_after_60s() -> None:
    import time
    now = time.time()
    with patch("spectre.schedule.cron_matches") as mock_match:
        mock_match.return_value = True
        assert is_due("* * * * *", last_run=now - 120)


def test_resolve_version_latest_no_git(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        class Result:
            returncode = 1
            stdout = ""
            stderr = ""
        mock_run.return_value = Result()
        assert resolve_version("latest") == "latest"


def test_resolve_version_fixed() -> None:
    assert resolve_version("v1.2.3") == "v1.2.3"


def test_load_schedules_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "schedules.toml"
    cfg.write_text(
        '[nightly]\nservice = "api"\nenvironment = "staging"\nschedule = "every 24h"\n'
    )
    schedules = load_schedules(str(cfg))
    assert len(schedules) == 1
    assert schedules[0].service == "api"
    assert schedules[0].schedule == "every 24h"


def test_load_schedules_missing() -> None:
    assert load_schedules("/nonexistent/schedules.toml") == []


def test_load_schedules_json(tmp_path: Path) -> None:
    cfg = tmp_path / "schedules.json"
    cfg.write_text(
        '{"nightly": {"service": "api", "environment": "staging", "schedule": "every 24h"}}'
    )
    schedules = load_schedules(str(cfg))
    assert len(schedules) == 1
    assert schedules[0].service == "api"
    assert schedules[0].schedule == "every 24h"
