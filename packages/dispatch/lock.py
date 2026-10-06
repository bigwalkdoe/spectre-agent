"""One lock per job, so a mutating action is never run twice at once.

The race this prevents is a 02:00 cron `backups/backup-all` and a hand-run
`spectre run backups/backup-all` landing together: both write the same target
directory, and whichever finishes last decides what is in it. A
`concurrency="forbid"` job therefore takes a lock file for the length of its run,
and the second arrival is refused by name before it executes anything.

A `concurrency="allow"` job takes nothing. Read-only jobs are the majority, two of
them are harmless, and a lock for them would cost a directory and a file per run
for no guarantee — so that path touches no filesystem at all: a job which permits
concurrency leaves no state behind to expire.

Two properties make the file a claim rather than a hint. It is created with
`O_CREAT | O_EXCL`, the one creation the filesystem performs atomically, so of two
dispatchers arriving together exactly one gets it and the other is told the file
exists rather than losing a race. And it names its holder — pid and start time as
JSON a person can read mid-incident — because "backup-all is locked" is only
actionable once you know by whom, and because the two ways a holder goes away
without releasing have to be told apart from the third, where it is still working.

Those two ways are reclaimed from: a pid that no longer exists, which is a
dispatcher that was killed rather than exiting, and a lock older than twice the
job's own timeout, which is a holder that never came back. A file naming no
readable holder is reclaimed on the same terms — it is a dispatcher that died
between creating and writing it, or one truncated by a full disk. Reclaiming is
tried *once*: an unbounded reclaim loop against a lock that keeps being re-created
is a livelock, and a lock that cannot be reclaimed must fail loudly rather than
spin.

Releasing is where the lock's other half lives. `release` unlinks only while the
file still names this process, because a run whose lock was reclaimed as stale
must not delete the file the run that reclaimed it now owns — freeing the job for
a third invocation while the real holder is still working.

`alive` reads permission as liveness: `os.kill(pid, 0)` raises `PermissionError`
for a process owned by another user, and several of these actions run under sudo,
so that answer means the holder is there. Reclaiming a lock we cannot signal would
unprotect the very job the lock exists for.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.dispatch.registry import Job

# How long a lock may outlive its holder before it is presumed abandoned: twice
# the job's own timeout, which is the longest a run is allowed to take plus room
# for the process that took the lock never having reached the dispatcher that
# would have released it.
_STALE_TIMEOUTS = 2

# A lock file is created 0o600: it is per-user state, and no other account needs
# to read it. The mode is still masked by the umask, which can only narrow this.
_LOCK_MODE = 0o600

# What `read_lock` reports for a file that exists but names no holder. Neither
# value is a real pid or a real instant — pid 0 is not a process any dispatcher
# can have, and the epoch is not a time any of them started — so they cannot be
# mistaken for a holder by anything reading this file. `alive` treats a
# non-positive pid as dead, which is what keeps such a file from wedging the job:
# the next run reclaims it instead of refusing forever.
_NO_HOLDER: tuple[int, datetime] = (0, datetime.fromtimestamp(0, UTC))


class LockUnavailable(Exception):
    """This job is already running, and this invocation must not run it.

    Carries the holder's pid and start time rather than only a message, because the
    caller's whole response is to refuse and say who is in the way — an exit code
    for the shell, and a line for the operator reading it.
    """

    def __init__(self, message: str, pid: int, started_at: datetime) -> None:
        super().__init__(message)
        self.pid = pid
        self.started_at = started_at


def _config_dir() -> Path:
    """Where Spectre keeps its per-user state.

    Read at call time rather than at import, for the reason `packages/memory/db.py`
    cannot do otherwise: a value resolved once at import cannot be redirected
    afterwards, so a test run would take its locks in the real `~/.config/spectre`.
    An empty variable is treated as unset, since `Path("")` is the working
    directory and every lock would then land in the checkout.
    """
    configured = os.environ.get("SPECTRE_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "spectre"


def lock_path(job: Job) -> Path:
    """The lock file for `job`.

    Under the job's own name, so `jobs/backups/backup-all.lock` says which job it is
    for without a second lookup — the layout is the documentation, and an operator
    handed a path by an error message can read it.
    """
    return _config_dir() / "jobs" / f"{job.name}.lock"


def read_lock(path: Path) -> tuple[int, datetime] | None:
    """The `(pid, started_at)` recorded in `path`, or None if it names no holder.

    None covers an absent file, an unreadable one and one whose contents do not
    describe a holder, because the only safe response to all three is the same as to
    a dead holder. Nothing is guessed: a `pid` that is not an integer and a
    `started_at` without a timezone are both refused, since an instant that cannot be
    compared against a timeout would let a file this dispatcher did not write decide
    when its job may run again.
    """
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    # RecursionError is json's own overflow on deeply nested text, and belongs to
    # "unreadable" for the same reason JSONDecodeError does.
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(decoded, dict):
        return None

    pid, started_at = decoded.get("pid"), decoded.get("started_at")
    # isinstance(True, int) is True, so a JSON `true` would otherwise read as pid 1.
    if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(started_at, str):
        return None
    try:
        when = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return (pid, when) if when.tzinfo is not None else None


def _alive(pid: int) -> bool:
    """Whether `pid` is a process this host still has.

    `PermissionError` means yes: the process exists and belongs to another user,
    which for an action running under sudo is the ordinary answer, and the opposite
    reading would reclaim a live lock. A pid that is not positive is never a holder
    this can verify — `kill` reads 0 and a negative pid as "my process group" and
    "every process I may signal", which says nothing about a lock's owner — and
    `read_lock` never produces one except for an unreadable file, which must not
    wedge the job.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class JobLock:
    """One job's lock, held for the length of its run.

    `with JobLock(job):` acquires on entry and releases on exit, including when the
    body raises. A job whose concurrency is `"allow"` holds nothing: acquiring and
    releasing it do nothing and write nothing.
    """

    def __init__(self, job: Job) -> None:
        self._job = job
        # Decided here so that `__init__` itself touches no filesystem for an
        # allow-concurrency job: the lock file is state, and a job that permits
        # concurrency must leave none.
        self._enforced = job.concurrency == "forbid"
        # Whether *this* object holds the lock. Distinct from `_enforced`, and
        # distinct from the file's contents: a second `JobLock` for a job this
        # process already holds is not the holder and must not release it.
        self._held = False

    def __enter__(self) -> JobLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def acquire(self) -> None:
        """Take the lock, or raise `LockUnavailable` naming the holder.

        Acquiring a lock this object already holds is a no-op, as releasing one it
        does not hold is: the pair is used from a `finally`, and neither half should
        be able to fail on how many times the caller got there.
        """
        if not self._enforced or self._held:
            return

        path = lock_path(self._job)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}
        body = json.dumps(record).encode("utf-8")

        try:
            self._claim(path, body)
        except FileExistsError:
            holder = read_lock(path)
            if not self._abandoned(holder):
                raise self._refused(holder) from None
            # Provably nobody is working on this job. Remove the file and claim it
            # again — once, because the retry is the end of the line, not a loop.
            path.unlink(missing_ok=True)
            try:
                self._claim(path, body)
            except FileExistsError:
                raise self._refused(read_lock(path)) from None

        self._held = True

    def release(self) -> None:
        """Give the lock up, if this run is the one holding it.

        The pid in the file is what decides that, and it is the whole point: a run
        whose lock was reclaimed as stale must not delete the file the run that
        reclaimed it now owns, or a third invocation would be free to start the job
        while that run is still working on it. Unlinking by path alone would hand the
        job to whoever asked next.

        A no-op for a lock this object never took, and for one taken twice.
        """
        if not self._held:
            return
        self._held = False

        path = lock_path(self._job)
        holder = read_lock(path)
        if holder is not None and holder[0] == os.getpid():
            path.unlink(missing_ok=True)

    def _claim(self, path: Path, body: bytes) -> None:
        """Create `path` with `body` in it, exclusively, or raise `FileExistsError`.

        `O_EXCL` is the atomic step: of two dispatchers arriving together, the
        kernel lets exactly one create the file. The record goes out in a single
        write immediately after, so the only content another process can find in
        `path` is a whole one.
        """
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _LOCK_MODE)
        try:
            os.write(fd, body)
        finally:
            os.close(fd)

    def _abandoned(self, holder: tuple[int, datetime] | None) -> bool:
        """Whether `holder` can be proven gone, so its file may be taken over.

        None counts as proof: a file that names no readable holder is a dispatcher
        that died between creating and writing it, or one truncated by a full disk,
        and neither is anybody to wait for. A live holder is waited for until its lock
        is older than twice this job's own timeout, at which point it is presumed to
        have never come back rather than to be working for twice its own limit.
        """
        if holder is None:
            return True
        pid, started_at = holder
        if not _alive(pid):
            return True
        return datetime.now(UTC) - started_at > timedelta(seconds=self._job.timeout * _STALE_TIMEOUTS)

    def _refused(self, holder: tuple[int, datetime] | None) -> LockUnavailable:
        """The refusal to raise, naming the holder where the file names one."""
        pid, started_at = _NO_HOLDER if holder is None else holder
        held_by = (
            f"pid {pid} since {started_at.isoformat()}"
            if holder
            else f"an unidentified holder in {lock_path(self._job)}"
        )
        return LockUnavailable(f"job {self._job.name} is already running: held by {held_by}", pid, started_at)
