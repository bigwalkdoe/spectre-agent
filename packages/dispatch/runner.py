"""Run one action as a subprocess, and record what it did.

Dispatch is the only place in Spectre that deliberately runs code Spectre did not
write, so this module exists for the two ways that goes wrong: an action that does
not stop, and an action that talks too much.

Not stopping is the timeout's job, and the kill it sends is aimed at the *process
group* rather than the direct child. Actions are shell scripts, and shell scripts
start processes — a backgrounded download, a `systemctl restart` that forked, a
subshell left mid-`sleep`. Signalling only the child would let all of that keep
running after the scheduler had recorded the job as timed out, which is the worst
of both worlds: work nobody is watching, and a record claiming it was stopped. The
action is therefore spawned with `start_new_session=True`, so it leads its own
group that one signal can reach whole — SIGTERM first, to let a script that tidies
up after itself do so, and then SIGKILL, because a script that ignores SIGTERM must
not outlive its own timeout.

Talking too much is the envelope's job, and this module does not take it on: every
record goes through `build_envelope`, so the output bound and the payload fence
cannot be bypassed by assembling fields here. What it must not do is *hand* it
something unbounded — an action that echoes for its whole timeout is bounded by
`truncate_output` only after the fact, which is no bound at all while the string is
being built — so both pipes are drained by their own threads into a buffer that
holds the same head-and-tail window from the first line on. What it must not do
either is discard what it read, because a timed-out action is exactly the run whose
output explains itself: the head says what it was doing and the tail is where it
says so.

A run is never an exception. A non-zero exit, a timeout, and a script that printed
`error` and exited zero are all ordinary outcomes of code this process does not
control, and the caller's problem is the record rather than an error to catch.
Failing to *dispatch* is the other matter entirely — a missing action, one that
resolves outside the checkout — and that is `resolve`'s to raise, before anything
is executed.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import IO, cast

from packages.dispatch.envelope import (
    _MAX_MARKER_LEN,
    OUTPUT_LIMIT,
    Envelope,
    Status,
    _byte_len,
    _marker,
    build_envelope,
    status_for_exit_code,
)
from packages.dispatch.resolve import ResolvedAction

# How long a timed-out process group has to exit on SIGTERM before SIGKILL. Long
# enough for a script's own trap to run, short enough that a scheduled job is not
# held up by one that ignores it.
_TERM_GRACE_SECONDS = 2.0

# How long each pipe is drained after the group is gone. A writer that escaped the
# group — one that gave itself a session — would otherwise hold the read end open
# forever, and the drain would cost more than the timeout it was recording.
_DRAIN_GRACE_SECONDS = 2.0

# Bytes kept at each end of a stream that outruns the limit. `envelope`'s own window
# arithmetic, imported rather than re-derived: the bound applied while reading and
# the bound the record applies afterwards have to be the same bound, or the elision
# marker could describe a cut the record never makes.
_WINDOW = (OUTPUT_LIMIT - _MAX_MARKER_LEN) // 2


class _BoundedOutput:
    """One output stream, held to `OUTPUT_LIMIT` bytes while it is being read.

    A stream within the limit is kept whole, because that is what an ordinary
    action's record has always held and nothing about bounding it may change. One
    that outruns the limit keeps its first `_WINDOW` bytes and its last `_WINDOW`,
    counted and dropped between them: the head says what the action was doing, the
    tail is where it explains itself, and a payload fence survives only because the
    tail runs to the very end of the stream — `parse_payload` requires the fence to
    be the last thing the action printed.

    Nothing held here grows with the stream, which is the whole point: an action
    that echoes for its whole timeout is bounded by this rather than by whatever
    memory the host has spare, and the marker's count stays exact because it is
    taken from what the reader really saw. One exception, a line longer than the
    limit, which a reader splitting on newlines hands over whole — bounded by the
    action rather than by time, and the same property the one-shot truncation had.
    """

    def __init__(self) -> None:
        self._head = b""
        self._after = bytearray()
        self._total = 0

    def write(self, text: str) -> None:
        """Take the next piece of the stream, whatever its size."""
        data = text.encode("utf-8", "ignore")
        self._total += len(data)

        room = _WINDOW - len(self._head)
        if room > 0:
            self._head += data[:room]
            data = data[room:]
        self._after += data

        # Nothing is dropped while the stream still fits the limit. Past it, only
        # the last window survives: the head is already full, and everything between
        # the two windows is what the marker counts.
        excess = len(self._after) - _WINDOW
        if self._total > OUTPUT_LIMIT and excess > 0:
            del self._after[:excess]

    def text(self) -> str:
        """The stream as the record should receive it."""
        if self._total <= OUTPUT_LIMIT:
            return (self._head + bytes(self._after)).decode("utf-8", "ignore")
        head = self._head.decode("utf-8", "ignore")
        tail = bytes(self._after).decode("utf-8", "ignore")
        # Counted from what survives rather than from the cut points, as
        # `truncate_output` does it: a cut inside a multi-byte character must not
        # make the marker claim more than is really missing.
        elided = self._total - _byte_len(head) - _byte_len(tail)
        return f"{head}{_marker(elided)}{tail}"


@dataclass(frozen=True)
class RunOutcome:
    """One finished run: its record, and the exit code it ended with.

    `returncode` is None for a timeout, because a timed-out action never reached an
    exit code and reporting the signal that killed it in this field would let a
    caller mistake a kill for a verdict. The verdict is `envelope.status`.
    """

    envelope: Envelope
    returncode: int | None


def _pump(stream: IO[str], sink: _BoundedOutput) -> None:
    """Feed every line `stream` yields to `sink`, until its writer closes it.

    One thread per stream, each with its own sink: the sinks are read only after
    both threads have been joined, so there is exactly one writer each and no lock
    to hold.
    """
    with contextlib.closing(stream):
        for line in stream:
            sink.write(line)


def _reader(stream: IO[str], sink: _BoundedOutput) -> threading.Thread:
    """A thread draining `stream` into `sink`.

    A daemon thread, so that a writer which outlives the kill cannot keep the
    dispatcher alive at exit.
    """
    return threading.Thread(target=_pump, args=(stream, sink), daemon=True)


def _signal_group(proc: subprocess.Popen[str], sig: signal.Signals, grace: float) -> bool:
    """Signal the action's whole process group, then wait out `grace` for it.

    True once the action is gone, false if it is still running. The group is
    signalled rather than the child so that everything the action started stops
    with it; only the child is waited for, since the rest of the group is not this
    process's to reap.
    """
    pgid = os.getpgid(proc.pid)
    # The action is spawned into its own session, so its group is never this
    # process's — but that is a fact about the call to `Popen` and not about this
    # function, and the two are edited apart. Were it ever false, `killpg` would
    # signal the dispatcher itself and every timeout would be a self-inflicted
    # restart, so the child is signalled on its own instead.
    whole_group = pgid != os.getpgid(0)
    try:
        if whole_group:
            os.killpg(pgid, sig)
        else:
            proc.send_signal(sig)
    except ProcessLookupError:
        # Nothing left in the group: it exited between the timeout and this signal.
        return True
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        return False
    return True


def _stop(proc: subprocess.Popen[str]) -> None:
    """Stop a timed-out action and every process it started.

    Every path ends in a `wait` that returns, so the child is reaped rather than
    left as a zombie for the next timeout to add to — SIGKILL cannot be ignored,
    which is what makes that true of the second path too.
    """
    if _signal_group(proc, signal.SIGTERM, _TERM_GRACE_SECONDS):
        return
    _signal_group(proc, signal.SIGKILL, _TERM_GRACE_SECONDS)


def run_action(
    resolved: ResolvedAction,
    args: list[str],
    trigger: str,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> RunOutcome:
    """Run `resolved`'s action and record the run.

    `args` is passed straight to the action, and `env` overlays the environment this
    process was started with rather than replacing it — a caller passing one
    variable must not take `PATH` away from every action.

    `timeout` is seconds, and None means no timeout at all: `Job.timeout` is the
    caller's to pass, and a limit invented here would truncate a long action and
    report the dispatcher's guess in a field that reads as the action's own
    outcome. On expiry the action's process group is stopped and the run is
    recorded as a timeout with no exit code, keeping whatever output it produced
    before the deadline.
    """
    started_at = datetime.now(UTC)
    started = time.monotonic()

    proc = subprocess.Popen(
        args=[str(resolved.path), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # Explicitly UTF-8 with substitution, because output arrives from code
        # nothing here controls: a locale-dependent decode would vary between
        # hosts, and a strict one would drop the whole stream of an action that
        # wrote a stray byte — losing the output that explains the run.
        encoding="utf-8",
        errors="replace",
        # The action leads its own process group and session, which is what makes a
        # timeout able to stop everything it started rather than just the child.
        start_new_session=True,
        env={**os.environ, **(env or {})},
    )

    stdout_sink = _BoundedOutput()
    stderr_sink = _BoundedOutput()
    # Both pipes were requested above, so neither is None; the cast says it once
    # here rather than as a guard inside every reader.
    readers = [
        _reader(cast("IO[str]", proc.stdout), stdout_sink),
        _reader(cast("IO[str]", proc.stderr), stderr_sink),
    ]
    for reader in readers:
        reader.start()

    try:
        returncode = proc.wait(timeout=timeout)
        status = status_for_exit_code(returncode)
    except subprocess.TimeoutExpired:
        returncode, status = None, Status.TIMEOUT
        # Timed to the deadline rather than to the end of the kill below: the grace
        # is the dispatcher's cleanup, not time the action spent running, and
        # including it would make two identical timeouts record differently
        # depending on whether the script trapped SIGTERM.
        duration_ms = int((time.monotonic() - started) * 1000)
        _stop(proc)
    else:
        duration_ms = int((time.monotonic() - started) * 1000)

    for reader in readers:
        reader.join(_DRAIN_GRACE_SECONDS)

    return RunOutcome(
        envelope=build_envelope(
            resolved=resolved,
            trigger=trigger,
            started_at=started_at,
            duration_ms=duration_ms,
            exit_code=returncode,
            stdout=stdout_sink.text(),
            stderr=stderr_sink.text(),
            status=status,
        ),
        returncode=returncode,
    )
