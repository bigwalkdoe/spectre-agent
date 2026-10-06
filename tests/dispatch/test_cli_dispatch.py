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
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine
from typer.testing import CliRunner

import apps.cli.dispatch_cmds as dispatch_cmds
from apps.cli.dispatch_cmds import (
    EXIT_FAILED,
    EXIT_LOCKED,
    EXIT_NOT_DISPATCHABLE,
    EXIT_OK,
    EXIT_UNKNOWN_JOB,
    EXIT_USAGE,
)
from apps.cli.main import app
from packages.dispatch import registry, retention
from packages.dispatch.lock import lock_path
from packages.dispatch.verify import ALL_CODES, HostInventory
from packages.memory.db import MaintenanceRecord, recent_runs

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
    silently comparing the wrong cell — which is exactly how the previous version
    of the sudo test came to pass against swapped columns.

    The schedule hint is the only multi-word cell (`0 2 * * 6` is five words), so
    it is the reason this cannot split a line into cells and hope. The trailing
    `rows` column is always a single token — a count or `-` — and is therefore taken
    off the right; the rest is split by column count, which leaves the hint whole.
    Splitting the whole line by column count from the left instead would let the
    hint swallow the number after it, and every job's `schedule` would read as a
    fragment.

    `note:` lines are skipped: they report rows the table has no job row for, and
    `zip(..., strict=True)` would otherwise read the first word of a sentence as a
    job name and add it to the table.
    """
    lines = [line for line in stdout.splitlines() if line.strip() and not line.startswith("note:")]
    headers = lines[0].split()
    table: dict[str, dict[str, str]] = {}
    for line in lines[1:]:
        head, last = line.rstrip().rsplit(None, 1)
        cells = [*head.split(maxsplit=len(headers) - 2), last]
        row = dict(zip(headers, cells, strict=True))
        table[row["job"]] = row
    return table


def _store_with_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: dict[str, int]) -> None:
    """Give the growth column a database of its own, holding `rows` per action.

    The session-wide throwaway database would do, except its contents depend on which
    tests ran first — so a count asserted here would be a count of the suite's history
    rather than of anything this test arranged.
    """
    store = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    SQLModel.metadata.create_all(store)
    with Session(store) as session:
        for action, count in rows.items():
            for _ in range(count):
                session.add(
                    MaintenanceRecord(agent="dispatch", action=action, status="success", log_output="", duration_ms=1)
                )
        session.commit()
    monkeypatch.setattr(retention, "engine", store)


def _unreadable_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> None:
    """Point retention at a database that cannot be read, without faking the failure.

    `empty.db` has no `maintenancerecord` — which is what every host that has not
    dispatched anything yet looks like — and `blocked.db` is a directory, so SQLite
    cannot open it at all. Both raise from the real query inside `record_growth`,
    rather than from a stub that decides to raise.
    """
    target = tmp_path / name
    if name.startswith("blocked"):
        target.mkdir()
    monkeypatch.setattr(retention, "engine", create_engine(f"sqlite:///{target}"))


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
    """Arguments after the job go to the action, once `--` says so.

    `--dry-run` is the action's flag, not spectre's, and `--` is how that is
    written. Pinned as the positive half of the pair below: forwarding works, and
    forwarding is not what happens without the `--`.
    """
    _write(actions, "backups/backup-all.sh", '#!/bin/bash\necho "a=$1"\n')
    result = runner.invoke(app, ["run", JOB, "--", "--dry-run"])
    assert result.exit_code == 0
    assert "a=--dry-run" in result.stdout


def test_run_refuses_an_unknown_option_rather_than_forwarding_it(actions: Path) -> None:
    """`--dry-run` without `--` is spectre's error, not the action's argument.

    Forwarding it silently was the defect: with `ignore_unknown_options` set,
    `spectre run maintenance/cleanup-cache --dry-run` ran the destructive path and
    reported `success in 5ms (exit 0)`. 45 of the 61 jobs mutate and 21 need root,
    and an operator's reflex before a destructive action is precisely to type the
    flag and hope — so a flag meant for spectre must not be able to arrive as the
    action's by accident.

    The action here is the check on the assertion: it writes a marker and exits
    non-zero, so a forwarding implementation fails on the output *and* on the exit
    code rather than passing for the wrong reason.
    """
    marker = actions / "ran-anyway.txt"
    _write(
        actions,
        "backups/backup-all.sh",
        f'#!/bin/bash\ntouch {marker}\necho "got=$*"\nexit 7\n',
    )

    result = runner.invoke(app, ["run", JOB, "--dry-run"])

    assert not marker.exists(), "the action ran despite the refused option"
    assert "got=" not in result.stdout
    assert "no such option for spectre run: --dry-run" in result.stdout
    # And it says how to forward it, because a refusal an operator cannot act on is
    # the same wall with better manners.
    assert "spectre run <job> -- --dry-run" in result.stdout


def test_a_refused_option_exits_usage_and_not_unknown_job(actions: Path) -> None:
    """Exit 64, so a usage error is never read as "no such job".

    Click's own code for a usage error is 2, which this module already spends on an
    unknown job name. Reusing it would make a typo and a missing job the same
    number, and 64 is outside every code in the dispatch table — so nothing here
    has to be disambiguated.
    """
    result = runner.invoke(app, ["run", JOB, "--dry-run"])

    assert result.exit_code == EXIT_USAGE
    assert result.exit_code == 64
    assert result.exit_code != EXIT_UNKNOWN_JOB


def test_a_flag_after_a_bare_argument_is_refused_too(actions: Path) -> None:
    """The refusal is not order-dependent: `spectre run <job> extra --flag` is the
    same mistake as `spectre run <job> --flag`, and both must stop before dispatch.

    Stated because `allow_extra_args` collects bare words and nothing else — the
    point of the test is that an unrecognised *option* is refused wherever it
    appears, which is what makes `--` the only way to pass one.
    """
    _write(actions, "backups/backup-all.sh", '#!/bin/bash\necho "got=$*"\nexit 7\n')

    result = runner.invoke(app, ["run", JOB, "extra", "--flag"])

    assert result.exit_code == 64
    assert "got=" not in result.stdout


def test_run_help_documents_the_double_dash(actions: Path) -> None:
    """The disambiguator is in `--help`, not only in a Python comment.

    It used to exist only in a comment above the command, which is the one place an
    operator never looks — and `spectre run --help` documented neither the
    forwarding nor the `--`.
    """
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--" in result.stdout


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

    `EXIT_USAGE` is included, and pinned *outside* the other six rather than merely
    named: it is the only code meaning "nothing ran and nothing was refused", and it
    is the one a collision with `EXIT_UNKNOWN_JOB` would silently absorb.
    """
    assert EXIT_OK == 0
    assert EXIT_UNKNOWN_JOB == 2
    assert EXIT_NOT_DISPATCHABLE == 3
    assert EXIT_LOCKED == 4
    assert EXIT_FAILED == 5
    assert EXIT_USAGE == 64
    assert EXIT_USAGE not in (EXIT_OK, EXIT_UNKNOWN_JOB, EXIT_NOT_DISPATCHABLE, EXIT_LOCKED, EXIT_FAILED)


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
    caught only as a confusing value mismatch rather than as an order change.

    `rows` is last, and is a growth figure rather than job metadata — so it cannot
    push `job`, the field an operator copies into `spectre run`, any further right."""
    result = runner.invoke(app, ["actions", "list"])
    header = next(line for line in result.stdout.splitlines() if line.strip())
    assert header.split() == ["job", "sudo", "mutates", "timeout", "schedule", "rows"]


def test_actions_list_reports_run_row_growth_per_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The last column is how much run history a job has accumulated.

    It is the figure `prune` acts on, shown where an operator is already looking:
    a job with 100,000 rows and one with 12 differ by four orders of magnitude and
    the listing is what says so before anyone wonders why the database is 28 MB.

    The count is read positionally, by the column *name* out of the header row, so a
    column that moved or a `-` that replaced a number is a failure here rather than a
    value quietly compared against the wrong cell.
    """
    _store_with_rows(monkeypatch, tmp_path, {JOB: 3})
    table = _listing(runner.invoke(app, ["actions", "list"]).stdout)
    assert table[JOB]["rows"] == "3"
    # A job that has never run is zero, not blank and not a dash: "no history" is a
    # fact about the job.
    assert table[SUDO_JOB]["rows"] == "0"


def test_actions_list_says_how_many_rows_belong_to_no_registered_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rows whose action names no job are reported outside the table, in one line.

    They have no row of their own to sit in — the table lists jobs — and on the live
    database they are all 140,385 of them, under the legacy agent's bare action names.
    A per-job column showing `0` under all 61 jobs while that is true would be worse
    than no column: it would read as "nothing is accumulating".
    """
    _store_with_rows(monkeypatch, tmp_path, {JOB: 1, "collect-metrics": 2, "check-thresholds": 3})
    result = runner.invoke(app, ["actions", "list"])
    note = next(line for line in result.stdout.splitlines() if line.startswith("note:"))

    assert "5" in note, note
    assert retention.UNKNOWN_JOB in note, note
    assert _listing(result.stdout)[JOB]["rows"] == "1"


def test_actions_list_does_not_pad_the_rows_column(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The count is printed as the number, never padded into a fixed field.

    A width for this column would have to be either measured from its contents or
    guessed, and a guess is visible: pad to six and every one of the 61 lines ends in
    spaces, in piped output, for 59 rows that are `0`. The columns to the left are
    padded — that is what makes them readable — but this one is last and nothing
    follows it, so its width buys nothing and costs trailing whitespace.
    """
    _store_with_rows(monkeypatch, tmp_path, {JOB: 1234})
    lines = [line for line in runner.invoke(app, ["actions", "list"]).stdout.splitlines() if line.strip()]

    wide = next(line for line in lines if line.startswith(JOB))
    assert wide.endswith(" 1234"), wide
    assert [line for line in lines if line != line.rstrip()] == []


def test_actions_list_leaves_no_database_behind_on_a_fresh_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking what can be run must not leave storage behind.

    `actions list` is the read-only discovery command, and R4's property to preserve is
    that it touched *nothing*. Connecting to SQLite creates the file, so a growth column
    that queries unconditionally would hand every fresh install a 4 KiB `memory.db` — and
    fail outright wherever the config directory cannot be created, which is a worse
    failure than the one the column was there to prevent.

    Asserted on the config *directory* rather than the whole tree, and with the
    directory present — which is the real shape of a fresh host, since anything else
    that has run already created `~/.config/spectre`. A missing directory would hide
    the regression: SQLite cannot create a file inside a directory that does not exist
    either, so a connecting implementation would fail, render `-` and pass.
    """
    config = tmp_path / "cfg"
    config.mkdir()
    monkeypatch.setattr(retention, "engine", create_engine(f"sqlite:///{config / 'memory.db'}"))
    result = runner.invoke(app, ["actions", "list"])

    assert result.exit_code == 0
    table = _listing(result.stdout)
    assert set(table) == {job.name for job in registry.JOBS}
    assert {row["rows"] for row in table.values()} == {"-"}
    assert list(config.iterdir()) == [], "a read-only discovery command created something"


def test_actions_list_lists_every_job_when_the_store_has_no_run_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`actions list` is the discovery command — "what can I run?" — and it must not
    become the first thing to break on a host where things are already broken.

    A database with no `maintenancerecord` is every fresh install, and one whose
    database was removed or half-created. So the growth column degrades to `-` and
    the registry still prints in full.

    `-` rather than `0` is the substance of it: zero is a claim about the database,
    and an unreadable database is a claim about the host. Reporting the second as the
    first would tell an operator nothing has run when the truth is that nothing could
    be asked.
    """
    _unreadable_store(monkeypatch, tmp_path, "empty.db")
    result = runner.invoke(app, ["actions", "list"])

    assert result.exit_code == 0
    table = _listing(result.stdout)
    assert set(table) == {job.name for job in registry.JOBS}
    assert {row["rows"] for row in table.values()} == {"-"}


def test_actions_list_survives_a_database_it_cannot_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A database path that cannot be opened at all raises from inside the query.

    The other half of the same promise: the degradation is not keyed on one specific
    failure, and neither is it `except OperationalError` reaching for the wrong one —
    SQLite raises `OperationalError` for both a missing table and an unopenable file,
    and a listing that only survived the first would have been fixed for the wrong
    reason.
    """
    _unreadable_store(monkeypatch, tmp_path, "blocked.db")
    result = runner.invoke(app, ["actions", "list"])

    assert result.exit_code == 0
    table = _listing(result.stdout)
    assert set(table) == {job.name for job in registry.JOBS}
    assert {row["rows"] for row in table.values()} == {"-"}


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

    The unclaimed script sits *inside* the actions root, because that is the only
    place a reference is Spectre's business: a path in another project's tree is
    that project's, and would now be dropped rather than reported.
    """
    monkeypatch.setattr(registry, "JOBS", [registry.get_job(JOB)])
    ghost = actions / "backups" / "legacy.sh"
    _host(monkeypatch, HostInventory([("0 1 * * *", str(ghost))], []))

    result = runner.invoke(app, ["actions", "verify"])

    assert result.exit_code == 0
    assert "legacy-path" in result.stdout
    assert "unregistered" in result.stdout
    assert str(ghost) in result.stdout


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


def test_actions_verify_reports_a_scheduled_unlocked_mutation_as_blocking(
    actions: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new code has to fail the gate, or it is a note rather than a rule.

    Asserted through the CLI because that is where the classification matters: it is
    `BLOCKING_CODES` that decides the exit, and a code added to `ALL_CODES` but left
    advisory would print a finding and certify the host anyway — which for this one
    would mean `verify` certifying as safe the exact job Plan 3 is about to schedule.

    `JOB` is replaced rather than added to, so this stays a single-code report and
    cannot pass by having some other blocking finding alongside it.
    """
    _write(actions, "backups/backup-all.sh", "#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(
        registry,
        "JOBS",
        [
            replace(
                registry.get_job(JOB),
                mutates=True,
                schedule_hint="0 1 * * *",
                concurrency="allow",
            )
        ],
    )
    _host(monkeypatch, HostInventory([], []))

    result = runner.invoke(app, ["actions", "verify"])

    assert result.exit_code == 1
    assert "unlocked-mutation" in result.stdout
    assert JOB in result.stdout
    assert "0 1 * * *" in result.stdout


def test_actions_verify_prints_every_code_even_at_zero(actions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All seven counts, always.

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


def test_python_m_actions_verify_exits_1_when_a_finding_is_blocking(actions: Path, tmp_path: Path) -> None:
    """`python -m apps.cli.main actions verify` must be able to fail.

    Every other test here goes through Click's `CliRunner`, which calls the Typer
    app directly and therefore never touches `__main__`. That path is the one that
    regressed: the module ended in a bare `main()`, and `raise SystemExit(main())`
    is what makes `python -m` agree with the installed console script — which is
    wrapped in `sys.exit()` by `console_scripts` and so always propagated the return
    value. With the bare call, every command exited 0 whatever it reported,
    including `actions verify`, a CI gate that could not fail.

    So this runs the module as a subprocess and reads the real exit status, with a
    registry whose only job is absent: one blocking finding, no other reason to
    fail. `SPECTRE_ACTIONS_ROOT` and `SPECTRE_CONFIG_DIR` are set in the child's
    environment rather than through `monkeypatch`, because a subprocess does not
    inherit the parent's monkeypatching — and the config dir matters, since
    `packages.memory.db` resolves `DB_FILE` at import and an unset variable would
    put this test on the live database.
    """
    env = {
        **os.environ,
        "SPECTRE_ACTIONS_ROOT": str(actions),
        "SPECTRE_CONFIG_DIR": str(tmp_path / "cfg"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }

    completed = subprocess.run(
        [sys.executable, "-m", "apps.cli.main", "actions", "verify"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
    )

    assert completed.returncode == 1, completed.stdout + completed.stderr
    # The report reached the terminal too, so the exit is the report's verdict and
    # not a crash on the way out.
    assert "missing" in completed.stdout
    assert MISSING_JOB in completed.stdout
