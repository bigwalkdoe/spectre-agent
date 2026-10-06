"""Tests for `spectre run` and `spectre actions`, the dispatch CLI surface.

The exit codes are this module's real subject, because they are the CLI's only
contract with cron: `0` success, `2` unknown job, `3` not dispatchable, `4`
another run holds the lock, `5` the run failed or timed out. Each of those is
pinned below against a real action, a real registry entry and a real lock file —
nothing here stubs the runner, the resolver or the lock, because every one of
those decisions is made here and stubbing them would test the stub.

Three of these tests exist because the naive version of them would have passed
for the wrong reason, and are commented where that is true:

* a failing action is `backups/backup-all` with its script overwritten, not a
  `backups/backup-fail` job — that name is not in the 61-job registry, so asking
  for it exits `2` (unknown job) and a test expecting `5` would go green on a
  refusal;
* the timeout test replaces a real registry entry's `timeout` with `1` rather
  than inventing a job, because the claim under test is that the CLI passes
  `Job.timeout` through, and only a real entry can carry the other fields that
  decide what happens around it;
* the sudo tests pin a refusal that runs nothing, so a "sudo job ran as an
  unprivileged user" regression cannot pass as a success.

Hermeticity: `SPECTRE_ACTIONS_ROOT` points at a per-test `tmp_path` holding only
the scripts written here, and `SPECTRE_CONFIG_DIR` at a per-test directory so
lock files never touch a real tree or each other. The run records go to the
session-wide throwaway database `tests/conftest.py` installed before
`packages.memory.db` was imported. Nothing here reaches the host's own actions,
crontab, systemd or `~/.config/spectre`.
"""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import apps.cli.dispatch_cmds as dispatch_cmds
from apps.cli.dispatch_cmds import EXIT_FAILED, EXIT_LOCKED, EXIT_NOT_DISPATCHABLE, EXIT_OK, EXIT_UNKNOWN_JOB
from apps.cli.main import app
from packages.dispatch import registry
from packages.dispatch.lock import lock_path
from packages.dispatch.verify import ALL_CODES, HostInventory
from packages.memory.db import recent_runs

runner = CliRunner()


@pytest.fixture(autouse=True)
def _the_host_is_not_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make reading the real crontab or systemd units impossible in this file.

    `spectre actions verify` is the first command here that reads the host at all,
    and it would do so on whatever machine runs the suite: a test would then pass
    or fail depending on that machine's units, and would read an operator's
    schedulers without asking. Every test below injects an inventory through
    `_host` instead; this makes forgetting impossible to miss rather than merely
    unlikely, in the same way it does in `tests/dispatch/test_verify.py`.
    """

    def forbidden() -> HostInventory:
        raise AssertionError("a test called read_host_inventory(); use _host(...) to inject an inventory")

    monkeypatch.setattr(dispatch_cmds.verify_mod, "read_host_inventory", forbidden)


def _host(monkeypatch: pytest.MonkeyPatch, inventory: HostInventory) -> None:
    """Give the `verify` command a `HostInventory` instead of the real host."""
    monkeypatch.setattr(dispatch_cmds.verify_mod, "read_host_inventory", lambda: inventory)


# A real registry job with sudo=false and concurrency=forbid, so the lock is
# exercised by the ordinary success and failure paths as well as by their own
# tests. `backups/backup-databases` is the other such job: never written by the
# fixture, which is what makes it the missing-action case.
JOB = "backups/backup-all"
MISSING_JOB = "backups/backup-databases"

# A real registry job with sudo=true *and* concurrency=forbid, so the sudo
# refusal and the lock-release-on-refusal assertions have a job that would
# otherwise have left a lock file behind.
SUDO_JOB = "security/run-security-hardening"


def _write(root: Path, name: str, body: str, executable: bool = True) -> Path:
    """Write an action under the actions root and make it executable.

    `write_text` alone leaves 0o644, and `resolve` refuses a non-executable
    action, so a fixture that skips the mode would fail on the wrong check.
    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway actions root holding only `JOB`'s script, plus a per-test config dir.

    The config directory is what `JobLock` reads at call time, so pointing it at
    `tmp_path` is what keeps one test's lock file out of the next one's way.
    """
    root = tmp_path / "actions"
    _write(root, "backups/backup-all.sh", "#!/bin/bash\necho backed up\nexit 0\n")
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(root))
    monkeypatch.setenv("SPECTRE_CONFIG_DIR", str(tmp_path / "cfg"))
    return root


def _rows(job: str) -> list[int | None]:
    """The ids of `job`'s run records, newest first.

    Ids rather than whole rows because every use of this is a before/after
    comparison: the question a refusal or a lock has to answer is "did a record
    appear?", and comparing the id set says that without depending on what the row
    contains.
    """
    return [r.id for r in recent_runs(job=job, limit=20) if r.action == job]


def _listing(stdout: str) -> dict[str, dict[str, str]]:
    """`spectre actions list` output as `{job: {column: cell}}`, keyed by header.

    The column *name* is read out of the header row rather than assumed, so a
    column that is renamed or reordered turns into a missing key here instead of
    silently comparing the wrong cell — which is exactly how the previous version of
    the sudo test came to pass against swapped columns.

    `maxsplit` leaves the schedule hint whole: `0 2 * * 6` is five whitespace-
    separated words, and splitting it across cells would make every job's schedule
    look like a mangled one.
    """
    lines = [line for line in stdout.splitlines() if line.strip()]
    headers = lines[0].split()
    table: dict[str, dict[str, str]] = {}
    for line in lines[1:]:
        cells = line.split(maxsplit=len(headers) - 1)
        row = dict(zip(headers, cells, strict=True))
        table[row["job"]] = row
    return table


# ── spectre run ──────────────────────────────────────────────────────────────


def test_run_executes_and_echoes_its_output(actions: Path) -> None:
    """The action's output reaches the operator.

    Not streamed live: the runner bounds both streams to the envelope's
    head-and-tail window while it reads them, so what the CLI prints is the same
    bounded text a run record keeps. Printing it is still the point — a run whose
    output went nowhere is indistinguishable from a run that never happened.
    """
    result = runner.invoke(app, ["run", JOB])
    assert result.exit_code == 0
    assert "backed up" in result.stdout


def test_run_unknown_job_exits_2(actions: Path) -> None:
    """`get_job` raises KeyError rather than returning None, so the CLI turns
    that into `unknown job` and exit 2 — never into a traceback, and never into a
    dispatch of something it guessed at."""
    result = runner.invoke(app, ["run", "backups/nope"])
    assert result.exit_code == 2
    assert "unknown job" in result.stdout


def test_run_unknown_job_records_nothing(actions: Path) -> None:
    before = _rows("backups/nope")
    runner.invoke(app, ["run", "backups/nope"])
    assert _rows("backups/nope") == before


def test_run_missing_action_exits_3(actions: Path) -> None:
    result = runner.invoke(app, ["run", MISSING_JOB])
    assert result.exit_code == 3
    assert MISSING_JOB in result.stdout


def test_run_non_executable_action_exits_3(actions: Path) -> None:
    """Executable, not merely present: a 0o644 action is refused the same way, and
    the reason names the file so the fix is obvious."""
    _write(actions, "backups/backup-databases.sh", "#!/bin/bash\nexit 0\n", executable=False)
    result = runner.invoke(app, ["run", MISSING_JOB])
    assert result.exit_code == 3
    assert "executable" in result.stdout


def test_run_missing_action_records_nothing(actions: Path) -> None:
    before = _rows(MISSING_JOB)
    runner.invoke(app, ["run", MISSING_JOB])
    assert _rows(MISSING_JOB) == before


def test_run_failure_exits_5_and_records(actions: Path) -> None:
    """A non-zero exit is `failed`, exit 5, and the record keeps the stderr tail.

    The action is the real `backups/backup-all` with its own script overwritten:
    there is no `backups/backup-fail` job, so dispatching one would exit 2 and
    this assertion would be green for a refusal rather than for a failure.
    """
    _write(actions, "backups/backup-all.sh", "#!/bin/bash\necho nope >&2\nexit 3\n")
    before = _rows(JOB)
    result = runner.invoke(app, ["run", JOB])
    assert result.exit_code == 5
    assert "nope" in result.stdout

    rows = recent_runs(job=JOB, limit=1)
    assert rows[0].id not in before
    assert rows[0].status == "failed"
    assert rows[0].exit_code == 3
    assert "nope" in (rows[0].stderr_tail or "")


def test_run_releases_the_lock_after_a_failure(actions: Path) -> None:
    """`JOB` is concurrency=forbid, so a failed run that kept its lock would
    block the next one for twice the timeout — the single failure mode the lock
    cannot be allowed to have."""
    _write(actions, "backups/backup-all.sh", "#!/bin/bash\nexit 3\n")
    assert runner.invoke(app, ["run", JOB]).exit_code == 5
    assert not lock_path(registry.get_job(JOB)).exists()


def test_run_lock_held_exits_4_and_names_the_holder(actions: Path) -> None:
    """Exit 4 names the holding pid and when it started, because "already
    running" is only actionable once you know by whom.

    The lock names this very process, which is alive, so it is a live holder by
    the same liveness test the lock itself uses — no extra process needed.
    """
    job = registry.get_job(JOB)
    started = datetime.now(UTC)
    path = lock_path(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "started_at": started.isoformat()}), encoding="utf-8")

    before = _rows(JOB)
    result = runner.invoke(app, ["run", JOB])

    assert result.exit_code == 4
    assert str(os.getpid()) in result.stdout
    assert started.isoformat() in result.stdout
    assert _rows(JOB) == before
    # The refusal must leave the real holder's lock exactly as it found it.
    assert path.exists()


def test_run_passes_the_job_timeout(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`run_action`'s `timeout=None` means *no timeout*, so a caller that forgets
    to pass `Job.timeout` produces a CLI that cannot stop a runaway action. Every
    registry job currently has `timeout=1800`, which is exactly why that mistake
    would stay invisible: it needs a different value to show up at all.

    A real registry entry is used with only `timeout` replaced, because the claim
    is about what the CLI reads off the entry, not about a job that does not exist.
    """
    _write(actions, "backups/backup-all.sh", "#!/bin/bash\nsleep 30\n")
    monkeypatch.setattr(
        registry,
        "JOBS",
        [replace(j, timeout=1) if j.name == JOB else j for j in registry.JOBS],
    )

    started = time.monotonic()
    result = runner.invoke(app, ["run", JOB])
    elapsed = time.monotonic() - started

    assert result.exit_code == 5
    # The action sleeps 30s and the job allows 1s. Elapsed is asserted as well as
    # the exit code because "it returned" and "it was stopped" are different claims.
    assert elapsed < 15
    row = recent_runs(job=JOB, limit=1)[0]
    assert row.status == "timeout"
    assert row.exit_code is None


def test_run_records_into_a_database_that_did_not_exist(
    actions: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host with no `memory.db` yet must still get a run record.

    Found by running the CLI, not by reading it: `save_run` inserts into
    `maintenancerecord`, and on a fresh config directory that table does not exist
    until something creates it, so the first `spectre run` on a fresh host died with
    `no such table: maintenancerecord` *after* the action had already run. Every
    other command in `main.py` calls `init_db()` first for the same reason, and a
    migrated host needs it too — `ensure_schema` is what adds the provenance columns
    to a table that predates them.

    The store is redirected at a file that does not exist rather than stubbed, so
    this is the real `init_db` and the real `save_run` writing a real database.
    """
    from sqlmodel import Session, create_engine, select

    from packages.memory import db as db_module

    fresh = tmp_path / "fresh-config" / "memory.db"
    fresh.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{fresh}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)

    assert runner.invoke(app, ["run", JOB]).exit_code == 0

    with Session(engine) as session:
        rows = list(session.exec(select(db_module.MaintenanceRecord)).all())
    assert [row.action for row in rows] == [JOB]
    assert rows[0].trigger == "cli"


def test_run_records_a_real_commit_when_actions_are_a_repo(actions: Path) -> None:
    """Full wiring: resolve -> provenance -> run record, against a real repository."""
    import subprocess

    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q"], cwd=actions, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=actions, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=actions, check=True, env=env)

    runner.invoke(app, ["run", JOB])
    row = recent_runs(job=JOB, limit=1)[0]
    expected = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=actions,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.strip()
    assert row.git_commit == expected
    assert row.git_dirty is False


def test_run_forwards_arguments(actions: Path) -> None:
    """Arguments after the job go to the action and are not parsed as spectre's
    own options — `--dry-run` is the action's flag, not spectre's."""
    _write(actions, "backups/backup-all.sh", '#!/bin/bash\necho "a=$1"\n')
    result = runner.invoke(app, ["run", JOB, "--", "--dry-run"])
    assert result.exit_code == 0
    assert "a=--dry-run" in result.stdout


def test_run_does_not_interpret_action_output_as_markup(actions: Path) -> None:
    """The app is built with rich markup, and an action's output is not spectre's
    to annotate: `[disk-full]` has to survive as the text the action wrote."""
    _write(actions, "backups/backup-all.sh", "#!/bin/bash\necho 'failed: [disk-full]'\n")
    result = runner.invoke(app, ["run", JOB])
    assert "[disk-full]" in result.stdout


def test_run_records_provenance(actions: Path) -> None:
    result = runner.invoke(app, ["run", JOB])
    assert result.exit_code == 0
    row = recent_runs(job=JOB, limit=1)[0]
    assert row.trigger == "cli"
    assert row.resolved_path.endswith("backups/backup-all.sh")
    # A plain tmp_path actions root is not a git repository, so provenance
    # degrades to empty rather than raising. Assert the degradation here; the
    # real git-reading path is pinned by tests/dispatch/test_resolve.py.
    assert row.git_commit == ""
    assert row.git_dirty is False


# ── groups: refused, but not called "unknown" ─────────────────────────────────

# Every name that is both a registered job and a group name, read from the registry
# at collection time so this stays honest if the registry changes: the collision set
# is a fact about the data, not a list someone has to remember to update.
COLLIDING_NAMES = sorted(set(registry.groups()) & {job.name for job in registry.JOBS})


def test_run_a_group_name_exits_2_saying_it_is_a_group(actions: Path) -> None:
    """A group is a real thing in the registry that `spectre run` cannot dispatch.

    Calling it "unknown" tells the operator their mental model of the CLI is wrong,
    when what is actually true is that a feature they saw in the design spec is
    missing. So the message names the group, says group running is not implemented,
    and points at the listing — and still exits 2, because nothing was dispatched.

    Every job in the group is given a script that would leave a marker, so "nothing
    ran" is checked rather than assumed: a partial group run is exactly the blast
    radius the deferral exists to avoid.
    """
    markers = []
    for job in registry.jobs_in_group("network"):
        marker = actions / f"ran-{job.name.replace('/', '-')}"
        _write(actions, job.action, f"#!/bin/bash\ntouch {marker}\n")
        markers.append(marker)

    result = runner.invoke(app, ["run", "network"])

    assert result.exit_code == 2
    assert "'network' is a group of 4 jobs" in result.stdout
    assert "Running a whole group is not implemented" in result.stdout
    assert "spectre actions list" in result.stdout
    assert not [m for m in markers if m.exists()]


def test_run_a_group_name_records_nothing(actions: Path) -> None:
    before = {job.name: _rows(job.name) for job in registry.jobs_in_group("network")}
    assert runner.invoke(app, ["run", "network"]).exit_code == 2
    assert {job.name: _rows(job.name) for job in registry.jobs_in_group("network")} == before


def test_actions_show_a_group_name_exits_2_saying_it_is_a_group(actions: Path) -> None:
    """`actions show` answers the same question the same way: the group explanation
    lives in the shared lookup, not in `spectre run`."""
    result = runner.invoke(app, ["actions", "show", "security"])
    assert result.exit_code == 2
    assert "'security' is a group" in result.stdout
    assert "not implemented" in result.stdout


def test_run_a_colliding_name_runs_the_job_and_says_so(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The job wins — it is the more specific reading — but the CLI says so.

    Silence here would be the worst available answer: `deploy-monitoring` is a job
    *and* a group, so an operator who meant the group would watch one job run, see
    its output, and have no hint that a group of the same name existed. With 45 of
    61 jobs mutating, that is a surprise with consequences.
    """
    _write(actions, "deploy-monitoring.sh", "#!/bin/bash\necho deploying the stack\n")
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 0)

    result = runner.invoke(app, ["run", "deploy-monitoring"])

    assert result.exit_code == 0
    assert "'deploy-monitoring' is both a registered job and a group name" in result.stdout
    assert "running the job" in result.stdout
    assert "deploying the stack" in result.stdout
    # The record proves which reading was taken, so the notice is not just a claim.
    assert recent_runs(job="deploy-monitoring", limit=1)[0].status == "success"


@pytest.mark.parametrize("name", COLLIDING_NAMES)
def test_every_colliding_name_is_announced_by_the_cli(
    name: str, actions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked against the CLI rather than against the registry, so a job that
    resolved quietly — the original defect — fails here even though the registry
    facts still hold.

    The action is absent from this fixture's root, so each of these runs ends at
    exit 3; the notice is printed before anything is resolved, and that ordering is
    part of what is pinned.
    """
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 0)

    result = runner.invoke(app, ["run", name])

    assert f"'{name}' is both a registered job and a group name" in result.stdout
    assert result.exit_code == 3


def test_the_colliding_names_are_really_colliding() -> None:
    """The empty case would make the tests above vacuous, so the set is asserted to
    be populated — and its size is not pinned, because the registry may change."""
    assert COLLIDING_NAMES
    for name in COLLIDING_NAMES:
        assert name in registry.groups()
        assert registry.get_job(name).name == name


def test_actions_show_a_colliding_name_mentions_the_group(actions: Path) -> None:
    _write(actions, "deploy-monitoring.sh", "#!/bin/bash\nexit 0\n")
    result = runner.invoke(app, ["actions", "show", "deploy-monitoring"])
    assert result.exit_code == 0
    assert "is both a registered job and a group name" in result.stdout


def test_run_an_unknown_name_still_says_only_that_it_is_unknown(actions: Path) -> None:
    """A name that is neither a job nor a group keeps the plain answer: the group
    wording is reserved for a group, so it stays a fact."""
    result = runner.invoke(app, ["run", "not-a-job-or-a-group"])
    assert result.exit_code == 2
    assert "unknown job: not-a-job-or-a-group" in result.stdout
    assert "is a group of" not in result.stdout


# ── sudo ─────────────────────────────────────────────────────────────────────


def test_run_refuses_a_sudo_job_when_not_root(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse, and print the exact command to run.

    Running it unprivileged instead would produce a partial failure or a
    misleading success, and the run record would faithfully log a privileged job
    having run as an unprivileged user. The exit code is 3 and not 5: nothing
    ran, and 5 means the run failed.
    """
    marker = actions / "ran-anyway"
    _write(actions, f"{SUDO_JOB}.sh", f"#!/bin/bash\ntouch {marker}\nexit 0\n")
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 1000)

    result = runner.invoke(app, ["run", SUDO_JOB])

    assert result.exit_code == 3
    assert f"sudo spectre run {SUDO_JOB}" in result.stdout
    assert not marker.exists()


def test_run_releases_the_lock_after_a_sudo_refusal(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No lock is left behind for a run that never happened.

    This asserts the property, not the ordering: it is equally satisfied by refusing
    before the lock is taken (which is what the implementation does) and by taking
    it and releasing it correctly. What it rules out is a leak — `SUDO_JOB` is
    `concurrency="forbid", and a lock stuck on this job would block every privileged
    run of it until stale reclamation, an hour later at the default timeout.

    The ordering itself is pinned by
    `test_run_refuses_a_sudo_job_before_taking_the_lock`, which can observe the
    difference; this one cannot.
    """
    _write(actions, f"{SUDO_JOB}.sh", "#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 1000)

    assert runner.invoke(app, ["run", SUDO_JOB]).exit_code == 3
    assert not lock_path(registry.get_job(SUDO_JOB)).exists()


def test_run_refuses_a_sudo_job_before_taking_the_lock(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal must not be reported as a lock, and must not take one.

    `SUDO_JOB` is `concurrency="forbid"` and its lock is held here by a live process,
    so the two orderings give different answers: refusing inside the lock answers `4`
    "already running", which points an unprivileged caller at waiting — and waiting
    is not what fixes not being root. Refusing first answers `3`, and leaves the real
    holder's lock untouched.
    """
    _write(actions, f"{SUDO_JOB}.sh", "#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 1000)

    path = lock_path(registry.get_job(SUDO_JOB))
    path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    held = json.dumps({"pid": os.getpid(), "started_at": started.isoformat()})
    path.write_text(held, encoding="utf-8")

    result = runner.invoke(app, ["run", SUDO_JOB])

    assert result.exit_code == 3
    assert "needs root" in result.stdout
    assert "already running" not in result.stdout
    assert path.read_text(encoding="utf-8") == held


def test_the_exit_code_constants_are_the_documented_ones() -> None:
    """The table in the module docstring, pinned against the constants.

    Every other code is asserted through a real dispatch, which only shows that *a*
    code came out; this is what stops the six being renumbered while the tests still
    pass — a `0` that became `1` would otherwise be indistinguishable from `main.py`'s
    catch-all.
    """
    assert EXIT_OK == 0
    assert EXIT_UNKNOWN_JOB == 2
    assert EXIT_NOT_DISPATCHABLE == 3
    assert EXIT_LOCKED == 4
    assert EXIT_FAILED == 5


def test_run_refuses_a_sudo_job_without_recording_a_run(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal records nothing: a record of a privileged job that never
    executed would be a lie the run history could not correct later."""
    _write(actions, f"{SUDO_JOB}.sh", "#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 1000)

    before = _rows(SUDO_JOB)
    assert runner.invoke(app, ["run", SUDO_JOB]).exit_code == 3
    assert _rows(SUDO_JOB) == before


def test_run_runs_a_sudo_job_when_already_root(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Root needs no special case: the refusal is about not being root, and a
    process that already is root is exactly what the job asked for."""
    _write(actions, f"{SUDO_JOB}.sh", "#!/bin/bash\necho did the privileged thing\n")
    monkeypatch.setattr(dispatch_cmds.os, "geteuid", lambda: 0)

    result = runner.invoke(app, ["run", SUDO_JOB])
    assert result.exit_code == 0
    assert "did the privileged thing" in result.stdout
    assert recent_runs(job=SUDO_JOB, limit=1)[0].status == "success"


# ── spectre actions ──────────────────────────────────────────────────────────


def test_actions_list_shows_the_registry() -> None:
    result = runner.invoke(app, ["actions", "list"])
    assert result.exit_code == 0
    assert "backups/backup-all" in result.stdout
    assert "backups/backup-databases" in result.stdout


def test_actions_list_shows_every_registered_job() -> None:
    """A job missing from the listing is a job nobody can discover, so the whole
    registry is asserted rather than a couple of representative names."""
    result = runner.invoke(app, ["actions", "list"])
    missing = [job.name for job in registry.JOBS if job.name not in result.stdout]
    assert missing == []


def test_actions_list_shows_sudo_mutates_timeout_and_schedule() -> None:
    """The listing is the operator's whole map of what a job will do before
    running it, so the four fields that decide that are columns: `sudo`,
    `mutates`, `timeout`, `schedule_hint`.

    The columns are plain aligned text rather than a Rich table because Rich
    truncates columns to the terminal width, which silently mangles the job name
    an operator has to copy into `spectre run`. A listing that cannot be copied
    is worse than one that is not decorated.
    """
    result = runner.invoke(app, ["actions", "list"])
    for header in ("sudo", "mutates", "timeout", "schedule"):
        assert header in result.stdout


def test_actions_list_reports_a_sudo_jobs_metadata() -> None:
    """21 of the 61 jobs need root. A listing that hid that — or that put the
    wrong value under the `sudo` heading — would send an operator into a failure
    they could have read off the list instead.

    Positional, which the previous version of this test was not: it asserted
    `"true" in sudo_row.split()[1:]`, membership anywhere in the row. Both
    `security/run-security-hardening` and `backups/backup-all` are `mutates=true`,
    so swapping the `sudo` and `mutates` columns left both assertions green — 44 of
    44 tests passed against a listing that told every non-privileged mutating job
    it needed root. Index 1 is the `sudo` column, and it is read as such.
    """
    result = runner.invoke(app, ["actions", "list"])
    table = _listing(result.stdout)
    assert table[SUDO_JOB]["sudo"] == "true"
    assert table[JOB]["sudo"] == "false"


def test_actions_list_reports_every_job_metadata_positionally() -> None:
    """All four metadata columns, for every job, against the registry.

    Wider than the sudo test on purpose: the same membership weakness applied to
    `mutates`, `timeout` and `schedule`, so this asserts each column for all 61
    jobs rather than one job by hand. Expectations come from the registry, keyed by
    the column *name* read out of the header row, so a column that is renamed or
    reordered fails here instead of comparing the wrong cell.
    """
    result = runner.invoke(app, ["actions", "list"])
    table = _listing(result.stdout)

    assert set(table) == {job.name for job in registry.JOBS}
    for job in registry.JOBS:
        row = table[job.name]
        assert row["sudo"] == str(job.sudo).lower(), job.name
        assert row["mutates"] == str(job.mutates).lower(), job.name
        assert row["timeout"] == str(job.timeout), job.name
        assert row["schedule"] == (job.schedule_hint or "manual"), job.name


def test_actions_list_column_order_is_the_documented_one() -> None:
    """The contract the two tests above rest on: column 1 is `sudo`, column 2 is
    `mutates`, and so on. Pinned here because a reordering would otherwise be
    caught only as a confusing value mismatch rather than as an order change."""
    result = runner.invoke(app, ["actions", "list"])
    header = next(line for line in result.stdout.splitlines() if line.strip())
    assert header.split() == ["job", "sudo", "mutates", "timeout", "schedule"]


def test_actions_list_shows_exactly_the_privileged_jobs_as_privileged() -> None:
    """Both directions, over the whole registry: exactly the `sudo=true` jobs read
    `true`, and the rest read `false`. A one-directional check would pass if the
    column were `true` for everything."""
    result = runner.invoke(app, ["actions", "list"])
    table = _listing(result.stdout)
    privileged = {job.name for job in registry.JOBS if job.sudo}

    assert privileged, "the registry no longer has any privileged job to check"
    assert {name for name, row in table.items() if row["sudo"] == "true"} == privileged


def test_actions_list_reports_the_schedule_hint() -> None:
    result = runner.invoke(app, ["actions", "list"])
    row = next(line for line in result.stdout.splitlines() if line.startswith(JOB))
    assert "0 2 * * 6" in row


def test_actions_show_reports_provenance(actions: Path) -> None:
    result = runner.invoke(app, ["actions", "show", JOB])
    assert result.exit_code == 0
    assert "backup-all.sh" in result.stdout
    assert str(actions) in result.stdout


def test_actions_show_reports_the_owning_scheduler(actions: Path) -> None:
    """`replaces` is the migration ledger: what this job superseded, and so which
    scheduler entry is now redundant."""
    result = runner.invoke(app, ["actions", "show", JOB])
    assert "crontab:0 2 * * 6" in result.stdout


def test_actions_show_unknown_exits_2(actions: Path) -> None:
    result = runner.invoke(app, ["actions", "show", "nope/nope"])
    assert result.exit_code == 2
    assert "unknown job" in result.stdout


def test_actions_show_missing_action_exits_3(actions: Path) -> None:
    """Registered but not dispatchable is exit 3 here too: the same fact about the
    same job should not have two exit codes depending on which command found it."""
    result = runner.invoke(app, ["actions", "show", MISSING_JOB])
    assert result.exit_code == 3


def test_actions_offers_verify() -> None:
    """Task 8's command, replacing the assertion that it does not exist.

    The test that stood here asked the CLI *not* to advertise `verify`, on the
    grounds that a preflight which decides nothing is worse than no preflight. That
    is still the reason it is a real command now: it decides, and the tests below
    pin the decision.
    """
    result = runner.invoke(app, ["actions", "--help"])
    assert result.exit_code == 0
    assert "verify" in result.stdout


# ── actions verify ───────────────────────────────────────────────────────────


def test_actions_verify_exits_1_on_a_blocking_finding(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit 1 is the gate. This root holds one script, so 60 of the 61 registered
    jobs have none — and a `verify` that passed on that would be the whole failure
    this command exists to prevent."""
    _host(monkeypatch, HostInventory([], []))

    result = runner.invoke(app, ["actions", "verify"])

    assert result.exit_code == 1
    assert MISSING_JOB in result.stdout


def test_actions_verify_exits_0_when_only_advisory_findings(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`legacy-path` and `unregistered` are printed and do not fail the gate.

    They describe a migration Plan 3 has not performed yet, and a preflight that
    failed on them would fail CI for state the fix is supposed to remove. The fix
    is to clear the state, not to silence the check — so the check still prints,
    loudly, and exits 0.
    """
    monkeypatch.setattr(registry, "JOBS", [registry.get_job(JOB)])
    _host(monkeypatch, HostInventory([("0 1 * * *", "/usr/local/bin/legacy.sh")], []))

    result = runner.invoke(app, ["actions", "verify"])

    assert result.exit_code == 0
    assert "legacy-path" in result.stdout
    assert "unregistered" in result.stdout
    assert "/usr/local/bin/legacy.sh" in result.stdout


def test_actions_verify_exits_0_when_nothing_is_wrong(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The green case, so exit 0 is pinned as "checked and clean" rather than as
    "did not crash". Both halves are empty *and* stubbed — a clean report from an
    unread host is the failure mode, and it needs a test of its own."""
    monkeypatch.setattr(registry, "JOBS", [registry.get_job(JOB)])
    _host(monkeypatch, HostInventory([], []))

    result = runner.invoke(app, ["actions", "verify"])

    assert result.exit_code == 0
    assert "no findings" in result.stdout


def test_actions_verify_reports_a_duplicate_as_blocking(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two jobs, one basename, both scripts present and executable — so `duplicate`
    is the only thing that can fail the run, which is what makes it worth testing
    on its own rather than as a side effect of a missing action."""
    _write(actions, "t/alpha.sh", "#!/bin/bash\nexit 0\n")
    _write(actions, "u/alpha.sh", "#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(
        registry,
        "JOBS",
        [
            replace(registry.get_job(JOB), name="t/alpha", action="t/alpha.sh", group="t"),
            replace(registry.get_job(JOB), name="u/alpha", action="u/alpha.sh", group="u"),
        ],
    )
    _host(monkeypatch, HostInventory([], []))

    result = runner.invoke(app, ["actions", "verify"])

    assert result.exit_code == 1
    assert "duplicate" in result.stdout
    assert "alpha.sh" in result.stdout
    assert "t/alpha" in result.stdout


def test_actions_verify_prints_every_code_even_at_zero(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All six counts, always.

    A code omitted because it found nothing is indistinguishable from a code that
    was never checked, and `actions verify`'s whole value is that the difference is
    visible. The counts are also the baseline the migration is measured against, so
    a run that only prints the failures cannot produce one.
    """
    monkeypatch.setattr(registry, "JOBS", [registry.get_job(JOB)])
    _host(monkeypatch, HostInventory([], []))

    result = runner.invoke(app, ["actions", "verify"])

    for code in ALL_CODES:
        assert code in result.stdout


def test_actions_verify_says_so_when_it_could_not_read_the_host(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreadable scheduler is a warning, not a finding — and not silence.

    A CI runner with no crontab makes `crontab -l` fail. Counting that as "nothing
    is legacy" reports a fact about the runner rather than about the deployment, and
    that is the specific dishonesty this command must not commit. So the
    incompleteness is stated, on its own line, before any counts.
    """
    monkeypatch.setattr(registry, "JOBS", [registry.get_job(JOB)])
    _host(monkeypatch, HostInventory([], [], ("crontab -l: exit 1: no crontab for builder",)))

    result = runner.invoke(app, ["actions", "verify"])

    assert "could not read" in result.stdout
    assert "no crontab for builder" in result.stdout
    assert "incomplete" in result.stdout
