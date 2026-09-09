from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A single scheduled task definition."""

    name: str
    schedule: str
    callback: Callable[..., Any]
    last_run: float | None = None
    enabled: bool = True


def parse_interval(expr: str) -> int:
    """Parse an interval expression into seconds.

    Supports: 'every 2h', 'every 30m', 'every 45s', 'every 1h30m',
              '@hourly', '@daily'.
    Returns 0 for invalid expressions.
    """
    shortcuts = {"@hourly": 3600, "@daily": 86400, "@weekly": 604800, "@monthly": 2592000}
    if expr in shortcuts:
        return shortcuts[expr]

    m = re.match(r"^every\s+((\d+)h)?((\d+)m)?((\d+)s)?$", expr)
    if not m:
        return 0

    hours = int(m.group(2) or 0)
    minutes = int(m.group(4) or 0)
    seconds = int(m.group(6) or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else 0


def cron_field(field_str: str, lo: int, hi: int) -> set[int]:
    """Parse a single cron field into a set of allowed values."""
    values: set[int] = set()
    for part in field_str.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(lo, hi + 1))
        elif "-" in part:
            start, end = part.split("-", 1)
            values.update(range(int(start), int(end) + 1))
        elif "/" in part:
            start, step = part.split("/", 1)
            s = int(step)
            if start == "*":
                values.update(range(lo, hi + 1, s))
            else:
                values.update(range(int(start), hi + 1, s))
        else:
            values.add(int(part))
    return values


def parse_cron(expr: str) -> list[set[int]]:
    """Parse a 5-field cron expression into a list of value sets.

    Fields: minute(0-59), hour(0-23), day(1-31), month(1-12), weekday(0-6).
    """
    fields = expr.split()
    if len(fields) != 5:
        return [set()] * 5
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    return [cron_field(f, lo, hi) for f, (lo, hi) in zip(fields, bounds, strict=False)]


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime matches a cron expression.

    Cron's weekday field runs 0-6 with 0 = Sunday, while Python's
    ``datetime.weekday()`` runs Monday(0)-Sunday(6), so the value is remapped.
    """
    fields = parse_cron(cron_expr)
    cron_weekday = (dt.weekday() + 1) % 7  # Monday=0 -> Sunday=0
    checks = [dt.minute, dt.hour, dt.day, dt.month, cron_weekday]
    return all(v in s for v, s in zip(checks, fields, strict=False))


def is_due(schedule_expr: str, last_run: float | None = None) -> bool:
    """Determine if a scheduled task is due to run."""
    if parse_interval(schedule_expr) > 0:
        if last_run is None:
            return True
        return (time.time() - last_run) >= parse_interval(schedule_expr)

    if cron_matches(schedule_expr, datetime.now(UTC)):
        if last_run is None:
            return True
        return (time.time() - last_run) >= 60
    return False


def resolve_version(version: str) -> str:
    """Resolve 'latest' to the current git short SHA, or return as-is."""
    if version != "latest":
        return version
    try:
        import subprocess

        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "latest"


class TaskScheduler:
    """Cron/interval-based task scheduler for periodic workflows."""

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def add_task(self, name: str, schedule: str, callback: Callable[..., Any]) -> None:
        """Register a new scheduled task."""
        self._tasks[name] = ScheduledTask(name=name, schedule=schedule, callback=callback)
        logger.info("Scheduled task '%s' with schedule '%s'", name, schedule)

    def remove_task(self, name: str) -> None:
        """Remove a scheduled task by name."""
        self._tasks.pop(name, None)

    def get_tasks(self) -> list[ScheduledTask]:
        """Return all registered tasks."""
        return list(self._tasks.values())

    def tick(self) -> list[str]:
        """Check all tasks and run those that are due. Returns names of executed tasks."""
        executed: list[str] = []
        for task in self._tasks.values():
            if not task.enabled:
                continue
            if is_due(task.schedule, task.last_run):
                logger.info("Running scheduled task '%s'", task.name)
                try:
                    task.callback()
                except Exception:
                    logger.exception("Scheduled task '%s' failed", task.name)
                task.last_run = time.time()
                executed.append(task.name)
        return executed

    def start(self, interval: float = 10.0) -> None:
        """Start the scheduler in a background thread."""
        if self._running:
            return
        self._running = True

        def _run() -> None:
            while self._running:
                self.tick()
                time.sleep(interval)

        self._thread = threading.Thread(target=_run, daemon=True, name="spectre-scheduler")
        self._thread.start()
        logger.info("Scheduler started (interval=%.1fs)", interval)

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Scheduler stopped")
