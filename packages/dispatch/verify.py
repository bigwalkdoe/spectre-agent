"""Preflight consistency check over the registry, the actions on disk, and the schedulers.

`spectre run` answers "can this one job run right now". This module answers the
question an operator has *before* dispatching anything: "would `spectre run` work
for every registered job, and is anything still pointing at the old layout?"

That is only worth asking if the answer can be trusted, so the design is shaped by
one rule: **a check that cannot run must say so, never report nothing.** A
preflight that passes because it could not see the problem is worse than no
preflight, because it is read as a clean bill of health. Every consequence of that
rule is visible in this module:

* the one impure function is `read_host_inventory()`, and `verify()` takes the
  inventory as an argument. Nothing else here reads the host, so the scheduler
  half is exercised in tests against fixtures rather than against whatever
  crontab the machine running them happens to have;
* `read_host_inventory()` never raises and never invokes `sudo`. A failed
  `crontab -l` is an entry in `unreadable`, not an exception — a tool that crashes
  on a host it cannot inspect reports nothing, which is indistinguishable from a
  clean host;
* a `bash -n` that will not launch is a finding, not a clean bill of health for
  every action on the box.

**The registry is read as a module attribute, never bound by name.**
`registry.JOBS` is looked up at call time, which is what lets a test pose a
registry that disagrees with the checked-in data. A `from ... import JOBS` would
freeze one into this module at import, and the `duplicate` check — the only check
that can be exercised at all without editing `registry_data.json` — would become
untestable.

**Why `actions_root()` rather than `resolve()`.** `resolve()` is the right
containment guard and it stays that way; it is the wrong tool for a preflight. It
raises on the first problem, so it reports one bad job out of 61, and it computes
git provenance per job, which a check that never executes anything has no use for.
`verify` therefore mirrors `resolve`'s path arithmetic and its existence and mode
checks exactly — same expression, same order — so the two never disagree about
whether a job is dispatchable, and reports every disagreement instead of the first.

It depends on the invariant `actions_root()` documents: that it returns a
**fully resolved** path in both of its branches, so every caller comparing a
resolved path against it compares like with like. That invariant is load-bearing
here twice over — a checkout that symlinks its actions directory would otherwise
have every one of its own scripts reported as a third-party leftover, and a
scheduler reference that is itself a symlink would be judged against the wrong
tree. It has broken once (Ruling 15); `_ours` resolves both sides for the same
reason and states why.

**One gap, named rather than papered over.** `verify` has no finding code for "this
host could not be inspected". It reports the unreadable sources on
`HostInventory.unreadable` and the CLI prints them as a warning, because a code
here would either be advisory — and then read as "nothing is legacy" when the truth
is "nothing is known" — or blocking, which would fail CI on every runner that has
no crontab. Neither is honest, so the gap is carried as a warning instead.

The six codes, and what each one claims:

``missing``
    The job's action is not present in the actions root, or is not a file. Three
    further cases land here because each is a job that cannot be dispatched and so
    cannot be reported as healthy: an action that resolves *outside* the root
    (`../escape.sh`, or an absolute path), where the detail says "resolves outside
    the actions root" rather than calling it absent from disk; a path that is a
    *directory* named like a script, which passes both `exists()` and the executable
    bit — on a directory that bit means "may be traversed" — and would otherwise be
    reported as a syntax error in a file that is not a script; and an `action` that
    cannot be turned into a path at all (an embedded NUL, a path too long, a looped
    symlink), which `resolve` refuses as an `unusable action path` and which must be
    reported here for the same reason. That last case is a finding rather than a
    traceback because this module is a CI gate: an exception out of `verify` reaches
    the CLI's catch-all as exit 1, the same code as "blocking findings present", so a
    gate that crashed and a gate that failed would report identically.
``not-executable``
    A file, but `os.access(..., os.X_OK)` is false. The mode a `git clone` or a
    `cp` without `-p` leaves behind.
``syntax``
    `bash -n` on the action exited non-zero, or could not be run at all. The detail
    carries bash's own message, because "this script is broken" is not actionable
    and "line 2: unexpected token" is.
``legacy-path``
    A crontab line or a unit's `ExecStart=` calls one of **our** scripts by path
    instead of by `spectre run <job>`. That is the migration Plan 3 performs, and
    being *inside* the actions root is what makes it one — a crontab line naming
    `<root>/backups/backup-all.sh` directly is precisely the thing the plan
    repoints at `spectre run backups/backup-all`, so skipping it here would have
    made this check blind to the only work it exists to drive.

    "Ours" is the actions root or the suite tree around it, because a suite's own
    scripts do not all live under the actions directory. Outside both, the script
    belongs to another package: a GitHub Actions runner's `run.sh` is not
    Spectre's unfinished migration, and reporting it as one put a permanent floor
    of unrelated third-party scripts under the plan's "zero legacy paths"
    criterion — which is what made that criterion unreachable rather than unmet.

    A reference whose path cannot be resolved — `ExecStart=$SUITE/f.sh`, where the
    variable is expanded by the unit's own `Environment=`, which is not read here —
    is reported as well, with the uncertainty in the detail instead of a guess.
    Silent is the one outcome this module must not produce, and an entry that used
    to be silently skipped became a live finding the moment inside-root calls
    started counting. Advisory.
``unregistered``
    A scheduler calls one of our scripts whose basename no registry job claims, so
    nothing describes its summary, timeout or concurrency policy. Advisory.
``unlocked-mutation``
    The job declares a `schedule_hint` and `mutates`, but takes no lock. Blocking,
    and it is the one invariant here that exists because of Plan 3 rather than
    because of a bug: the migration repoints schedulers one at a time and verifies
    each, so a *scheduled* mutating job is exactly what this preflight is about to
    put on cron. With `concurrency="allow"` two of its runs interleave, and
    nothing else in the system would notice — `mutates` is recorded and badged, not
    enforced. Before this code the invariant held only by inspection of today's nine
    `schedule_hint` values, and nothing kept it holding.
``duplicate``
    Two registry jobs claim the same action basename. Blocking, and deliberately
    so: two jobs in different groups dispatching one script means one of them is
    not running what its name says. Whether a given pair is one job classified
    twice, or two jobs needing distinct scripts, is a registry question — and the
    fix is to change the registry, never to stop looking.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from packages.dispatch import registry
from packages.dispatch.resolve import actions_root

# The seven codes, in the order findings are reported: what would break a run
# first, then what is left over from the migration.
MISSING = "missing"
NOT_EXECUTABLE = "not-executable"
SYNTAX = "syntax"
LEGACY_PATH = "legacy-path"
UNREGISTERED = "unregistered"
UNLOCKED_MUTATION = "unlocked-mutation"
DUPLICATE = "duplicate"

ALL_CODES: tuple[str, ...] = (
    MISSING,
    NOT_EXECUTABLE,
    SYNTAX,
    LEGACY_PATH,
    UNREGISTERED,
    UNLOCKED_MUTATION,
    DUPLICATE,
)

# A preflight gate fails on what would stop `spectre run`, and not on what a
# migration has not finished cleaning up. Making the migration findings blocking
# would fail CI for state Plan 3 exists to remove; the fix is to clear the state,
# not to silence the check.
BLOCKING_CODES: frozenset[str] = frozenset({MISSING, NOT_EXECUTABLE, SYNTAX, UNLOCKED_MUTATION, DUPLICATE})
ADVISORY_CODES: frozenset[str] = frozenset({LEGACY_PATH, UNREGISTERED})

# Bound on every subprocess this module starts. `crontab -l` reads a spool file and
# `bash -n` parses a file, so neither is expected to be slow; a bound that fires
# turns into a finding rather than a hung preflight.
_SUBPROCESS_TIMEOUT = 10

# Only `.sh` is treated as a script path. Every unit on a real host has an absolute
# path in its `ExecStart=`, and most of them name a binary, so the suffix is what
# keeps a preflight from reporting the whole of systemd. The cost is that an
# extensionless maintenance script is not seen — stated here rather than left to be
# discovered, and it is why a non-`.sh` reference inside the suite tree is a gap
# rather than a decision.
_SCRIPT_SUFFIX = ".sh"

_EXEC_START_PREFIX = "ExecStart="

# The command word a migrated scheduler entry uses. Matched on the basename so
# `/usr/bin/spectre`, `spectre` and a `PATH` lookup all count — the launcher is
# wherever the distribution put it, and what makes an entry migrated is what it
# invokes, not where that lives.
_DISPATCHER = "spectre"

# systemd's home-directory specifier, which appears in real user units. Left
# unexpanded it is not an absolute path, so it would match neither the actions root
# nor anything outside it, and the entry would be silently skipped.
_HOME_SPECIFIER = "%h"

# systemd's executable prefixes: `-` ignores a non-zero exit, `@` sets argv[0], `+`
# runs with full privileges, `!`/`!!` are sandbox markers. They are part of the
# command word and not part of the path, and only ever appear on the first one — so
# `ExecStart=-/opt/x.sh` is a real reference that a bare `startswith("/")` test
# dropped on the floor.
_SYSTEMD_EXEC_PREFIXES = "-@+!"

_SYSTEM_UNIT_DIR = Path("/etc/systemd/system")

# `VAR=value` at the start of a crontab line. Stripped before the schedule is read,
# because Vixie cron allows those lines ahead of the schedule.
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Fields a non-`@` schedule occupies, and the one command word that must follow it
# for the line to name a command at all.
_SCHEDULE_FIELDS = 5


@dataclass(frozen=True)
class HostInventory:
    """What the host's schedulers currently run.

    `cron_entries` is `(schedule, command)`, `unit_exec_starts` is `(unit name,
    ExecStart= line)` — the whole line, prefix included, because that is what the
    unit file contains and parsing it again here would be a second place to get it
    wrong.

    `unreadable` names every source this process could not read, with the reason.
    It is not a finding: there is no code that honestly means "this host could not
    be inspected", and see the module docstring for why. It is a warning the CLI
    prints above the table, so an incomplete report says so instead of looking
    complete and empty.
    """

    cron_entries: list[tuple[str, str]]
    unit_exec_starts: list[tuple[str, str]]
    unreadable: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    """One inconsistency, as a code plus a detail naming the job and the path.

    The detail is the whole value of the finding. `missing` alone is a category;
    "no action at /home/deon/.../scripts/t/beta.sh" is the fact an operator can act
    on without re-running anything.
    """

    code: str
    detail: str


@dataclass(frozen=True)
class Reference:
    """One script path a scheduler calls, and whether this process could place it.

    `resolved` is False for a reference such as `ExecStart=$SUITE/alpha.sh`, whose
    path depends on an `Environment=` this preflight does not read. Both kinds are
    reported under `legacy-path`, because both are a scheduler reaching a script by
    path rather than through the dispatcher — but the detail differs, because the
    claim differs. A resolved path can be checked against Spectre's trees; an
    unresolved one cannot, and saying so is worth more than deciding by guess.
    """

    source: str
    path: str
    resolved: bool


def _user_unit_dir() -> Path:
    """The per-user unit directory. A function so a test can replace the one place
    that reaches for `$HOME`."""
    return Path.home() / ".config/systemd/user"


def _unit_dirs() -> list[Path]:
    """The two unit directories systemd loads, in the order it loads them.

    Top-level `.service` files only. Drop-in directories (`*.service.d/*.conf`) can
    also set `ExecStart`, and reading them is a larger job than this preflight
    claims — so the boundary is here, in one place, rather than implied.
    """
    return [_SYSTEM_UNIT_DIR, _user_unit_dir()]


def _one_line(text: str, limit: int = 200) -> str:
    """`text` as a single trimmed line, truncated with its reason kept.

    Detail is printed one per line and grepped; a multi-line bash message or a
    warning with newlines in it would break both.
    """
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _parse_crontab(text: str) -> list[tuple[str, str]]:
    """`(schedule, command)` for every real entry in `crontab -l` output.

    The schedule is *located*, not assumed, because a line can begin with an
    assignment — `0 4 * * 0 PRUNE_PROJECTS=x /path/script.sh` is a scheduled
    command, not an environment line, and reading it as one would drop the entry.
    """
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        while parts and _ENV_ASSIGNMENT.match(parts[0]):
            parts.pop(0)
        if not parts:
            continue
        if parts[0].startswith("@"):
            schedule, rest = parts[0], parts[1:]
        elif len(parts) >= _SCHEDULE_FIELDS + 1:
            schedule, rest = " ".join(parts[:_SCHEDULE_FIELDS]), parts[_SCHEDULE_FIELDS:]
        else:
            # A schedule with no command. Not an entry; there is nothing to run.
            continue
        if rest:
            entries.append((schedule, " ".join(rest)))
    return entries


def _cron_entries() -> tuple[list[tuple[str, str]], list[str]]:
    """`(entries, unreadable)` from `crontab -l`.

    Any failure at all — `crontab` absent, a spool this user may not read, no
    crontab at all — yields no entries and a named reason. No `sudo`: reading
    another user's crontab would make this a tool that cannot run in CI as the
    unprivileged user it is, and escalates to root on an operator's desktop for
    entries it cannot act on anyway.
    """
    try:
        completed = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return [], [f"crontab -l: {e}"]
    if completed.returncode != 0:
        detail = _one_line(completed.stderr or "no output") or f"exit {completed.returncode}"
        return [], [f"crontab -l: exit {completed.returncode}: {detail}"]
    return _parse_crontab(completed.stdout), []


def _unit_exec_starts() -> tuple[list[tuple[str, str]], list[str]]:
    """`(entries, unreadable)` from every top-level `.service` in both unit dirs."""
    entries: list[tuple[str, str]] = []
    unreadable: list[str] = []
    try:
        # `Path.home()` itself can raise when the user has no home it can determine,
        # so building the list is inside the guard too. Falling out of here would
        # cost the crontab entries too, which are read first and are the half a
        # container or a cron-less host usually still has.
        directories = _unit_dirs()
    except (OSError, RuntimeError) as e:
        return entries, [f"the unit directories could not be located: {e}"]

    for directory in directories:
        try:
            units = sorted(directory.glob("*.service"))
        except OSError as e:
            unreadable.append(f"{directory}: {e}")
            continue
        for unit in units:
            try:
                # `errors="replace"`: a unit file is data to be parsed, and one
                # unreadable byte must not cost the whole inventory.
                lines = unit.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as e:
                unreadable.append(f"{unit}: {e}")
                continue
            for line in lines:
                # Indented inside `[Service]`, which is how systemd allows it to be
                # written, so the check is on the stripped line.
                text = line.strip()
                if text.startswith(_EXEC_START_PREFIX):
                    entries.append((unit.name, text))
    return entries, unreadable


def read_host_inventory() -> HostInventory:
    """The host's cron entries and unit `ExecStart=` lines.

    The only function in this package that touches the host, and the only one that
    is allowed to be wrong about the host: it is read-only, it never invokes
    `sudo`, and it **never raises**. Every failure — a missing `crontab`, an
    unreadable unit directory, anything unforeseen — becomes a name in
    `unreadable` instead, because a preflight that crashes on a host it cannot
    inspect reports nothing, and nothing reads as a clean host.
    """
    try:
        cron, cron_unreadable = _cron_entries()
        units, unit_unreadable = _unit_exec_starts()
        return HostInventory(cron, units, (*cron_unreadable, *unit_unreadable))
    except Exception as e:  # noqa: BLE001 - "never raises" is the whole contract
        # Unreachable given the guards above, and kept because the contract is not
        # "does not usually raise": a future edit must not be able to break it.
        return HostInventory([], [], (f"the host inventory could not be read: {e}",))


def _syntax_problem(path: Path) -> str:
    """Why `path` is not known to be valid bash, or `""` when `bash -n` agrees.

    `bash -n` rather than anything Python-shaped: an action is a bash script, and
    bash is what will refuse to run it. A launch failure is returned as a problem
    too — reporting "no syntax errors" for a check that never ran is the one answer
    this function must never give.
    """
    try:
        completed = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"the syntax check could not run: {e}"
    if completed.returncode == 0:
        return ""
    return f"bash -n exited {completed.returncode}: {_one_line(completed.stderr) or 'no message'}"


def _registry_findings() -> list[Finding]:
    """Every registry job against the actions root, plus the duplicates among them.

    The checks run containment, then existence, then "is a file", then mode, then
    syntax — the same order `resolve` uses, and for the same reason: which fact you
    report decides which fix the operator reaches for, and "resolves outside the
    checkout" is a different and more serious problem than "that file is not
    executable". Each check stops at its own finding for a given job, because "not
    executable" is a claim about a file, and there is no file to make the claim
    about.
    """
    root = actions_root()
    findings: list[Finding] = []

    for job in sorted(registry.JOBS, key=lambda entry: entry.name):
        # The same expression `resolve` uses, guarded the same way, so the two cannot
        # disagree about what a job's action path is — including about a path neither
        # can turn into one. Resolved, because a checkout may symlink its actions
        # directory and an unresolved comparison would refuse everything.
        try:
            target = (root / job.action).resolve()
        except (OSError, ValueError) as e:
            # `ValueError` here is the embedded-NUL case; `OSError` is a path too long
            # or a looped symlink. `resolve` raises `DispatchError` for both, and
            # raising here instead would escape through `main`'s catch-all as exit 1 —
            # the same code as "blocking findings present", so a crashed gate would be
            # indistinguishable from a failing one. A preflight that cannot judge a job
            # has to report it; that is what `missing` means for every other job here.
            findings.append(Finding(MISSING, f"{job.name}: unusable action path {job.action!r}: {e}"))
            continue

        if not target.is_relative_to(root):
            findings.append(
                Finding(
                    MISSING,
                    f"{job.name}: action resolves outside the actions root: {target} (from {job.action!r})",
                )
            )
        elif not target.exists():
            findings.append(Finding(MISSING, f"{job.name}: no action at {target}"))
        elif not target.is_file():
            # `exists()` and `os.access(X_OK)` both pass for a directory — the
            # executable bit on a directory means "may be traversed", not "is a
            # program" — so a directory named `cleanup.sh` reached `bash -n` and was
            # reported as `syntax`, exit 126. "this script is broken" is the wrong
            # claim about something that is not a script, and `resolve` refuses the
            # same path, so the two have to say the same thing.
            findings.append(Finding(MISSING, f"{job.name}: action is not a file: {target}"))
        elif not os.access(target, os.X_OK):
            findings.append(Finding(NOT_EXECUTABLE, f"{job.name}: not executable: {target}"))
        else:
            problem = _syntax_problem(target)
            if problem:
                findings.append(Finding(SYNTAX, f"{job.name}: {target}: {problem}"))

    findings.extend(_unlocked_mutation_findings())
    findings.extend(_duplicate_findings())
    return findings


def _unlocked_mutation_findings() -> list[Finding]:
    """Every scheduled job that mutates and takes no lock.

    The rule Plan 3 depends on, and which nothing enforced: the migration repoints
    each scheduler to `spectre run <job>` and verifies the host before and after, so
    a job with a `schedule_hint` is one cron is about to call. If it also mutates
    and declares `concurrency="allow"`, two of its runs can interleave, and the only
    other signal — `mutates` — is recorded and badged for display rather than acted
    on. An operator watching one timeout in the log would have no way to tell an
    interleaving pair from two ordinary runs.

    Read-only jobs are exempt, deliberately: two concurrent disk reports are harmless,
    and requiring a lock on them would buy nothing at the cost of exit-4 noise every
    time one overran its period.

    The detail names the schedule, because "this job takes no lock" is a registry
    fact and "…that Plan 3 is about to schedule it" is the reason it matters.
    """
    return [
        Finding(
            UNLOCKED_MUTATION,
            f"{job.name}: scheduled ({job.schedule_hint}) and mutates, but concurrency is "
            f"{job.concurrency!r}; a scheduled mutating job must take the lock",
        )
        for job in sorted(registry.JOBS, key=lambda entry: entry.name)
        if job.schedule_hint and job.mutates and job.concurrency != "forbid"
    ]


def _duplicate_findings() -> list[Finding]:
    """One finding per action basename that more than one job claims.

    Both claimants are named, because "two jobs claim this script" is not
    actionable and the two names are the entire finding. Deliberately left
    unresolved: whether a pair is one job classified twice, or two jobs needing
    distinct scripts, is a registry decision, and a preflight that resolves it by
    ignoring the collision would be lying to make itself convenient.
    """
    claims: dict[str, list[str]] = defaultdict(list)
    for job in registry.JOBS:
        claims[Path(job.action).name].append(job.name)
    return [
        Finding(DUPLICATE, f"{basename} is claimed by {len(names)} jobs: {', '.join(sorted(names))}")
        for basename, names in sorted(claims.items())
        if len(names) > 1
    ]


def _tokens(command: str) -> list[str]:
    """`command` split into words, POSIX-quoting aware.

    Falls back to whitespace splitting on unbalanced quotes: a crontab line that
    does not parse is still worth the paths in it, and refusing to read it at all
    would hide the entry.
    """
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _command_tokens(command: str) -> list[str]:
    """`command`'s words with systemd's executable prefix off the first one.

    Only the first token, because that is the only place systemd allows a prefix.
    On every other token a leading `-` is an ordinary word character, and stripping
    it would turn a flag that happens to start with one into a path.
    """
    tokens = _tokens(command)
    if tokens:
        stripped = tokens[0].lstrip(_SYSTEMD_EXEC_PREFIXES)
        tokens[0] = stripped or tokens[0]
    return tokens


def _expand_home(token: str) -> str:
    """systemd's `%h` as a real path, so the entry can be judged at all."""
    if token == _HOME_SPECIFIER or token.startswith(f"{_HOME_SPECIFIER}/"):
        return str(Path.home()) + token[len(_HOME_SPECIFIER) :]
    return token


def _looks_like_a_script(token: str) -> bool:
    """Whether a token that is *not* a resolvable path still reads as a script path.

    Narrow on purpose: a `/` in it or a `.sh` suffix, and nothing else. That catches
    `$SUITE/f.sh` and `$SUITE/run` — the two forms an unread `Environment=` hides —
    while leaving a unit's `--nofork` and a crontab's bare word alone. A rule loose
    enough to catch those would bury the entries that are real, which is the same
    failure as not reporting any of them.
    """
    return "/" in token or token.endswith(_SCRIPT_SUFFIX)


def _exec_start_command(value: str) -> str:
    """The command half of an `ExecStart=` line.

    `HostInventory` keeps the whole line because that is what the unit file
    contains; stripping the prefix in one place is better than in every caller.
    """
    text = value.strip()
    return text[len(_EXEC_START_PREFIX) :] if text.startswith(_EXEC_START_PREFIX) else text


def _migrated_job_index(tokens: list[str]) -> int | None:
    """The index of the job name in a `spectre run <job>` command, or `None`.

    The migrated form is the one shape this whole check is driving towards, so it
    has to produce no findings at all — including from its own job name, which
    contains a `/` and would otherwise read as an unresolvable script path on every
    grouped job in the registry. Skipping exactly that one argument, rather than
    the whole command, is what keeps a wrapper that still calls a script by path
    visible.
    """
    for index in range(len(tokens) - 2):
        if tokens[index + 1] == "run" and Path(tokens[index]).name == _DISPATCHER:
            return index + 2
    return None


def _collect(source: str, command: str, found: list[Reference]) -> None:
    """Every script path in one scheduler command, appended to `found`."""
    tokens = _command_tokens(command)
    job_name = _migrated_job_index(tokens)
    for index, token in enumerate(tokens):
        if index == job_name:
            continue
        path = _expand_home(token)
        if path.startswith("/"):
            if path.endswith(_SCRIPT_SUFFIX):
                found.append(Reference(source, path, True))
        elif _looks_like_a_script(token):
            found.append(Reference(source, token, False))


def _references(inventory: HostInventory) -> list[Reference]:
    """Every script path a scheduler calls, resolved or not.

    `source` names the scheduler rather than just the file, because the actionable
    fact about a legacy path is which crontab line or which unit has to change.

    Which of them are Spectre's is `_ours`' judgement and deliberately not this
    function's, so that "what do the schedulers call" stays a statement about the
    host rather than about the migration.
    """
    found: list[Reference] = []
    for schedule, command in inventory.cron_entries:
        _collect(f"crontab: {schedule}", command, found)
    for unit, exec_start in inventory.unit_exec_starts:
        _collect(f"unit {unit}", _exec_start_command(exec_start), found)
    return found


def _suite_tree(root: Path) -> Path:
    """The tree a reference is judged against besides the actions root itself.

    The actions root is `$SPECTRE_ACTIONS_ROOT`, else `<repo>/scripts`; its parent
    is the suite root that holds the actions, which is also where the rest of the
    suite lives once the actions move to `<repo>/spectre/actions`. A suite's own
    scripts are not confined to the actions directory — on the host this was
    written against, the two five-minute Prometheus exporters still running from
    cron live in the suite's `prometheus/` directory, and they are as much
    Spectre's leftover work as any registry job is.

    A root whose parent is itself (only reachable if `SPECTRE_ACTIONS_ROOT` were
    `/`) collapses to the root, because otherwise every absolute path on the host
    would count as ours.
    """
    parent = root.parent
    return parent if parent != root else root


def _ours(root: Path, path: str) -> bool:
    """Whether `path` is a script Spectre owns, and so ours to migrate.

    Both sides resolved, and that is not tidiness: it is the invariant
    `actions_root()` documents, on which this whole comparison rests — it returns a
    resolved path in both of its branches precisely so that callers can compare a
    resolved reference against it. A checkout that symlinks its actions directory
    would otherwise have every one of its own scripts reported as another package's
    leftover, which is the mirror image of the bug this predicate replaces.

    Outside both trees the reference belongs to another package. That is the half
    that makes the check mean something: a GitHub Actions runner's `run.sh` is not
    Spectre's unfinished migration, and counting it put a permanent floor of
    unrelated third-party scripts under the plan's success criterion.
    """
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return resolved.is_relative_to(root) or resolved.is_relative_to(_suite_tree(root))


def _scheduler_findings(inventory: HostInventory) -> list[Finding]:
    """What the host's schedulers still call, against what the registry claims.

    `legacy-path` is emitted per reference, because "which unit and which crontab
    line" is the part that makes it fixable. `unregistered` is emitted once per
    basename however many entries name it, because the fact is a property of the
    script rather than of the reference, and a count that moved with the number of
    schedulers mentioning it would be a number about the schedulers.

    Both codes are scoped by `_ours`, so both are about this suite: a scheduler
    reaching another project's tree is that project's business, and reporting it
    here made every count on this command a measurement of the host rather than of
    the migration.
    """
    root = actions_root()
    claimed = {Path(job.action).name for job in registry.JOBS}
    legacy: list[Finding] = []
    unknown: dict[str, list[str]] = defaultdict(list)

    for reference in _references(inventory):
        if not reference.resolved:
            # Ownership is undecidable, so the detail says so instead of asserting
            # it: a resolved reference can be checked against our trees and this one
            # cannot, and saying "ours" here would be the guess the module's own
            # rule forbids.
            legacy.append(
                Finding(
                    LEGACY_PATH,
                    f"{reference.source}: calls {reference.path} by path instead of `spectre run <job>`; "
                    "the path does not resolve, so this cannot tell whether Spectre owns it",
                )
            )
            continue
        if not _ours(root, reference.path):
            continue
        legacy.append(
            Finding(LEGACY_PATH, f"{reference.source}: calls {reference.path} by path instead of `spectre run <job>`")
        )
        basename = Path(reference.path).name
        if basename not in claimed:
            unknown[basename].append(reference.source)

    findings = legacy
    for basename, sources in sorted(unknown.items()):
        findings.append(
            Finding(
                UNREGISTERED,
                f"{basename}: no registered job claims this script; called by {', '.join(sorted(set(sources)))}",
            )
        )
    return findings


def verify(inventory: HostInventory | None = None) -> list[Finding]:
    """Every inconsistency between the registry, the disk and the host's schedulers.

    `inventory=None` reads the host; passing one is what lets the whole module be
    tested without a host. Findings come back in `ALL_CODES` order and then by
    detail, which is part of the contract rather than a side effect of the sort
    key: a CI gate whose output reorders between runs cannot be diffed.

    The list is complete rather than short-circuited. Every registered job is
    checked and every inconsistency is reported, because a preflight that stops at
    the first problem answers "how bad is it" when it was asked "what is wrong".
    """
    if inventory is None:
        inventory = read_host_inventory()
    findings = [*_registry_findings(), *_scheduler_findings(inventory)]
    return sorted(findings, key=lambda finding: (ALL_CODES.index(finding.code), finding.detail))
