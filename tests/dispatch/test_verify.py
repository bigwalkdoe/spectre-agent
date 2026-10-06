"""Tests for `spectre actions verify` — the preflight over registry, disk and schedulers.

`verify` earns its place by being honest, so these tests pin three things beyond
"a code appeared in the list":

* each code comes from the condition it names and from nothing else. The fixtures
  install a synthetic registry rather than using the real one, because the real
  registry has 61 jobs and three duplicate action basenames, and a test that
  happened to assert against that data would keep passing for the wrong reason —
  or start failing when the registry is fixed;
* a check that cannot run says so instead of reporting nothing. `bash -n` failing
  to launch, and a crontab that cannot be read, are both pinned here, because
  "reported nothing" and "reported clean" are the same lie;
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


# ── the schedulers ───────────────────────────────────────────────────────────


def test_a_scheduler_calling_a_script_outside_the_root_is_legacy(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory(
        [("0 1 * * *", "/usr/local/bin/alpha.sh")],
        [("legacy.service", "ExecStart=/usr/local/bin/alpha.sh")],
    )

    findings = [f for f in verify(inventory) if f.code == "legacy-path"]

    # One per reference, not one per script: which unit and which crontab line have
    # to change is the actionable part.
    assert len(findings) == 2
    assert any("crontab: 0 1 * * *" in f.detail and "/usr/local/bin/alpha.sh" in f.detail for f in findings)
    assert any("legacy.service" in f.detail for f in findings)


def test_a_scheduler_calling_a_script_inside_the_root_is_not_legacy(
    tmp_path: Path, registry: pytest.MonkeyPatch
) -> None:
    """Relative or absolute, inside the root is inside the root.

    Both forms appear on a real host — a user unit writes an absolute path, a
    crontab line writes whatever was pasted into it — and neither is a migration
    finding.
    """
    root = _root(tmp_path, registry)
    script = _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory(
        [("0 1 * * *", str(script))],
        [("ok.service", f"ExecStart=/bin/bash {script}")],
    )

    assert "legacy-path" not in _codes(verify(inventory))


def test_a_scheduler_already_calling_spectre_run_is_not_legacy(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """The migrated form is `spectre run <job>`, which names no script at all — so
    there is no path to call legacy. This is the shape Plan 3 migrates to, and a
    preflight that flagged it would keep every migrated entry failing forever."""
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])

    inventory = HostInventory([("0 1 * * *", "spectre run t/alpha")], [("ok.service", "ExecStart=spectre run t/alpha")])

    assert verify(inventory) == []


def test_a_scheduler_naming_an_unregistered_script_is_a_finding(tmp_path: Path, registry: pytest.MonkeyPatch) -> None:
    """A script running on a schedule that no job claims has no summary, no timeout
    and no concurrency policy, because nothing in the registry describes it."""
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory([("0 1 * * *", "/x/scripts/backups/ghost.sh")], [])

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
    _root(tmp_path, registry)
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory(
        [("0 1 * * *", "/x/ghost.sh"), ("0 2 * * *", "/x/ghost.sh")],
        [("a.service", "ExecStart=/x/ghost.sh")],
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
    the one that runs on a real host.
    """
    root = _root(tmp_path, registry)
    _write(root, _ALPHA.action)
    home = tmp_path / "home"
    home.mkdir()
    registry.setenv("HOME", str(home))
    registry.setattr(verify_mod.registry, "JOBS", [_ALPHA])
    inventory = HostInventory([], [("fedora.service", "ExecStart=%h/.local/bin/backup.sh")])

    findings = [f for f in verify(inventory) if f.code == "legacy-path"]

    assert len(findings) == 1
    assert str(home / ".local/bin/backup.sh") in findings[0].detail


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
    inventory = HostInventory([("0 1 * * *", "/x/ghost.sh")], [])

    codes = _codes(verify(inventory))

    assert codes == sorted(codes, key=verify_mod.ALL_CODES.index)
    # And the documented order itself, since "sorted by ALL_CODES" is only a claim
    # about consistency until the order is written down somewhere.
    assert verify_mod.ALL_CODES == ("missing", "not-executable", "syntax", "legacy-path", "unregistered", "duplicate")


def test_the_blocking_codes_are_the_documented_four() -> None:
    """`legacy-path` and `unregistered` are advisory until Plan 3 clears them, and
    making them blocking would fail CI for state the migration has not removed."""
    assert verify_mod.BLOCKING_CODES == frozenset({"missing", "not-executable", "syntax", "duplicate"})
    assert verify_mod.ADVISORY_CODES == frozenset({"legacy-path", "unregistered"})
    assert verify_mod.BLOCKING_CODES | verify_mod.ADVISORY_CODES == frozenset(verify_mod.ALL_CODES)


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
