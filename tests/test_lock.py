from __future__ import annotations

from pathlib import Path

from spectre import lock


def test_acquire_and_release(tmp_path: Path) -> None:
    lock._LOCK_DIR = tmp_path / "locks"
    err = lock.acquire("api", "staging", "v1")
    assert err is None

    err = lock.acquire("api", "staging", "v2")
    assert err is not None
    assert "already deploying" in err

    lock.release("api", "staging")
    err = lock.acquire("api", "staging", "v3")
    assert err is None
    lock.release("api", "staging")


def test_is_locked(tmp_path: Path) -> None:
    lock._LOCK_DIR = tmp_path / "locks"
    assert not lock.is_locked("api", "staging")

    lock.acquire("api", "staging", "v1")
    assert lock.is_locked("api", "staging")

    lock.release("api", "staging")
    assert not lock.is_locked("api", "staging")


def test_release_idempotent(tmp_path: Path) -> None:
    lock._LOCK_DIR = tmp_path / "locks"
    lock.release("api", "staging")
    lock.release("api", "staging")


def test_isolated_per_service(tmp_path: Path) -> None:
    lock._LOCK_DIR = tmp_path / "locks"
    lock.acquire("api", "staging", "v1")
    assert lock.acquire("worker", "staging", "v1") is None
    assert lock.acquire("api", "production", "v1") is None
    lock.release("api", "staging")
    lock.release("worker", "staging")
    lock.release("api", "production")


def test_stale_lock_cleaned(tmp_path: Path) -> None:
    lock._LOCK_DIR = tmp_path / "locks"
    lock_file = tmp_path / "locks" / "api-staging.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text("999999999|v1|0.0", encoding="utf-8")

    assert lock.is_locked("api", "staging") is False
    assert lock_file.exists() is False


def test_acquire_replaces_stale(tmp_path: Path) -> None:
    lock._LOCK_DIR = tmp_path / "locks"
    lock_file = tmp_path / "locks" / "api-staging.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text("999999999|v1|0.0", encoding="utf-8")

    err = lock.acquire("api", "staging", "v2")
    assert err is None
    assert lock_file.is_file()
