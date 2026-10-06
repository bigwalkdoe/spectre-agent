"""`spectre run` and `spectre actions` — the dispatch layer's operator surface.

Everything else in dispatch decides *what happens to a run*: the resolver refuses a
path that escapes the checkout, the lock refuses a second holder, the runner bounds
the output and enforces the deadline. This module decides what an operator and cron
see, and there is only one thing to get right here, so it is worth stating plainly:

**The exit code is the contract.**

======  ==========================================================
 code   meaning
======  ==========================================================
 ``0``  the action ran and succeeded
 ``2``  no such job in the registry
 ``3``  registered but not dispatchable — missing, non-executable,
        resolving outside the actions root, or needing root and
        not having it
 ``4``  another run holds this job's lock
 ``5``  the action ran and failed, or was stopped for exceeding
        its timeout
 ``1``  an unexpected exception — see below
======  ==========================================================

``spectre actions verify`` has its own, much smaller contract, because it dispatches
nothing and its exit code is a CI gate rather than a run result:

======  ==========================================================
 code   meaning
======  ==========================================================
 ``0``  every registered job is dispatchable and no blocking
        finding stands — which may still be true with
        ``legacy-path`` or ``unregistered`` findings, which are
        printed and advisory until Plan 3 migrates the schedulers
 ``1``  at least one of ``missing``, ``not-executable``,
        ``syntax`` or ``duplicate``
======  ==========================================================

That ``1`` collides with the catch-all above, and the collision is deliberate rather
than accidental: a preflight that failed with ``3`` would be reporting one job's
state as if it were the whole verdict, and one that failed with ``5`` would say an
action ran when none did. Of the codes on offer, ``1`` — "something is wrong" — is
the only honest one, and a caller that cannot tell it from `main.py`'s catch-all
learns it from the report's `verdict:` line, which says how many blocking findings
there were. The alternative was a new code, and a code nothing else in the project
returns is worse than a documented overlap.

Cron reads those numbers and nothing else, so each refusal prints the one fact the
operator needs to act: the path that is missing, the pid holding the lock and since
when, the command to run instead. `3` and `4` describe the invocation and `5`
describes the run, which is why a refusal is never reported as a failed run.

``1`` is in the table because the table would otherwise read as exhaustive and it is
not. It is `main.py`'s pre-existing catch-all, not a code chosen here: a run whose
action succeeded and whose `save_run` then failed — the store locked, the disk full,
a schema this binary does not understand — leaves no record and exits `1` rather than
`5`, because `5` means the *action* failed and would be the more expensive lie. Cron
sees non-zero either way, so the run is still reported as not clean; what is lost is
that it is indistinguishable from a run that never started. It is named here so the
next reader knows it is a known gap in the contract rather than an oversight, and it
is not worth fixing here: a store that cannot record a run that happened is a
storage problem, and pretending otherwise from the dispatcher would be its own lie.

**`spectre run` dispatches one job, and says so when it is asked for something else.**
The design spec lists `spectre run security --audit` as running a group, and leaves
open whether groups need ordering or dependency semantics. That is undecided, and the
registry makes guessing unsafe — 8 of the 16 group names are also job names, and 45 of
the 61 jobs are `mutates=true` — so group running is deferred to a later plan along
with the naming question. What is *not* deferred is the answer: a group name is
reported as a group, and a name that is both a job and a group says which one ran.
See `_explain_missing_job` and `_note_group_collision`.

Two decisions here are deliberate enough to be worth their own note.

**`sudo` refuses rather than half-attempts.** 21 of the 61 registry jobs need root —
every `security/*` and `network/*` job, every `deploy-*` and `setup-*`. Run as an
unprivileged user, one of those produces a confusing partial failure or, worse, a
misleading success, and the run record would faithfully log a privileged job having
executed as an unprivileged user. So the CLI prints the exact command to run and
exits `3`: nothing ran, which is why this is not `5`. The runner has no sudo path and
this module does not add one; re-execing under sudo would mean the dispatcher
deciding how a privileged process is authenticated, which is the operator's call and
belongs in their terminal, not in a maintenance tool's.

**`job.timeout` is passed to `run_action`,** because `timeout=None` there means *no
timeout at all*. All 61 jobs currently declare `timeout=1800`, which is precisely why
omitting it would go unnoticed: it needs a different value to show up. Task 5's lock
judges a holder abandoned after twice the job's own timeout, so a caller that never
passes the timeout also quietly invalidates the reasoning that lock is built on.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from packages.dispatch import registry
from packages.dispatch import verify as verify_mod
from packages.dispatch.envelope import Status
from packages.dispatch.lock import JobLock, LockUnavailable
from packages.dispatch.registry import Job
from packages.dispatch.resolve import DispatchError, ResolvedAction, actions_root, resolve
from packages.dispatch.runner import run_action
from packages.dispatch.verify import Finding
from packages.memory.db import init_db, save_run

# The exit codes, named so a reader does not have to count down a table to find
# which one a `raise typer.Exit` carries.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN_JOB = 2
EXIT_NOT_DISPATCHABLE = 3
EXIT_LOCKED = 4
EXIT_FAILED = 5

# Recorded on every run dispatched from here, so a record can be told apart from a
# cron dispatch or a systemd one by the column that already exists for it.
TRIGGER = "cli"

# The `actions` sub-app. `no_args_is_help` so `spectre actions` lists its commands
# instead of doing nothing successfully.
actions_app = typer.Typer(
    name="actions",
    help="Inspect the job registry: what exists, where it resolves, what it needs.",
    no_args_is_help=True,
)

# Column order for `actions list`, and the value shown for a job with no
# `schedule_hint`. "manual" rather than "-" because it says what it means: the job
# exists and is dispatchable by hand, and nothing schedules it.
_LIST_HEADERS = ("job", "sudo", "mutates", "timeout", "schedule")
_UNSCHEDULED = "manual"


def _bool(value: bool) -> str:
    """`value` as the lowercase word the registry stores it as.

    `True`/`False` would be Python's spelling in a CLI that otherwise speaks
    JSON, `sudo` and the rest of it.
    """
    return str(value).lower()


def _explain_missing_job(name: str) -> None:
    """Why there is no job by that name, which is not always a typo.

    A name that is a *group* is a real thing in the registry that `spectre run`
    cannot dispatch, and calling it "unknown" is a lie about the CLI's own surface:
    an operator who read the design spec — where `spectre run security --audit` runs
    a group — would conclude their installation is broken rather than that the
    feature is not built. So the group case is named as a group, with its size, and
    said plainly to be unimplemented.

    Running a group is deferred rather than declined on the merits. The design
    spec's own open question ("whether groups need ordering or dependency semantics
    is undecided") is unresolved, and the registry makes guessing unsafe: 8 of the 16
    group names are also job names, so `spectre run <name>` is already ambiguous for
    half the groups, and 45 of the 61 jobs are `mutates=true`, which is a large blast
    radius to settle by accident.
    """
    typer.echo(f"unknown job: {name}")
    if name in registry.groups():
        members = registry.jobs_in_group(name)
        typer.echo(f"'{name}' is a group of {len(members)} jobs, not a job.")
        typer.echo("Running a whole group is not implemented: spectre run takes one job at a time.")
    typer.echo("run `spectre actions list` to see every registered job")


def _note_group_collision(name: str) -> None:
    """Say so when a name is both a job and a group, and that the job is what runs.

    8 of the 16 group names are also registered job names, so for those
    `spectre run <name>` is genuinely ambiguous and the job is the safer, more
    specific reading. Keeping the job silently would be the worst of the available
    answers: an operator who meant the group would get one job's output and no hint
    that a group of the same name existed, and 45 of the 61 jobs mutate, so they would
    have run one of them without knowing which reading they were seeing.
    """
    if name not in registry.groups():
        return
    typer.echo(f"note: '{name}' is both a registered job and a group name; running the job.")
    typer.echo("      Running the group is not implemented — see `spectre actions list`.")


def _job_lookup(name: str) -> Job:
    """The registered job, or exit `2` naming it and what it actually is.

    `get_job` raises `KeyError` rather than returning `None` for an unknown name,
    which is the right contract for a lookup — a caller cannot forget to check — but
    it means the CLI has to catch it rather than test the result. An unknown job is
    also the mistake most likely to be a typo or a job that does not exist yet, so
    the message points at the command that lists what does.

    The two cases the message has to keep apart are a name that is nothing at all and
    a name that is a group, and the collision notice for a name that is both: see
    `_explain_missing_job` and `_note_group_collision`. Both live here rather than in
    `spectre run`, so `actions show` answers the same question the same way.
    """
    try:
        job = registry.get_job(name)
    except KeyError:
        _explain_missing_job(name)
        raise typer.Exit(EXIT_UNKNOWN_JOB) from None
    _note_group_collision(name)
    return job


def _refuse_unprivileged(job: Job) -> None:
    """Exit `3` with the command to run instead, unless this process is root.

    Called *before* the lock is taken, and that ordering is the point rather than an
    accident. Taking a `concurrency="forbid"` lock in order to refuse leaves a window
    in which a SIGKILL between the claim and the refusal leaks that lock until stale
    reclamation — up to twice the job's timeout, an hour at the defaults — so one
    unprivileged attempt would lock out every later privileged one. A lock taken for
    work that is never going to happen is a lock nobody asked for.

    It also makes the answer correct rather than merely fast. A caller who is not
    root and meets a busy privileged job otherwise gets exit 4, "lock held", which
    points at the wrong problem: waiting is not what fixes not being root.

    Nothing is executed on this path and nothing is recorded — a record of a
    privileged job that never ran would be a lie the run history cannot later correct.
    """
    if not job.sudo or os.geteuid() == 0:
        return
    typer.echo(f"{job.name} needs root, and this process is not root.")
    typer.echo(f"run: sudo spectre run {job.name}")
    raise typer.Exit(EXIT_NOT_DISPATCHABLE)


def _describe(job: Job, resolved: ResolvedAction) -> None:
    """What `actions show` prints: the registry entry, then what it resolved to.

    The resolved path and the commit are the two things `actions show` exists for —
    "which file would run, and from which revision of the checkout" — and `replaces`
    is included because the registry is the migration ledger, so the scheduler entry
    a job superseded is part of knowing what the job is.
    """
    # Built as (label, value) pairs and rendered by one aligned loop, so a label
    # added later cannot quietly land in its own column.
    fields: list[tuple[str, str]] = [
        ("job", job.name),
        ("summary", job.summary),
        ("group", job.group),
        ("action", job.action),
        ("resolved", str(resolved.path)),
        ("commit", resolved.git_commit or "none (not a git checkout)"),
        ("dirty", _bool(resolved.git_dirty)),
        ("sudo", _bool(job.sudo)),
        ("mutates", _bool(job.mutates)),
        ("timeout", f"{job.timeout}s"),
        ("concurrency", job.concurrency),
        ("schedule", job.schedule_hint or _UNSCHEDULED),
    ]
    fields += [("replaces", replaced) for replaced in job.replaces]
    width = max(len(label) for label, _ in fields)
    for label, value in fields:
        typer.echo(f"{label + ':':<{width + 1}}  {value}")


@actions_app.command("list")
def actions_list() -> None:
    """Every registered job, with the four fields that decide how to run it.

    Plain aligned text rather than a Rich table, and that is not a stylistic
    preference: Rich fits columns to the terminal width and truncates what does not
    fit, so on an 80-column terminal the job name — the one field an operator has
    to copy into `spectre run` — is exactly what gets cut. A listing that cannot be
    copied from is worse than one that is not decorated, and this output is read by
    grep as often as by eye.
    """
    jobs = sorted(registry.JOBS, key=lambda job: job.name)
    rows = [
        (
            job.name,
            _bool(job.sudo),
            _bool(job.mutates),
            str(job.timeout),
            job.schedule_hint or _UNSCHEDULED,
        )
        for job in jobs
    ]
    widths = [
        max(len(header), max((len(row[index]) for row in rows), default=0))
        for index, header in enumerate(_LIST_HEADERS)
    ]
    # The last column is not padded: trailing whitespace in piped output is noise,
    # and it is the last thing on the line anyway.
    typer.echo("  ".join(header.ljust(widths[i]) for i, header in enumerate(_LIST_HEADERS)).rstrip())
    for row in rows:
        typer.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:-1])) + f"  {row[-1]}")


@actions_app.command("show")
def actions_show(job: str) -> None:
    """One job: its metadata, where it resolves, and which scheduler it replaced."""
    entry = _job_lookup(job)
    try:
        resolved = resolve(entry)
    except DispatchError as e:
        # Exit 3 here for the same reason `run` uses it: "registered but not
        # dispatchable" is one fact about one job and must not have two exit codes
        # depending on which command happened to find it.
        typer.echo(str(e))
        raise typer.Exit(e.exit_code) from None
    _describe(entry, resolved)


# ── actions verify ───────────────────────────────────────────────────────────

# Findings are indented under their code, and the counts are the block an operator
# reads and CI diffs. Both are plain aligned text for the same reason `actions
# list` is — see `_print_verify_report`.
_VERIFY_INDENT = "  "


def _print_verify_report(inventory_unreadable: tuple[str, ...], findings: list[Finding]) -> None:
    """The report: what was checked, what was found, and how each code is weighted.

    Plain aligned text rather than a Rich table, for the same reason `actions list`
    is: Rich fits columns to the terminal width and wraps or truncates what does
    not fit, and on an 80-column terminal the path — the one field an operator has
    to copy into a ticket — is exactly what gets broken. This output is read by
    grep at least as often as by eye, and a run of 61 missing actions has to stay
    greppable.

    **All six counts are printed, including the zeroes.** A code omitted because it
    found nothing is indistinguishable from a code that was never checked, and being
    able to tell those apart is the entire value of a preflight. It is also what
    makes the counts a baseline: the migration's before and after have to be
    comparable, and a run that prints only its failures produces no number to
    compare.

    The unreadable-source warning comes first and says the word "incomplete",
    because an unread scheduler half must not read as an empty one.
    """
    typer.echo(f"actions root: {actions_root()}")
    typer.echo(f"registry:     {len(registry.JOBS)} jobs")
    typer.echo("")

    if inventory_unreadable:
        typer.echo("WARNING: could not read — the scheduler half of this report is incomplete:")
        for reason in inventory_unreadable:
            typer.echo(f"{_VERIFY_INDENT}{reason}")
        typer.echo("")

    counts = {code: 0 for code in verify_mod.ALL_CODES}
    for finding in findings:
        counts[finding.code] += 1

    width = max(len(code) for code in verify_mod.ALL_CODES)
    for heading, codes in (
        ("blocking — any of these fails the gate:", verify_mod.BLOCKING_CODES),
        ("advisory — reported, not gated, until the schedulers are migrated:", verify_mod.ADVISORY_CODES),
    ):
        typer.echo(heading)
        for code in verify_mod.ALL_CODES:
            if code in codes:
                typer.echo(f"{_VERIFY_INDENT}{code:<{width}}  {counts[code]:>4}")
        typer.echo("")

    if not findings:
        typer.echo("no findings")
        return

    for code in verify_mod.ALL_CODES:
        matching = [finding for finding in findings if finding.code == code]
        if matching:
            typer.echo(f"{code} ({len(matching)}):")
            for finding in matching:
                typer.echo(f"{_VERIFY_INDENT}{finding.detail}")


@actions_app.command("verify")
def actions_verify() -> None:
    """Preflight the registry, the actions on disk and the host's schedulers.

    Exit 0 when nothing blocking was found, 1 when something was. `legacy-path`
    and `unregistered` describe the migration this plan has not performed yet, so
    they are reported and do not fail the gate — the fix is to clear the state, not
    to silence the check.

    The inventory is read here rather than by `verify()`'s own default, because the
    warning about sources it could not read is not a finding and `verify()` returns
    findings only. Splitting it here keeps the six codes meaning six things and
    leaves "this host could not be fully inspected" as what it is.
    """
    inventory = verify_mod.read_host_inventory()
    findings = verify_mod.verify(inventory)

    _print_verify_report(inventory.unreadable, findings)

    blocking = [finding for finding in findings if finding.code in verify_mod.BLOCKING_CODES]
    if blocking:
        typer.echo(f"verdict: {len(blocking)} blocking finding(s) — see the blocking codes above")
        raise typer.Exit(EXIT_FINDINGS)
    raise typer.Exit(EXIT_OK)


def run_action_job(job: Job, args: list[str]) -> None:
    """Dispatch `job`, record the run, and raise the exit code cron reads.

    The order is the order of the things that can go wrong, cheapest and least
    consequential first: the privilege requirement is checked before the lock is
    taken, the action is resolved before it too, and the lock is held only for the
    run itself. Both checks that precede the lock are refusals — "you are not root",
    "this action is not dispatchable" — and neither is fixed by waiting, so neither
    should cost a contended lock, let alone leave one behind if this process is
    killed in between.

    The lock is a `with` rather than an acquire/release pair, deliberately. Every
    exit from inside it — a failed run, an exception from the store — has to release
    it, and a pair of calls written out by hand is a place where one exit path
    eventually forgets. `backups/backup-all` failing while holding a
    `concurrency="forbid"` lock would block the next backup for twice the timeout,
    which is the one failure mode the lock cannot be allowed to have.
    """
    _refuse_unprivileged(job)
    try:
        resolved = resolve(job)
    except DispatchError as e:
        typer.echo(str(e))
        raise typer.Exit(e.exit_code) from None

    try:
        with JobLock(job):
            outcome = run_action(resolved, args, TRIGGER, timeout=job.timeout)
    except LockUnavailable as e:
        # The exception already carries the holder's pid and start time, and both
        # are printed: "already running" is not actionable without knowing by whom.
        typer.echo(str(e))
        raise typer.Exit(EXIT_LOCKED) from None

    envelope = outcome.envelope
    # `init_db()` before `save_run`, and only here: it creates the tables on a host
    # that has none yet and migrates the seven provenance columns onto a
    # `maintenancerecord` that predates them, and every other command in `main.py`
    # opens the store the same way. Without it the first run on a fresh host failed
    # *after* its action had already run, which is the worst order: the work
    # happened and the record of it did not. Calling it here rather than at the top
    # means a refusal never opens the database at all, so "the refusal records
    # nothing" holds because it never reaches the store, not merely because it
    # decided not to write.
    init_db()
    save_run(envelope)

    # The action's own output, then the summary. Output first because it is what
    # the operator came for, and because `typer.echo` rather than the Rich console
    # so that text an action wrote is printed verbatim — the CLI is built with rich
    # markup, and `[disk-full]` coming out of a script would otherwise be read as a
    # style tag and dropped.
    if envelope.stdout_tail:
        typer.echo(envelope.stdout_tail.rstrip("\n"))
    if envelope.stderr_tail:
        typer.echo(envelope.stderr_tail.rstrip("\n"))

    ended = f"exit {envelope.exit_code}" if envelope.exit_code is not None else "no exit code"
    typer.echo(f"{envelope.job}: {envelope.status.value} in {envelope.duration_ms}ms ({ended})")
    if envelope.status is not Status.SUCCESS:
        raise typer.Exit(EXIT_FAILED)
    # Explicit rather than falling off the end: every other code in the table is a
    # visible `raise`, and a success that is only implied is the one a reader has to
    # go looking for.
    raise typer.Exit(EXIT_OK)


def register(app: typer.Typer) -> None:
    """Attach `run` and the `actions` sub-app to `app`.

    `run` is defined here rather than as a module-level command so both live in one
    place for a reader looking for the dispatch surface, and so `main.py` stays a
    registration call rather than a command.

    The `context_settings` are what make `spectre run <job> -- --flag` work:
    `allow_extra_args` collects what follows the job, and `ignore_unknown_options`
    stops Click from trying to parse an action's own flags as spectre's. Without
    them `spectre run backups/backup-all --dry-run` would fail on an option spectre
    does not have, which is the common case — the flags belong to the action.
    """

    @app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
    def run(
        job: str,
        args: Annotated[list[str] | None, typer.Argument()] = None,
    ) -> None:
        """Run one registered job and record the run.

        Exit 0 success, 2 unknown job, 3 not dispatchable (including a job that
        needs root and did not get it), 4 lock held, 5 failed or timed out, 1 for an
        unexpected error such as a run record that could not be written.
        """
        run_action_job(_job_lookup(job), list(args or []))

    app.add_typer(actions_app, name="actions")
