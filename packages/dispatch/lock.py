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
job's own timeout, which is a holder that never came back.

A file that names no readable holder is a third case, and it is treated as neither.
`O_CREAT | O_EXCL` creates the file empty and the record follows in the next
write, so an empty or unparseable file is ambiguous between a dispatcher that has
claimed it and one that died having done so — and guessing wrong in that direction
takes two mutating jobs at once, which is the single outcome this module exists to
prevent. So it is *refused*, carrying the pid `0` that names no process and the
file's own mtime as the only evidence there is of when it appeared. No liveness
question is asked of it, because there is no pid to ask about. It becomes
reclaimable on the age rule alone once it is older than twice the timeout: refused
while the reading is ambiguous, reclaimed once it is not.

Reclaiming is tried *once* wherever it happens at all: an unbounded reclaim loop
against a lock that keeps being re-created is a livelock, and a lock that cannot
be reclaimed must fail loudly rather than spin.

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

# The shortest staleness window any job may be judged by, in seconds. `registry.py`
# validates `timeout` as an int and not as a positive one, and this module must not
# lean on registry having validated its input: at `timeout = 0` the window would be
# zero seconds, every lock would read as abandoned, and the lock would exclude
# nothing at all — a silent fail-open, the opposite of what this module is for. So a
# job whose timeout is unusable is judged by this floor instead, which keeps
# exclusion working and keeps reclaiming its lock slow. That is cheap here because a
# `timeout` of zero is not a run that lasts: `run_action` enforces it as a deadline
# and stops the action on it immediately.
_MIN_TIMEOUT_SECONDS = 60

# A lock file is created 0o600: it is per-user state, and no other account needs
# to read it. The mode is still masked by the umask, which can only narrow this.
_LOCK_MODE = 0o600

# The pid reported for a lock file that names no holder. 0 is not a process any
# dispatcher can have, so nothing reading this file can mistake it for one — and it
# never reaches `_alive`, because there is no process there to ask the kernel about.
_UNKNOWN_PID = 0

# The `started_at` fallback for the one case the refusal cannot evidence: the file
# disappeared between being judged and being named. Everything else reports when
# the file actually appeared.
_EPOCH = datetime.fromtimestamp(0, UTC)


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
    describe a holder. The caller gives those three different answers — a missing
    file is a free job, an unreadable one is an ambiguity to refuse — so what None
    means is left here rather than decided in one place: it says only that no holder
    is named. Nothing is guessed: a `pid` that is not an integer and a `started_at`
    without a timezone are both refused, since an instant that cannot be compared
    against a timeout would let a file this dispatcher did not write decide when its
    job may run again.
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


def _filed_at(path: Path) -> datetime | None:
    """When `path` was last written, or None if it is no longer there.

    The one piece of evidence an unreadable lock file offers about itself, and the
    only thing its age can be judged from.
    """
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None


def _alive(pid: int) -> bool:
    """Whether `pid` is a process this host still has.

    `PermissionError` means yes: the process exists and belongs to another user,
    which for an action running under sudo is the ordinary answer, and the opposite
    reading would reclaim a live lock.

    `OverflowError` means no. `os.kill` raises it rather than `ProcessLookupError`
    for any pid above 2**31, so it has to be caught here or it escapes as a traceback
    instead of a refusal — and, worse, escapes before the age rule is ever consulted,
    which leaves that lock file unreclaimable by anyone and blocks the job until it is
    deleted by hand. No Linux pid reaches 2**31, so such a value names no real
    process: reading it as dead sends it down the ordinary abandoned-lock path, the
    one an unreadable file takes as well.

    A pid that is not positive names no process this can verify either — `kill` reads
    0 and a negative pid as "my process group" and "every process I may signal" — and
    the only such pid reported anywhere is the `_UNKNOWN_PID` of an unreadable file,
    which is refused on its age before any liveness question about it arises.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False
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
        # Where the lock was claimed, remembered rather than recomputed: `lock_path`
        # reads `SPECTRE_CONFIG_DIR` at call time, so a config directory that differed
        # between the claim and the release would leave `release` reading a lock file
        # this process never wrote, failing to match its own pid, and leaking the real
        # one until the age rule noticed. Only set by a successful claim, which keeps
        # an allow-concurrency job from resolving a path it will never use.
        self._path: Path | None = None

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
            if not self._abandoned(holder, path):
                raise self._refused(holder, path) from None
            # Judged abandoned: a holder that is gone, or a lock older than this job
            # may ever run. Remove the file and claim it again — once, because the
            # retry is the end of the line, not a loop.
            path.unlink(missing_ok=True)
            try:
                self._claim(path, body)
            except FileExistsError:
                raise self._refused(read_lock(path), path) from None

        self._path = path
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

        # The path recorded at the claim, never recomputed: see `_path`.
        path = self._path
        if path is None:
            return
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

    def _abandoned(self, holder: tuple[int, datetime] | None, path: Path) -> bool:
        """Whether `path` can be proven abandoned, so its lock may be taken over.

        A holder that named itself is judged by liveness and by age: a pid that is
        gone is a dispatcher that was killed, and a lock older than twice this job's
        own timeout belongs to a holder that never came back rather than to one
        working for twice its own limit.

        A file that named nobody is judged by age alone, and only by age. It has no
        pid, so there is nothing to signal, and reclaiming it on that ground would be
        guessing: the window between the exclusive create and the write leaves a file
        that is empty for as long as one `write` takes, and a second dispatcher
        arriving in it must wait rather than run the job alongside the first. Age is
        what settles it — young is ambiguous, old is abandoned — and a file that has
        since been deleted is nothing to wait for at all.
        """
        if holder is None:
            appeared = _filed_at(path)
            return appeared is None or self._too_old(appeared)
        pid, started_at = holder
        return not _alive(pid) or self._too_old(started_at)

    def _too_old(self, started_at: datetime) -> bool:
        """Whether a lock taken at `started_at` is older than this job may ever run.

        Bounded below by `_MIN_TIMEOUT_SECONDS`, so a job whose registry entry carries
        a non-positive timeout still excludes concurrent runs instead of treating every
        lock it holds as abandoned the instant it is written.
        """
        window = timedelta(seconds=max(self._job.timeout, _MIN_TIMEOUT_SECONDS) * _STALE_TIMEOUTS)
        return datetime.now(UTC) - started_at > window

    def _refused(self, holder: tuple[int, datetime] | None, path: Path) -> LockUnavailable:
        """The refusal to raise: naming the holder where the file names one, and the
        file where it does not."""
        if holder is None:
            return LockUnavailable(
                f"job {self._job.name} is already running: the holder of {path} cannot be determined "
                f"(unreadable lock file — is a run in flight?)",
                _UNKNOWN_PID,
                _filed_at(path) or _EPOCH,
            )
        pid, started_at = holder
        return LockUnavailable(
            f"job {self._job.name} is already running: held by pid {pid} since {started_at.isoformat()}",
            pid,
            started_at,
        )
