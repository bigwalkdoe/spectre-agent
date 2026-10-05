"""Tests for running an action as a subprocess and recording the run.

Every test writes its action into `tmp_path` and points `SPECTRE_ACTIONS_ROOT`
there, so nothing here executes the host's own maintenance suite. The actions are
real shell scripts and are really executed: this module's whole job is process
handling — signals, process groups, pipes — and a stubbed `subprocess` would test
the stub instead. The session-wide stub in `tests/conftest.py` deliberately does
not reach `packages.dispatch`.

The timeout cases cost real wall-clock time, because the scripts have to actually
sleep for a timeout to be the thing under test.
"""

from __future__ import annotations

import os
import re
import stat
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from packages.dispatch.envelope import OUTPUT_LIMIT
from packages.dispatch.resolve import resolve
from packages.dispatch.runner import RunOutcome, _BoundedOutput, run_action
from tests.dispatch.conftest import make_job

# The elision notice Task 3 established, matched rather than rebuilt so that a change
# to its wording shows up here as a failure instead of as a silent mismatch.
_MARKER = re.compile(r"\n\.\.\. \[(\d+) bytes elided\] \.\.\.\n")


def _write(root: Path, name: str, body: str) -> None:
    """Write an executable action: `write_text` alone leaves 0o644, and dispatch
    refuses a non-executable action, so a fixture that skips the chmod fails on the
    wrong check."""
    p = root / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(root: Path, name: str, body: str, **kw: Any) -> RunOutcome:
    """Write `body` as the action `name` and run it as the whole job."""
    _write(root, name, body)
    return run_action(resolve(make_job(name)), [], trigger="cli", **kw)


def test_success_records_stdout_and_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "ok.sh", "#!/bin/bash\necho hello\nexit 0\n")
    assert got.returncode == 0
    assert got.envelope.status.value == "success"
    assert "hello" in got.envelope.stdout_tail


def test_failure_is_recorded_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "bad.sh", "#!/bin/bash\necho boom >&2\nexit 2\n")
    assert got.returncode == 2
    assert got.envelope.status.value == "failed"
    assert "boom" in got.envelope.stderr_tail


def test_envelope_carries_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _write(tmp_path, "ok.sh", "#!/bin/bash\nexit 0\n")
    got = run_action(resolve(make_job("ok.sh")), [], trigger="cron")
    assert got.envelope.trigger == "cron"
    assert got.envelope.resolved_path.endswith("ok.sh")
    assert got.envelope.git_commit == resolve(make_job("ok.sh")).git_commit


def test_timeout_kills_the_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 4: a script's own children must die with it.

    The action backgrounds a grandchild that writes a marker two seconds in, then
    sleeps far longer than the timeout. A kill that reaches only the direct child
    leaves the grandchild alive to finish its work and write that marker, which is
    the failure this test exists to catch — the scheduler has recorded a timeout
    while the work it was meant to stop carries on unobserved.

    `started` is the guard against passing for the wrong reason: it proves the
    grandchild was really up before the timeout fired, so a missing marker means it
    was killed rather than never spawned. It also dates the fork, which is what
    makes the short waits decisive — the grandchild would have written the marker
    within a second of `run_action` returning, well before the assertion reads it.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    marker = tmp_path / "grandchild.txt"
    started = tmp_path / "grandchild_started.txt"
    body = f"#!/bin/bash\n( sleep 2; touch {marker} ) &\ntouch {started}\nsleep 30\n"
    got = _run(tmp_path, "slow.sh", body, timeout=1)

    assert got.envelope.status.value == "timeout"
    assert got.returncode is None
    assert started.exists(), "the grandchild never started, so the kill proved nothing"
    time.sleep(3)
    assert not marker.exists(), "grandchild survived the timeout kill"


def test_timeout_keeps_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A timed-out action is the one whose output explains itself, so what it wrote
    before the deadline belongs in the record.

    Three seconds, not one: the timeout starts counting at `Popen`, so on a loaded CI
    runner a second can be gone before bash has even reached its `echo`, and the
    failure would read as "output was lost" rather than "the machine was busy".
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "slow.sh", "#!/bin/bash\necho started\nsleep 30\n", timeout=3)
    assert "started" in got.envelope.stdout_tail


def test_a_timeout_escalates_to_sigkill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SIGTERM is a request, not a guarantee, and an action may refuse it: a script
    that traps TERM has to be stopped anyway, or the record says "timeout" while the
    action carries on — the exact orphan this task's review focus is about. The trap
    is inherited by the `sleep`, so the whole group ignores SIGTERM and only the
    escalation ends it.

    The envelope cannot tell a stopped action from a stubborn one — both are recorded
    as a timeout — so the action is asked directly, and its pid is the thing that
    proves it got going: a pid that no longer exists is what a kill leaves behind. A
    missing `pid.txt` fails loudly as a missing file rather than as a lost kill.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    pid_file = tmp_path / "pid.txt"
    body = f"#!/bin/bash\ntrap '' TERM\necho started\necho $$ > {pid_file}\nsleep 30\n"
    got = _run(tmp_path, "stubborn.sh", body, timeout=1)

    assert got.envelope.status.value == "timeout"
    assert got.returncode is None
    assert "started" in got.envelope.stdout_tail
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_exit_code_survives_a_huge_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 2 continued: truncation must not lose the verdict."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    body = "#!/bin/bash\nfor i in $(seq 1 20000); do echo line$i; done\nexit 7\n"
    got = _run(tmp_path, "loud.sh", body)
    assert got.returncode == 7
    assert got.envelope.status.value == "failed"
    assert "elided" in got.envelope.stdout_tail


def test_args_are_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _write(tmp_path, "ok.sh", '#!/bin/bash\necho "arg=$1"\n')
    got = run_action(resolve(make_job("ok.sh")), ["--apply"], trigger="cli")
    assert "arg=--apply" in got.envelope.stdout_tail


# What bounding the reader costs and buys. The bound the record applies in
# `build_envelope` is no bound at all while the string is being built, so the runner
# keeps the same window from the first line on. The tests below pin that the window
# changes nothing for an action that stays inside it, and that it costs nothing of
# what explains a run that does not.


def _lines(count: int) -> str:
    """`count` lines of 40 bytes, the shape a looping `echo` actually produces."""
    return "".join(f"{i:012d} abcdefghijklmnopqrstuvwxyz\n" for i in range(count))


def _emit_lines(count: int) -> str:
    """A script printing the same `count` lines `_lines` would have produced."""
    return f'#!/bin/bash\nfor ((i=0;i<{count};i++)); do printf "%012d abcdefghijklmnopqrstuvwxyz\\n" "$i"; done\n'


def test_output_within_the_limit_reaches_the_record_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Just inside the limit, every byte survives and no marker appears: bounding the
    reader must not become an excuse to elide a run that never overran.

    1638 lines of 40 bytes is 65520, sixteen under `OUTPUT_LIMIT`.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "chatty.sh", _emit_lines(1638))
    assert got.envelope.status.value == "success", got.envelope.stderr_tail
    assert got.envelope.stdout_tail == _lines(1638)
    assert "elided" not in got.envelope.stdout_tail


def test_output_over_the_limit_is_bounded_and_keeps_both_ends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the limit the record stops growing, and what it keeps is the two ends:
    the head for what the action was doing, the tail for how it ended. The tail runs
    to the last byte, which is what a payload fence needs to survive."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "loud.sh", _emit_lines(4000))
    tail = got.envelope.stdout_tail

    assert len(tail.encode()) <= OUTPUT_LIMIT
    assert tail.startswith("000000000000 abcdefghijklmnopqrstuvwxyz\n")
    assert tail.endswith("000000003999 abcdefghijklmnopqrstuvwxyz\n")


def test_the_elision_marker_counts_what_it_actually_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The marker states how many bytes went missing, so a short output and an elided
    one cannot be mistaken for each other. Exactly one of them: the bound belongs
    once, and a second marker means the runner bounded the stream and then the
    envelope bounded it again, each cut counted against a window that was already
    spent.

    Checked as `elided + shown == printed` rather than against a re-derived window,
    so the test cannot drift from the arithmetic it is checking.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    printed = len(_lines(4000).encode())
    got = _run(tmp_path, "loud.sh", _emit_lines(4000))

    found = list(_MARKER.finditer(got.envelope.stdout_tail))
    assert len(found) == 1, f"expected one elision marker, found {len(found)}"
    shown = len(got.envelope.stdout_tail.encode()) - len(found[0].group(0).encode())
    assert int(found[0].group(1)) + shown == printed


def test_a_payload_fence_survives_an_overrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fence with a quarter of a megabyte in front of it: the bounded buffer
    keeps the *end* of the stream at full fidelity, which is the only reason
    `parse_payload` can still read it. Without the tail window the fence would be
    dropped along with the middle and this action's structured result would vanish."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    body = _emit_lines(4000) + "printf '```spectre\\n{\"removed\": 3}\\n```\\n'\n"
    got = _run(tmp_path, "report.sh", body)

    assert got.envelope.payload == {"removed": 3}
    assert "elided" in got.envelope.stdout_tail


def test_one_enormous_line_is_bounded_and_keeps_its_true_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty megabytes with no newline in it at all: a `base64` with its wrapping
    turned off, a `curl` of a binary blob. A reader splitting on newlines holds all
    of it before handing over a byte, which is the unbounded read the buffer exists to
    prevent — so the reader is measured here, not just the record, which looks the
    same either way once `truncate_output` has had its turn.

    Eight megabytes of threshold against the 430 KB this reader is measured to use,
    and against the 60 MB a line-splitting one is measured to hold: an action that
    chooses not to emit a newline is not a reason for the dispatcher to grow without
    limit.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    body = "#!/bin/bash\nhead -c 20000000 /dev/zero | tr '\\0' 'x'\nprintf 'THE-END'\n"

    tracemalloc.start()
    try:
        got = _run(tmp_path, "blob.sh", body)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    tail = got.envelope.stdout_tail
    assert got.envelope.status.value == "success", got.envelope.stderr_tail
    assert len(tail.encode()) <= OUTPUT_LIMIT
    # The last bytes the action actually wrote. A payload fence survives only because
    # this tail is the true end of the stream, so a tail cut short at one of the
    # reader's own boundaries would fail here first.
    assert tail.endswith(f"{'x' * 64}THE-END")
    assert peak < 8_000_000, f"the reader held {peak} bytes of a 20 MB line"


def test_the_buffer_does_not_grow_with_the_stream() -> None:
    """The bound has to hold while the stream is read, not once it is over: an action
    that echoes for its whole timeout would otherwise grow the dispatcher until
    something OOM-killed it, with nothing here noticing.

    Measured on the buffer rather than through a subprocess, because peak allocation
    is the claim and the process's RSS is not measurable to that precision here. 20 MB
    through the buffer, and less than 4 MB of it may survive the trip.
    """
    buffer = _BoundedOutput()
    tracemalloc.start()
    try:
        for _ in range(200):
            buffer.write("x" * 100_000)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 4_000_000, f"retained {peak} bytes of a 20 MB stream"
    assert len(buffer.text().encode()) <= OUTPUT_LIMIT


def test_env_merges_over_the_parent_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An action's interpreter is found by an absolute shebang, so a caller who
    passed `env` as a replacement rather than an overlay would lose nothing visible
    until the script reached for any other command at all. `seq` is that command.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    body = '#!/bin/bash\necho "foo=$FOO"\nseq 1 1\n'
    got = _run(tmp_path, "env.sh", body, env={"FOO": "bar"})
    assert "foo=bar" in got.envelope.stdout_tail
    assert got.envelope.status.value == "success", got.envelope.stderr_tail


def test_no_timeout_is_imposed_when_none_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The job's own `timeout` is the caller's to pass, not this module's to
    invent: a default applied here would silently cut off a long action, and the
    record would report the dispatcher's guess rather than a failure.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "slow.sh", "#!/bin/bash\necho finished\nsleep 2\n")
    assert got.envelope.status.value == "success", got.envelope.stderr_tail
    assert "finished" in got.envelope.stdout_tail


def test_a_payload_fence_from_the_action_reaches_the_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The record is built through `build_envelope`, so the whole of what the action
    printed is what reaches the fence parser. `test_envelope` proves the parser on
    strings it is handed; this proves the runner hands it the real thing — a
    refactor that bounded the output before building the envelope would break the
    payload and pass every other test here.
    """
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    body = "#!/bin/bash\necho working\nprintf '```spectre\\n{\"removed\": 3}\\n```\\n'\n"
    got = _run(tmp_path, "report.sh", body)
    assert got.envelope.payload == {"removed": 3}
    assert "working" in got.envelope.stdout_tail
