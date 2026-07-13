from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spectre.models import Schedule as ScheduleCfg

_INTERVAL_RE = re.compile(
    r"^every\s+(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE,
)


def parse_interval(expr: str) -> int:
    m = _INTERVAL_RE.match(expr.strip())
    if m:
        hours = int(m.group(1)) if m.group(1) else 0
        minutes = int(m.group(2)) if m.group(2) else 0
        seconds = int(m.group(3)) if m.group(3) else 0
        return hours * 3600 + minutes * 60 + seconds
    shorthand = {
        "@hourly": 3600,
        "@daily": 86400,
        "@weekly": 604800,
    }
    return shorthand.get(expr.strip().lower(), 0)


def _parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    if field == "*":
        return set(range(lo, hi + 1))
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            values.update(range(int(a), int(b) + 1))
        else:
            values.add(int(part))
    return {v for v in values if lo <= v <= hi}


def parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"invalid cron expression: {expr!r} (expected 5 fields)")
    return (
        _parse_cron_field(fields[0], 0, 59),
        _parse_cron_field(fields[1], 0, 23),
        _parse_cron_field(fields[2], 1, 31),
        _parse_cron_field(fields[3], 1, 12),
        _parse_cron_field(fields[4], 0, 6),
    )


def cron_matches(expr: str, dt: datetime | None = None) -> bool:
    if dt is None:
        dt = datetime.now(UTC)
    min_s, hour_s, dom_s, mon_s, dow_s = parse_cron(expr)
    return (
        dt.minute in min_s
        and dt.hour in hour_s
        and dt.day in dom_s
        and dt.month in mon_s
        and dt.weekday() in dow_s
    )


def is_due(
    schedule_expr: str,
    last_run: float | None = None,
) -> bool:
    now = time.time()
    interval = parse_interval(schedule_expr)
    if interval > 0:
        if last_run is None:
            return True
        return (now - last_run) >= interval
    if last_run is not None and (now - last_run) < 60:
        return False
    return cron_matches(schedule_expr)


def resolve_version(version_spec: str) -> str:
    if version_spec == "latest":
        try:
            import subprocess
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, OSError):
            pass
        return "latest"
    return version_spec


def load_schedules(path: str = "config/schedules.toml") -> list[ScheduleCfg]:
    p = Path(path)
    if not p.is_file():
        return []
    raw: dict[str, Any] = {}
    suffix = p.suffix.lower()
    if suffix == ".toml":
        import tomllib
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    elif suffix == ".json":
        raw = json.loads(p.read_text(encoding="utf-8"))
    else:
        return []
    schedules: list[ScheduleCfg] = []
    for key, cfg in raw.items():
        if isinstance(cfg, dict):
            cfg.setdefault("schedule", "")
            schedules.append(ScheduleCfg.from_dict({"name": key, **cfg}))
    return schedules


def _run_deploy_for_schedule(
    s: ScheduleCfg,
    schedules_path: str,
    services_path: str,
    environments_path: str,
) -> str | None:
    from spectre.cli import main as cli_main
    version = resolve_version(s.version)
    try:
        rc = cli_main([
            "deploy", s.service, s.environment, version,
            "--services", services_path,
            "--environments", environments_path,
            "--force",
        ])
        return None if rc == 0 else f"deploy failed for {s.service}/{s.environment}"
    except SystemExit:
        return None
    except Exception as exc:
        return str(exc)


def run_scheduler(
    schedules_path: str = "config/schedules.toml",
    services_path: str = "config/services.toml",
    environments_path: str = "config/environments.toml",
    interval: float = 30.0,
    once: bool = False,
) -> int:
    last_runs: dict[str, float] = {}

    if once:
        schedules = load_schedules(schedules_path)
        for s in schedules:
            if is_due(s.schedule, last_runs.get(s.name)):
                last_runs[s.name] = time.time()
                err = _run_deploy_for_schedule(
                    s, schedules_path, services_path, environments_path,
                )
                if err:
                    print(f"[schedule] {err}")
        return 0

    print("[schedule] scheduler started (Ctrl+C to stop)")
    while True:
        try:
            schedules = load_schedules(schedules_path)
            now = time.time()
            for s in schedules:
                if is_due(s.schedule, last_runs.get(s.name)):
                    last_runs[s.name] = now
                    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                    print(f"[{ts}] running scheduled deploy: {s.service}/{s.environment}")
                    err = _run_deploy_for_schedule(
                        s, schedules_path, services_path, environments_path,
                    )
                    if err:
                        print(f"[{ts}] {err}")
                    else:
                        print(f"[{ts}] {s.service}/{s.environment} completed")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[schedule] scheduler stopped")
            return 0
