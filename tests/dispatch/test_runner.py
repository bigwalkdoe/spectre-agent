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

import stat
import time
from pathlib import Path
from typing import Any

import pytest

from packages.dispatch.resolve import resolve
from packages.dispatch.runner import RunOutcome, run_action
from tests.dispatch.conftest import make_job


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
    before the deadline belongs in the record."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    got = _run(tmp_path, "slow.sh", "#!/bin/bash\necho started\nsleep 30\n", timeout=1)
    assert "started" in got.envelope.stdout_tail


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
