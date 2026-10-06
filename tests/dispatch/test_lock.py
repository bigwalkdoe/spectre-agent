"""Tests for the per-job lock that keeps two mutating runs from interleaving.

The race this exists for is a 02:00 cron `backups/backup-all` and a hand-run
`spectre run backups/backup-all` landing together: both write the same target
directory, and whichever finishes last decides what is in it. The second arrival
must be refused, must say who holds the lock, and must leave behind nothing that
would convince a later run the job is still held by the process that just
refused.

Every test points `SPECTRE_CONFIG_DIR` at a `tmp_path`, so none of them creates
state in the real `~/.config/spectre`. The one test that exercises the default
config dir deletes the variable and points `HOME` at a tmpdir instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from packages.dispatch.lock import JobLock, LockUnavailable, lock_path, read_lock
from packages.dispatch.registry import Job
from tests.dispatch.conftest import make_job

# The timeout the jobs under test carry, so the staleness arithmetic in the tests
# that exercise it reads as the arithmetic in the module.
_TIMEOUT = 1800


def _job(mutates: bool = True, concurrency: str = "forbid") -> Job:
    return make_job(
        "backups/backup-all.sh",
        mutates=mutates,
        concurrency=concurrency,
        timeout=_TIMEOUT,
    )


def _config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_CONFIG_DIR", str(tmp_path))


def _write_lock(job: Job, pid: int, started_at: datetime) -> Path:
    """Put a lock file in place, as a run that crashed without releasing would."""
    path = lock_path(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "started_at": started_at.isoformat()}), encoding="utf-8")
    return path


def _backdate(path: Path, seconds: float) -> None:
    """Make `path` look `seconds` old, mtime and all.

    `os.utime` rather than a written `started_at`, because the one case that has to be
    judged by the file's own age is the file that names nothing at all.
    """
    when = time.time() - seconds
    os.utime(path, (when, when))


def _dead_pid() -> int:
    """A pid that has certainly exited: a child this test started and reaped.

    A pid invented from thin air is only *probably* unused — 999999 is inside this
    host's pid_max — so liveness would be a property of the machine rather than of
    the test.
    """
    reaped = subprocess.Popen(["/bin/true"])
    reaped.wait()  # reaped, so nothing owns this pid any more
    return reaped.pid


def test_allow_concurrency_jobs_never_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    j = _job(mutates=False, concurrency="allow")
    with JobLock(j):
        with JobLock(j):
            pass


def test_an_allow_concurrency_job_leaves_no_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A job that permits concurrency must not create the state a lock is: a
    directory and a file per run, to be cleaned up and to go stale."""
    _config_dir(tmp_path, monkeypatch)
    j = _job(mutates=False, concurrency="allow")
    with JobLock(j):
        pass
    assert not (tmp_path / "jobs").exists()


def test_forbid_refuses_the_second_holder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 3: overlapping invocations must not interleave."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with JobLock(j):
        try:
            JobLock(j).acquire()
        except LockUnavailable as e:
            assert e.pid == os.getpid()
        else:
            raise AssertionError("expected LockUnavailable")


def test_a_refusal_names_the_holder_and_the_time_it_started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal that only says "busy" sends the operator to the host to find out
    who holds the lock."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with JobLock(j):
        before = lock_path(j).read_text(encoding="utf-8")
        with pytest.raises(LockUnavailable) as refused:
            JobLock(j).acquire()
        assert str(os.getpid()) in str(refused.value)
        assert refused.value.started_at.tzinfo is not None
        assert refused.value.started_at.isoformat() in str(refused.value)
        # Refusing must have executed nothing and claimed nothing: the holder's file
        # is byte for byte what it was, and still the only file under jobs/.
        assert lock_path(j).read_text(encoding="utf-8") == before
        assert [p.name for p in lock_path(j).parent.iterdir()] == [lock_path(j).name]


def test_the_lock_file_is_readable_by_a_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mid-incident the lock file is what gets read, so it records who and since when
    in a form a person can parse."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with JobLock(j):
        decoded = json.loads(lock_path(j).read_text(encoding="utf-8"))
    assert decoded["pid"] == os.getpid()
    started_at = datetime.fromisoformat(decoded["started_at"])
    assert started_at.tzinfo is not None
    assert started_at <= datetime.now(UTC)


def test_lock_is_released_on_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with JobLock(j):
        pass
    JobLock(j).acquire()  # must not raise


def test_lock_is_released_when_the_body_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with pytest.raises(RuntimeError):
        with JobLock(j):
            raise RuntimeError("boom")
    JobLock(j).acquire()


def test_stale_lock_from_a_dead_pid_is_reclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = _write_lock(j, pid=999999, started_at=datetime(2026, 1, 1, tzinfo=UTC))
    with JobLock(j):
        pass
    assert not path.exists()


def test_a_dead_holder_is_reclaimed_even_by_a_fresh_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Liveness alone decides this one: the lock is seconds old, so only the dead
    pid can be why it is reclaimed."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = _write_lock(j, pid=_dead_pid(), started_at=datetime.now(UTC))
    with JobLock(j):
        pass
    assert not path.exists()


def test_a_lock_older_than_twice_the_timeout_is_reclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A holder that is still alive but far past the job's own timeout is presumed
    abandoned — the dispatcher that took it never came back, or never exited.

    The pid here is this very process, so the age is the only reason the lock is
    reclaimed; a liveness check alone would refuse it."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = _write_lock(j, pid=os.getpid(), started_at=datetime.now(UTC) - timedelta(seconds=2 * _TIMEOUT + 60))
    with JobLock(j):
        pass
    assert not path.exists()


def test_an_unsignalable_pid_is_reclaimed_rather_than_raising(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`os.kill` raises OverflowError — not ProcessLookupError — for a pid at or above
    2**31, so an uncaught one escapes as a traceback instead of a refusal, and escapes
    before the age rule runs, which would leave this file unreclaimable by anyone and
    block the job until it is deleted by hand. No Linux pid reaches 2**31, so it names
    no process and is reclaimed like any other abandoned lock."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = _write_lock(j, pid=2**31, started_at=datetime.now(UTC))
    with JobLock(j):
        pass
    assert not path.exists()


def test_a_zero_timeout_still_excludes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`registry.py` validates `timeout` as an int and not as a positive one, and the
    lock cannot lean on registry having validated its input: a zero-length staleness
    window would make every lock abandoned the instant it was written, and the lock
    would then exclude nothing at all."""
    _config_dir(tmp_path, monkeypatch)
    j = make_job("backups/backup-all.sh", mutates=True, concurrency="forbid", timeout=0)
    with JobLock(j):
        with pytest.raises(LockUnavailable) as refused:
            JobLock(j).acquire()
    assert refused.value.pid == os.getpid()


def test_a_lock_held_by_another_user_is_not_reclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`os.kill` raises PermissionError for a process this user cannot signal, which
    for an action running under sudo is the ordinary case. That is alive, not dead:
    reclaiming it would unprotect the very job the lock exists for."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = _write_lock(j, pid=4242, started_at=datetime.now(UTC))

    real_kill = os.kill

    def unsignalable(pid: int, sig: int) -> None:
        if pid == 4242:
            raise PermissionError(13, "Operation not permitted")
        real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", unsignalable)
    with pytest.raises(LockUnavailable) as refused:
        JobLock(j).acquire()
    assert refused.value.pid == 4242
    assert path.exists()


def test_an_empty_lock_file_is_refused_not_reclaimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`O_CREAT | O_EXCL` creates the file empty and the record follows in the next
    write, so a file this young is ambiguous between a dispatcher that has claimed it
    and one that died having done so. Reclaiming here would run two mutating jobs at
    once — the one outcome the lock exists to prevent — so the run is refused, and no
    liveness question is asked of a file that names no pid."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = lock_path(j)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    signalled: list[int] = []
    real_kill = os.kill

    def watched(pid: int, sig: int) -> None:
        signalled.append(pid)
        real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", watched)
    with pytest.raises(LockUnavailable) as refused:
        JobLock(j).acquire()

    assert refused.value.pid == 0
    assert str(path) in str(refused.value)
    assert "cannot be determined" in str(refused.value)
    # The file's own mtime is the only evidence there is of when it appeared, and it
    # is real evidence rather than a placeholder.
    assert abs((refused.value.started_at - datetime.fromtimestamp(path.stat().st_mtime, UTC)).total_seconds()) < 1
    assert refused.value.started_at <= datetime.now(UTC)
    # No pid to ask about, so none was asked about.
    assert signalled == []
    assert path.exists()


def test_an_unparseable_lock_file_is_refused_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same refusal for a file truncated by a full disk as for one caught mid-write:
    neither names a holder, so neither may be assumed to be free."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = lock_path(j)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"pid": ', encoding="utf-8")
    with pytest.raises(LockUnavailable) as refused:
        JobLock(j).acquire()
    assert refused.value.pid == 0
    assert path.exists()


def test_an_unreadable_lock_older_than_twice_the_timeout_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of refusing: an unreadable file nobody has claimed within twice
    this job's own timeout was abandoned, not in flight, so the job must not stay
    wedged behind it forever."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    path = lock_path(j)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    _backdate(path, 2 * _TIMEOUT + 60)
    with JobLock(j):
        pass
    assert not path.exists()


def test_a_reclaim_is_retried_once_and_then_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unbounded reclaim loop against a lock that keeps coming back is a livelock,
    so the second failure refuses rather than trying again."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    stale = {"pid": _dead_pid(), "started_at": (datetime.now(UTC) - timedelta(seconds=2 * _TIMEOUT + 60)).isoformat()}
    path = lock_path(j)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stale), encoding="utf-8")

    real_unlink = Path.unlink
    reclaims: list[str] = []

    def reappears(self: Path, missing_ok: bool = False) -> None:
        real_unlink(self, missing_ok=missing_ok)
        reclaims.append(self.name)
        self.write_text(json.dumps(stale), encoding="utf-8")  # claimed again behind our back

    monkeypatch.setattr(Path, "unlink", reappears)
    with pytest.raises(LockUnavailable) as refused:
        JobLock(j).acquire()
    assert refused.value.pid == stale["pid"]
    # Exactly one reclaim: the retry is the last attempt, and it refuses.
    assert len(reclaims) == 1


def test_release_leaves_a_lock_it_no_longer_owns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run whose lock was reclaimed as stale must not delete the file the run that
    reclaimed it now owns: that would free the job for a third invocation while the
    new holder is still working."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    first = JobLock(j)
    first.acquire()
    path = _write_lock(j, pid=os.getpid() + 1, started_at=datetime.now(UTC))

    first.release()
    assert (now := read_lock(path)) is not None
    assert now[0] != os.getpid()


def test_release_without_acquiring_leaves_the_holder_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second JobLock for a job this process already holds is not the holder, and a
    refused acquisition is not a holder at all; neither may release the real one."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    holder = JobLock(j)
    with holder:
        refused = JobLock(j)
        with pytest.raises(LockUnavailable):
            refused.acquire()
        refused.release()
        JobLock(j).release()
        assert (now := read_lock(lock_path(j))) is not None
        assert now[0] == os.getpid()


def test_release_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with JobLock(j) as held:
        pass
    held.release()
    held.release()
    assert not lock_path(j).exists()


def test_release_unlinks_the_file_it_claimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The path is remembered from the claim rather than resolved again, so a config
    directory that moved between the two cannot leave the real lock file behind: the
    release would read a lock this process never wrote, find no pid of its own in it,
    and leak the original until the age rule noticed."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    with JobLock(j):
        claimed = lock_path(j)
        monkeypatch.setenv("SPECTRE_CONFIG_DIR", str(tmp_path / "elsewhere"))
        assert lock_path(j) != claimed
    assert not claimed.exists()


def test_read_lock_is_none_for_a_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    assert read_lock(lock_path(_job())) is None


def test_read_lock_is_none_for_a_lock_that_names_no_holder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing a holder wrote is refused, and nothing from a foreign writer is guessed
    at: a `pid` that is not an integer, or a `started_at` with no timezone, is not a
    holder this dispatcher can reason about."""
    _config_dir(tmp_path, monkeypatch)
    j = _job()
    for contents in (
        "",
        "null",
        "[]",
        '{"pid": true, "started_at": "2026-01-01T00:00:00+00:00"}',
        '{"pid": 1, "started_at": "2026-01-01T00:00:00"}',
        '{"pid": 1, "started_at": "not-a-time"}',
    ):
        path = _write_lock(j, pid=1, started_at=datetime(2026, 1, 1, tzinfo=UTC))
        path.write_text(contents, encoding="utf-8")
        assert read_lock(path) is None, contents


def test_lock_path_uses_the_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _config_dir(tmp_path, monkeypatch)
    assert lock_path(_job()) == tmp_path / "jobs" / "backups" / "backup-all.lock"


def test_lock_path_falls_back_to_the_home_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented default, with `HOME` redirected so the assertion does not name
    the machine's real config directory."""
    monkeypatch.delenv("SPECTRE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert lock_path(_job()) == tmp_path / ".config" / "spectre" / "jobs" / "backups" / "backup-all.lock"
