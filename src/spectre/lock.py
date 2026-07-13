from __future__ import annotations

import os
import time
from pathlib import Path

_LOCK_DIR = Path(".spectre") / "locks"


def _lock_path(service: str, environment: str) -> Path:
    return _LOCK_DIR / f"{service}-{environment}.lock"


def acquire(service: str, environment: str, version: str) -> str | None:
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = _lock_path(service, environment)

    if lock_file.is_file():
        content = lock_file.read_text(encoding="utf-8").strip()
        parts = content.split("|")
        pid = int(parts[0]) if parts else 0
        if _pid_alive(pid):
            existing_version = parts[1] if len(parts) > 1 else "?"
            existing = f"{existing_version}, pid {pid}"
            return f"already deploying {service}/{environment} (version {existing})"

    lock_file.write_text(f"{os.getpid()}|{version}|{time.time()}", encoding="utf-8")
    return None


def release(service: str, environment: str) -> None:
    lock_file = _lock_path(service, environment)
    try:
        if lock_file.is_file():
            lock_file.unlink()
    except OSError:
        pass


def is_locked(service: str, environment: str) -> bool:
    lock_file = _lock_path(service, environment)
    if not lock_file.is_file():
        return False
    try:
        content = lock_file.read_text(encoding="utf-8").strip()
        parts = content.split("|")
        pid = int(parts[0]) if parts else 0
        if not _pid_alive(pid):
            lock_file.unlink(missing_ok=True)
            return False
        return True
    except (OSError, ValueError):
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
