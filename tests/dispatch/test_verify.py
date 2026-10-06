"""Tests for `spectre actions verify` — the preflight over registry, disk and schedulers.

`verify` earns its place by being honest, so these tests pin three things beyond
"a code appeared in the list":

* each code comes from the condition it names and from nothing else. The fixtures
  install a synthetic registry rather than using the real one, because the real
  registry has 61 jobs and three duplicate action basenames, and a test that
  happened to assert against that data would keep passing for the wrong reason —
  or start failing when the registry is fixed;
* a check that cannot run says so instead of reporting nothing. `bash -n` failing
  to launch, a crontab that cannot be read, and an `ExecStart=` naming a path this
  process cannot resolve are all pinned here, because "reported nothing" and
  "reported clean" are the same lie;
* `legacy-path` and `unregistered` name *this suite's* leftovers and nobody else's.
  Which means the predicate has to keep two cases apart — a crontab line calling
  `<root>/backups/alpha.sh` is the migration, a unit calling some other project's
  `run.sh` is not — and the pair is posed together rather than one test each way,
  because the implementation this replaced dropped the first and reported the
  second, and either test alone would have been satisfied by a predicate that
  reported everything or nothing;
* nothing in this file reads the host. That is enforced by an autouse fixture
  that makes `read_host_inventory()` raise, not by an assertion after the fact: an
  assertion can be deleted by accident, whereas a raise cannot be mistaken for a
  pass.

The real registry's three duplicate basenames are deliberately *not* pinned as a
failing test. They are a genuine finding that `spectre actions verify` reports on
the real host, and whether each pair is one job classified twice or two jobs
needing distinct scripts is a registry question. A test asserting "there are
exactly three" would have to be edited when that is fixed, which is a reason to
delete it rather than maintain it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import packages.dispatch.verify as verify_mod
from packages.dispatch.verify import HostInventory, verify
from tests.dispatch.conftest import make_job

# The real implementation, captured before the guard fixture replaces it. Only the
# two tests that exist to pin `read_host_inventory`'s never-raise contract use it,
# and both stub the two seams it touches, so neither reaches the host.
_real_read_host_inventory = verify_mod.read_host_inventory

# Two jobs, one script each — the shape every test below wants unless it is
# specifically about the registry disagreeing with itself.
_ALPHA = make_job("t/alpha.sh", group="t")
_BETA = make_job("t/beta.sh", group="t")

_VALID = "#!/bin/bash\nexit 0\n"


@pytest.fixture(autouse=True)
def _the_host_is_not_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make reading the real crontab or systemd units impossible, not merely unlikely.

    `read_host_inventory()` is the one impure function in the module, and every
    test here passes an explicit `HostInventory` instead. If a future test forgets
    and omits the argument, it would otherwise quietly read the developer's real
    schedulers and pass for the wrong reason — or fail on a machine with a
    different set of units. Raising makes the accident impossible to miss.
    """

    def forbidden() -> HostInventory:
        raise AssertionError(
            "read_host_inventory() was called; tests must pass an explicit HostInventory "
            "so they cannot depend on the host's own schedulers"
        )

    monkeypatch.setattr(verify_mod, "read_host_inventory", forbidden)


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Install a synthetic registry for one test.

    `verify` reads `registry.JOBS` as a module attribute on purpose, which is what
    makes this possible at all: a `from ... import JOBS` binding captured at import
    would be frozen into `verify` and no test could ever pose a registry that
    disagrees with the checked-in data.
    """
    return monkeypatch


def _write(root: Path, name: str, body: str = _VALID, executable: bool = True) -> Path:
    """Write an action under the actions root and set its mode."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755 if executable else 0o644)
    return path


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty actions root, pointed at by `SPECTRE_ACTIONS_ROOT`."""
    root = tmp_path / "scripts"
    root.mkdir()
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(root))
    return root


def _codes(findings: list[verify_mod.Finding]) -> list[str]:
    return [f.code for f in findings]


# ── the registry and the disk ────────────────────────────────────────────────


def test_a_present_executable_action_is_not_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The green case, which is the one a preflight has to be able to reach.

    Pinned first and pinned as its own test because the checks below are all
    negative: without a positive case, a `verify` that returned `[]` unconditionally
    would satisfy every other test here.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    _write(root, _BETA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA, _BETA])

    assert verify(HostInventory([], [])) == []


def test_a_missing_action_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA, _BETA])

    findings = [f for f in verify(HostInventory([], [])) if f.code == "missing"]

    # Exactly one, naming the job that has no script — not one per missing file, and
    # not one for the job that is fine.
    assert [f.detail for f in findings] == [f"t/beta: no action at {root / _BETA.action}"]
    # The mode is never checked on a file that is not there: "not executable" is a
    # claim about a file, and there is no file to make the claim about.
    assert "not-executable" not in _codes(verify(HostInventory([], [])))


def test_a_directory_named_like_an_action_is_reported_not_parsed(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """A directory passes both existence and the executable bit, and is neither.

    `os.access(X_OK)` on a directory answers "may be traversed", so a directory
    named `t/alpha.sh` satisfied both guards and was handed to `bash -n`, which
    exited 126 — reported as `syntax`, i.e. "this script is broken", about something
    that is not a script at all. `spectre run` refuses the same path, so a preflight
    that passed it was answering "would this run?" with a yes it cannot mean.

    `missing` is the honest code: the action root holds scripts, and this is not one
    of them. The two facts that must not both appear are `syntax` (a claim about
    code) and `unregistered` (a claim about the registry).
    """
    root = _root(tmp_path, registry)
    (root / "t").mkdir()
    (root / "t" / "alpha.sh").mkdir()
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])

    codes = _codes(verify(HostInventory([], [])))

    assert codes == ["missing"]
    findings = [f for f in verify(HostInventory([], [])) if f.code == "missing"]
    assert "not a file" in findings[0].detail
    assert str(root / "t" / "alpha.sh") in findings[0].detail


def test_a_non_executable_action_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """Executable, not merely present — a 0o644 script is what a git checkout or a
    `cp` without `-p` leaves behind, and `spectre run` refuses it too."""
    root = _root(tmp_path, registry)
    path = _write(root, _ALPHA.action, executable=False)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])

    findings = [f for f in verify(HostInventory([], [])) if f.code == "not-executable"]

    assert [f.detail for f in findings] == [f"t/alpha: not executable: {path}"]
    # Present, so neither of the other two disk codes may also fire.
    assert set(_codes(verify(HostInventory([], [])))) == {"not-executable"}


def test_a_syntax_error_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """`bash -n` rather than a Python-side guess: an action is a bash script, and
    bash is the thing that will refuse to run it."""
    root = _root(tmp_path, registry)
    path = _write(root, _ALPHA.action, "#!/bin/bash\nif [\n")
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])

    findings = [f for f in verify(HostInventory([], [])) if f.code == "syntax"]

    assert len(findings) == 1
    detail = findings[0].detail
    # The job, the path, and that bash is what refused — without naming bash, a
    # syntax finding is indistinguishable from a missing interpreter.
    assert "t/alpha" in detail
    assert str(path) in detail
    assert "bash -n" in detail


def test_an_action_escaping_the_actions_root_is_reported_not_assumed_dispatchable(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """A relative `../` or an absolute path in `action` resolves outside the root.

    There is no finding code for "escapes the root", and inventing one would have
    made this a seventh code for a case the six cover. `missing` is the honest fit:
    the script genuinely is not present *in the actions root*, and the detail says
    so in those words rather than calling it absent from disk. What matters is that
    it is reported at all — `spectre run` refuses such a job, so a preflight that
    passed it would be answering "would this run?" with a yes it cannot mean.
    """
    _root(tmp_path, registry)
    outside = tmp_path / "outside.sh"
    outside.write_text(_VALID)
    outside.chmod(0o755)
    registry.setattr(verify_mod.registry, "JOBS", [make_job("../outside.sh", group="t")])

    findings = [f for f in verify(HostInventory([], [])) if f.code == "missing"]

    assert len(findings) == 1
    assert "outside the actions root" in findings[0].detail
    assert str(outside) in findings[0].detail


def test_a_syntax_check_that_cannot_run_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """No `bash` on the box is not "the script is valid".

    Swallowing the launch failure would report a clean action the preflight never
    actually checked — the exact failure this command exists to prevent. It is
    reported under `syntax` because the claim that code can make is "this action is
    not known to be valid bash", which is true, and the detail says the check could
    not run rather than claiming the script is broken.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])

    def no_bash(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError(2, "No such file or directory: 'bash'")

    registry.setattr(verify_mod.subprocess, "run", no_bash)

    findings = [f for f in verify(HostInventory([], [])) if f.code == "syntax"]

    assert len(findings) == 1
    assert "could not run" in findings[0].detail
    assert "No such file" in findings[0].detail


# ── the registry against itself ──────────────────────────────────────────────


def test_two_jobs_claiming_one_basename_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The `network-monitor.sh` duplication, made permanently detectable.

    Both jobs exist, both scripts exist and both are runnable, so every other code
    is silent — which is why this is easy to miss by eye. Two groups claiming one
    script means one of them is not dispatching what its name promises.
    """
    root = _root(tmp_path, registry)
    _write(root, "maintenance/network-monitor.sh")
    _write(root, "network/network-monitor.sh")
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [
            make_job("maintenance/network-monitor.sh", group="maintenance"),
            make_job("network/network-monitor.sh", group="network"),
        ],
    )

    findings = [f for f in verify(HostInventory([], [])) if f.code == "duplicate"]

    assert len(findings) == 1
    detail = findings[0].detail
    assert "network-monitor.sh" in detail
    # Both claimants, named: "two jobs claim this" is not actionable, the two names
    # are the whole finding.
    assert "maintenance/network-monitor" in detail
    assert "network/network-monitor" in detail


def test_two_distinct_actions_are_not_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The negative for `duplicate`, stated as distinct basenames rather than
    distinct paths.

    It has to be basenames, because two jobs naming the *same* action path cannot
    exist at all: the registry rejects a name that disagrees with its action, and
    two jobs with one action would share one name. So a basename collision in two
    different directories is the only form the finding can take — which is exactly
    the form the real registry's three pairs take.
    """
    root = _root(tmp_path, registry)
    _write(root, "t/alpha.sh")
    _write(root, "u/beta.sh")
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [make_job("t/alpha.sh", group="t"), make_job("u/beta.sh", group="u")],
    )

    assert verify(HostInventory([], [])) == []


# ── the invariant Plan 3 repoints the schedulers against ─────────────────────


def test_a_scheduled_mutating_job_that_takes_no_lock_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """`schedule_hint` plus `mutates` must mean `concurrency="forbid"`.

    This is the invariant the migration leans on and nothing enforced. Plan 3
    repoints schedulers one at a time, verifying each, so a job carrying a
    `schedule_hint` is one cron is about to call — and if it mutates and declares
    `concurrency="allow"`, two of its runs can interleave with nothing to prevent
    it. `mutates` does not help: it is recorded and badged, never acted on, so an
    operator reading the run history would see two ordinary successful runs.

    The action on disk is present and executable, so every disk code is silent and
    this is the only finding — which is what makes it easy to miss by eye.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [make_job("t/alpha.sh", group="t", mutates=True, schedule_hint="0 1 * * *", concurrency="allow")],
    )

    findings = [f for f in verify(HostInventory([], [])) if f.code == "unlocked-mutation"]

    assert len(findings) == 1
    detail = findings[0].detail
    assert "t/alpha" in detail
    # The schedule, because "this job takes no lock" is a registry fact and
    # "…that is about to be scheduled" is the reason it matters.
    assert "0 1 * * *" in detail
    assert "'allow'" in detail


def test_a_scheduled_mutating_job_that_locks_is_not_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The green case, stated so the rule cannot be satisfied by dropping the check.

    Every job the real registry schedules today is in this shape, and a rule with no
    positive case would be satisfied by a `verify` that reported nothing at all.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [make_job("t/alpha.sh", group="t", mutates=True, schedule_hint="0 1 * * *", concurrency="forbid")],
    )

    assert verify(HostInventory([], [])) == []


def test_a_read_only_job_needs_no_lock_however_often_it_runs(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """Read-only jobs are exempt, and the exemption is a decision worth pinning.

    Two concurrent disk reports are harmless, so requiring a lock on them would buy
    nothing and cost an exit-4 every time one overran its period — which would train
    an operator to read "lock held" as noise, on the same code that reports a real
    collision. The rule is about interleaving *mutations*, not about concurrency.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [make_job("t/alpha.sh", group="t", mutates=False, schedule_hint="*/5 * * * *", concurrency="allow")],
    )

    assert verify(HostInventory([], [])) == []


def test_a_mutating_job_nothing_schedules_may_still_take_no_lock(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """No `schedule_hint`, no finding — the rule is about the schedulers, not the flag.

    Stated as its own case because it is the one a reader is most likely to get
    wrong in the other direction: the point of the code is that `verify` is how Plan
    3 proves a repoint is safe, so it judges jobs a scheduler is about to call and
    not jobs an operator may call by hand.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [make_job("t/alpha.sh", group="t", mutates=True, schedule_hint=None, concurrency="allow")],
    )

    assert verify(HostInventory([], [])) == []


def test_the_checked_in_registry_has_no_scheduled_job_without_a_lock() -> None:
    """The real data satisfies the invariant, so the rule guards it rather than
    merely restating today's accident.

    This reads the committed registry instead of a synthetic one, which is the one
    job in this file that is allowed to break when the registry is corrected — and
    that is the point. `unlocked-mutation` had no rule at all, so a `schedule_hint`
    added to any of the eleven mutating jobs that took no lock would have shipped to
    cron with nothing to notice.
    """
    offenders = sorted(
        job.name
        for job in verify_mod.registry.JOBS
        if job.schedule_hint and job.mutates and job.concurrency != "forbid"
    )

    assert offenders == []


# ── the schedulers ───────────────────────────────────────────────────────────


def test_a_scheduler_calling_a_script_inside_the_root_is_legacy(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The migration itself: a crontab line calling `<root>/backups/alpha.sh` directly.

    This check used to do the opposite, and the inversion is the whole finding. A
    crontab entry that reaches a reviewed action by path is precisely the legacy
    form Plan 3 repoints at `spectre run <job>`, so treating "inside the actions
    root" as evidence that it had already been migrated made `legacy-path` blind to
    the only work it exists to drive — on the host it was written against, twelve of
    fourteen crontab entries call suite scripts by path and every one of them was
    silently discarded.

    Both the absolute crontab form and the `bash <path>` unit form appear, because
    both do on a real host and neither is the migrated shape.
    """
    root = _root(tmp_path, registry)
    script = _write(root, "backups/alpha.sh")
    registry.setattr(verify_mod.registry, "JOBS", [make_job("backups/alpha.sh", group="backups")])
    inventory = HostInventory(
        [("0 1 * * *", str(script))],
        [("legacy.service", f"ExecStart=/bin/bash {script}")],
    )

    findings = [f for f in verify(inventory) if f.code == "legacy-path"]

    # One per reference, not one per script: which unit and which crontab line have
    # to change is the actionable part.
    assert len(findings) == 2
    assert any("crontab: 0 1 * * *" in f.detail and str(script) in f.detail for f in findings)
    assert any("legacy.service" in f.detail for f in findings)
    # Registered, so the companion code stays silent — the two are different facts.
    assert "unregistered" not in _codes(verify(inventory))


def test_a_scheduler_calling_another_projects_script_is_not_reported(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """A third-party `run.sh` is that project's business, not our leftover work.

    The other half of the same fix, and the half that makes the first half mean
    something: `verify` reported only references *outside* the actions root, so
    every finding it printed belonged to software Spectre does not own — a GitHub
    Actions runner, a KDE helper, a distribution backup script. None will ever be
    migrated, which put a permanent floor under the plan's success criterion.

    `unregistered` is scoped the same way. "No job claims this script" is only
    Spectre's problem for a script Spectre ships.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory(
        [("0 1 * * *", "/usr/libexec/actions-runner/run.sh")],
        [("runner.service", "ExecStart=/usr/libexec/actions-runner/run.sh")],
    )

    assert verify(inventory) == []


def test_our_script_and_a_third_party_one_are_told_apart_in_one_inventory(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """The two cases the predicate exists to keep apart, judged side by side.

    A crontab line calling `<root>/backups/alpha.sh` is ours and is the migration; a
    unit calling `/usr/libexec/whatever/run.sh` belongs to another project and is
    none of our business. Stated in one inventory deliberately — the previous
    implementation dropped the first and reported the second, and a pair of
    one-direction tests would have been satisfied by a predicate that simply
    reported or dropped everything.
    """
    root = _root(tmp_path, registry)
    ours = _write(root, "backups/alpha.sh")
    theirs = "/usr/libexec/whatever/run.sh"
    registry.setattr(verify_mod.registry, "JOBS", [make_job("backups/alpha.sh", group="backups")])
    inventory = HostInventory([("0 1 * * *", str(ours))], [("other.service", f"ExecStart={theirs}")])

    legacy = [f for f in verify(inventory) if f.code == "legacy-path"]

    assert [f.detail for f in legacy] == [
        f"crontab: 0 1 * * *: calls {ours} by path instead of `spectre run <job>`",
    ]


def test_a_script_in_the_suite_tree_outside_the_actions_root_is_legacy(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """A suite's own scripts are not all under the actions directory.

    The two five-minute Prometheus exporters that still run from cron on this host
    live in the suite's `prometheus/` directory and are in neither the registry nor
    the actions root — and they are exactly as much Spectre's leftover work as any
    registered job, so scoping to the actions root alone would have dropped the one
    pair Plan 3 most clearly has to replace. Hence the suite tree, the actions
    root's parent.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    exporter = root.parent / "prometheus" / "business-metrics-exporter.sh"
    inventory = HostInventory([("*/5 * * * *", str(exporter))], [])

    findings = verify(inventory)

    assert any(f.code == "legacy-path" and str(exporter) in f.detail for f in findings)
    # And it is ours, so nothing claims it and that is reported alongside.
    assert any(f.code == "unregistered" and "business-metrics-exporter.sh" in f.detail for f in findings)


def test_systemds_ignore_failure_prefix_does_not_hide_a_reference(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """`ExecStart=-/root/alpha.sh` means "ignore a non-zero exit", not "not a path".

    systemd prefixes the executable with `-`, `@`, `+` or `!` to change what a
    failure means. The prefix is part of the command word and not part of the path,
    so a bare "does it start with `/`" test discarded the whole reference — and a
    reference that cannot be judged must still be reported.
    """
    root = _root(tmp_path, registry)
    script = _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory([], [("tolerant.service", f"ExecStart=-{script}")])

    findings = [f for f in verify(inventory) if f.code == "legacy-path"]

    assert len(findings) == 1
    assert str(script) in findings[0].detail


def test_a_reference_this_preflight_cannot_resolve_is_reported_not_dropped(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """`ExecStart=$SUITE/alpha.sh` names a real script whose path cannot be computed.

    The variable is expanded by the unit's own `Environment=`, which is out of scope
    for a preflight that reads `ExecStart=` lines, so ownership is undecidable. It
    is still reported, and the detail says so rather than asserting an answer: a
    check that silently drops an entry it could not judge is indistinguishable from
    one that found nothing there, which is the failure this module exists to avoid.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory([], [("templated.service", "ExecStart=$SUITE/alpha.sh")])

    findings = [f for f in verify(inventory) if f.code == "legacy-path"]

    assert len(findings) == 1
    detail = findings[0].detail
    assert "$SUITE/alpha.sh" in detail
    assert "does not resolve" in detail
    # The honest part: it must not claim to know whose script this is.
    assert "cannot tell whether" in detail


def test_a_scheduler_already_calling_spectre_run_is_not_legacy(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The migrated form is `spectre run <job>`, which names no script at all.

    This is the shape Plan 3 migrates to, and a preflight that flagged it would
    keep every migrated entry failing forever — so the job name is skipped
    explicitly. It has to be: 40 of the 61 registered names contain a `/`, so a
    `spectre run backups/backup-all` whose job name was read as an unresolvable
    script path would report a finding for every entry Plan 3 had already fixed,
    which is the same anti-correlation this check was corrected for, one level up.
    """
    root = _root(tmp_path, registry)
    _write(root, "backups/alpha.sh")
    registry.setattr(verify_mod.registry, "JOBS", [make_job("backups/alpha.sh", group="backups")])

    inventory = HostInventory(
        [("0 1 * * *", "spectre run backups/alpha")],
        [("ok.service", "ExecStart=/usr/bin/spectre run backups/alpha")],
    )

    assert verify(inventory) == []


def test_a_scheduler_naming_an_unregistered_script_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """A script running on a schedule that no job claims has no summary, no timeout
    and no concurrency policy, because nothing in the registry describes it."""
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    ghost = root / "backups" / "ghost.sh"
    inventory = HostInventory([("0 1 * * *", str(ghost))], [])

    findings = [f for f in verify(inventory) if f.code == "unregistered"]

    assert len(findings) == 1
    assert "ghost.sh" in findings[0].detail
    assert "t/alpha" not in findings[0].detail


def test_an_unregistered_script_is_reported_once_however_many_entries_name_it(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """One fact, one finding — naming both sources rather than repeating the finding.

    A script reached from two units is one unregistered script, and the useful
    detail is "these two reach it". Repeating the finding per reference would make
    the count a function of how many schedulers happen to mention it.
    """
    root = _root(tmp_path, registry)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    ghost = root / "ghost.sh"
    inventory = HostInventory(
        [("0 1 * * *", str(ghost)), ("0 2 * * *", str(ghost))],
        [("a.service", f"ExecStart={ghost}")],
    )

    findings = [f for f in verify(inventory) if f.code == "unregistered"]

    assert len(findings) == 1
    assert "ghost.sh" in findings[0].detail
    assert "a.service" in findings[0].detail


def test_a_units_percent_h_is_expanded_before_being_judged(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """`%h` is systemd's home-directory specifier and appears in real user units.

    Left unexpanded it is not an absolute path, so it would compare as neither
    inside nor outside the actions root — and the entry would be silently skipped.
    Silent is the one outcome this command must not produce.

    `$HOME` is set rather than a helper being replaced, so the code under test is
    the one that runs on a real host. `HOME` is the *parent* of the actions root, so
    the expanded path lands inside it and the entry is one of ours — which is what
    makes the expansion observable in the finding rather than in its absence.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setenv("HOME", str(tmp_path))
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory([], [("templated.service", "ExecStart=%h/scripts/t/alpha.sh")])

    findings = [f for f in verify(inventory) if f.code == "legacy-path"]

    assert len(findings) == 1
    assert str(root / "t" / "alpha.sh") in findings[0].detail


def test_a_command_without_a_script_path_is_ignored(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """Most of a real host's units are not maintenance scripts, and a preflight
    that called every absolute path legacy would bury the three entries that are."""
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory(
        [("0 1 * * *", "/usr/bin/python3 -m apps.daemon.main")],
        [("daemon.service", 'ExecStart=/usr/share/code/bin/code-tunnel "--verbose" tunnel service')],
    )

    assert verify(inventory) == []


def test_ordinary_unit_words_are_not_read_as_unresolvable_script_paths(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """The unresolvable bucket is narrow, because the alternative is a flood.

    Every non-absolute word in a unit command is a candidate for "a script path we
    cannot place", and almost all of them are flags, argv[0]s or bare verbs. These
    are the words of the units on the host this was written against: a rule loose
    enough to catch them would bury the entries that are real, which is the same
    failure as reporting none of them.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setenv("HOME", str(tmp_path))
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory(
        [],
        [
            ("dbus.service", "ExecStart=/usr/bin/dbus-daemon --system --nofork $DBUS_ARGS"),
            ("gateway.service", "ExecStart=/usr/bin/hermes gateway run"),
            ("wg-quick@.service", "ExecStart=/usr/bin/wg-quick %i up"),
            ("api.service", "ExecStart=/usr/bin/python3 -m uvicorn apps.api.main:app --port 8106"),
        ],
    )

    assert verify(inventory) == []


# ── ordering, so the output is a gate and not a shuffle ──────────────────────


def test_findings_come_back_in_the_documented_code_order(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """A CI gate that reorders its output between runs cannot be diffed, so the
    order is part of the contract rather than a property of the sort key."""
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action, executable=False)
    registry.setattr(
        verify_mod.registry,
        "JOBS",
        [
            make_job("t/alpha.sh", group="t"),
            make_job("t/beta.sh", group="t"),
            make_job("maintenance/network-monitor.sh", group="maintenance"),
            make_job("network/network-monitor.sh", group="network"),
        ],
    )
    # Inside the actions root, so this entry is one of ours and exercises the sort
    # across codes; outside it, the scheduler half would have nothing to order.
    inventory = HostInventory([("0 1 * * *", str(root / "ghost.sh"))], [])

    codes = _codes(verify(inventory))

    assert codes == sorted(codes, key=verify_mod.ALL_CODES.index)
    # And the documented order itself, since "sorted by ALL_CODES" is only a claim
    # about consistency until the order is written down somewhere. The two
    # registry-internal codes sit together at the end, after the three disk codes
    # that would break a run first.
    assert verify_mod.ALL_CODES == (
        "missing",
        "not-executable",
        "syntax",
        "legacy-path",
        "unregistered",
        "unlocked-mutation",
        "duplicate",
    )


def test_the_blocking_codes_are_the_documented_ones() -> None:
    """`legacy-path` and `unregistered` are advisory until Plan 3 clears them, and
    making them blocking would fail CI for state the migration has not removed.

    `unlocked-mutation` is on the other side, and that is the decision: it is a
    registry inconsistency a repoint would ship to cron, not leftover state. A gate
    that let it pass would let `verify` certify as safe exactly the thing Plan 3
    relies on it to prove safe.
    """
    assert verify_mod.BLOCKING_CODES == frozenset(
        {"missing", "not-executable", "syntax", "unlocked-mutation", "duplicate"}
    )
    assert verify_mod.ADVISORY_CODES == frozenset({"legacy-path", "unregistered"})
    assert verify_mod.BLOCKING_CODES | verify_mod.ADVISORY_CODES == frozenset(verify_mod.ALL_CODES)
    assert verify_mod.BLOCKING_CODES & verify_mod.ADVISORY_CODES == frozenset()


def test_verify_without_an_inventory_reads_the_host() -> None:
    """The default argument delegates to `read_host_inventory()`.

    Which the autouse guard turns into its own assertion: the only way this can
    pass is by the call reaching the patched function and being stopped by it. The
    alternative — no argument, no host — would make `verify()` on a real host
    silently skip the whole scheduler half, reporting a clean registry and no
    migration findings at all.
    """
    with pytest.raises(AssertionError, match="read_host_inventory"):
        verify()


# ── the one impure function ──────────────────────────────────────────────────


def test_read_host_inventory_never_invents_a_scheduler_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """It reads `crontab -l` and nothing else — in particular it never shells out to
    `sudo crontab -l`.

    Reading another user's crontab needs root, and a preflight that escalated to do
    it would be a tool that cannot run as the unprivileged user in CI, running as
    root on an operator's desktop, for a set of entries it cannot act on anyway.
    """
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "0 1 * * * /x/scripts/alpha.sh\n# a comment\n\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(verify_mod, "_unit_dirs", lambda: [])

    inventory = _real_read_host_inventory()

    assert calls == [["crontab", "-l"]]
    assert inventory.cron_entries == [("0 1 * * *", "/x/scripts/alpha.sh")]
    assert inventory.unit_exec_starts == []
    assert inventory.unreadable == ()


def test_read_host_inventory_reports_what_it_could_not_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every failure becomes an entry in `unreadable`, never an exception.

    A preflight that crashed on a host it could not inspect would report nothing at
    all, which reads exactly like a clean host. Two independent failures — the
    command and the unit directories — are both named.
    """

    def no_crontab(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "no crontab for deon\n")

    monkeypatch.setattr(subprocess, "run", no_crontab)

    def unreadable() -> list[Path]:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(verify_mod, "_unit_dirs", unreadable)

    inventory = _real_read_host_inventory()

    assert inventory.cron_entries == []
    assert inventory.unit_exec_starts == []
    joined = " ".join(inventory.unreadable)
    assert "crontab -l" in joined
    assert "no crontab for deon" in joined
    assert "Permission denied" in joined


def test_read_host_inventory_reads_only_top_level_service_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One `ExecStart=` per top-level `.service`, and drop-in directories are out of
    scope.

    A drop-in `*.service.d/*.conf` is a real way to set `ExecStart`, and reading
    them is a larger job than this preflight claims to do — so the boundary is
    stated here rather than left for someone to discover from a missed entry.
    """
    units = tmp_path / "units"
    (units / "one.service.d").mkdir(parents=True)
    (units / "one.service").write_text(
        "# a comment\nExecStart=/bin/bash /suite/one.sh\n  ExecStart=/suite/overridden.sh\n"
    )
    (units / "two.service").write_text("ExecStart=/suite/two.sh --flag\n")
    (units / "one.service.d" / "override.conf").write_text("ExecStart=/suite/drop-in.sh\n")
    monkeypatch.setattr(verify_mod, "_unit_dirs", lambda: [units])
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))

    inventory = _real_read_host_inventory()

    assert inventory.unit_exec_starts == [
        ("one.service", "ExecStart=/bin/bash /suite/one.sh"),
        # Indented inside `[Service]`, which is how systemd allows it to be written.
        ("one.service", "ExecStart=/suite/overridden.sh"),
        ("two.service", "ExecStart=/suite/two.sh --flag"),
    ]


def test_read_host_inventory_understands_the_crontab_shapes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Comments, blanks, `VAR=value` lines ahead of a schedule, `@reboot`, a command
    that begins with an assignment of its own, and quoted arguments.

    The assignment *inside* the command is on this host's crontab, and it is the
    reason the schedule is located rather than assumed:
    `0 4 * * 0 PRUNE_PROJECTS=x /path/script.sh` is a scheduled command, not an
    environment line, and reading it as one would drop the entry.

    Two malformed lines are asserted *absent* rather than reported: a schedule with
    no command names nothing to run, and `PRUNE=x /suite/six.sh` — an assignment
    with no schedule — is not a crontab entry either. Cron would not run either,
    so counting them would report schedulers the host does not have.
    """

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd,
            0,
            "\n".join(
                [
                    "# a comment",
                    "",
                    "SHELL=/bin/bash",
                    "0 1 * * * /suite/one.sh",
                    "PRUNE=x 0 2 * * * /suite/two.sh",
                    "0 4 * * 0 PRUNE_PROJECTS=suite /suite/three.sh",
                    "@reboot /suite/four.sh",
                    "*/5 * * * * /bin/bash -c '/suite/five.sh --now'",
                    "0 5 * * *",  # a schedule with no command
                    "PRUNE=x /suite/six.sh",  # an assignment with no schedule
                ]
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(verify_mod, "_unit_dirs", lambda: [])

    inventory = _real_read_host_inventory()

    assert inventory.cron_entries == [
        ("0 1 * * *", "/suite/one.sh"),
        ("0 2 * * *", "/suite/two.sh"),
        ("0 4 * * 0", "PRUNE_PROJECTS=suite /suite/three.sh"),
        ("@reboot", "/suite/four.sh"),
        ("*/5 * * * *", "/bin/bash -c '/suite/five.sh --now'"),
    ]
