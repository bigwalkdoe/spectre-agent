"""Turn a registry entry into a verified absolute path plus git provenance.

Resolution is the dispatcher's containment guard, and the incident it exists for
is a wrapper script that was a symlink to a copy of itself left elsewhere on the
host: the scheduler's path check was satisfied by the symlink while the code that
actually ran was not the reviewed code. So the target is fully resolved — symlinks
followed — *before* anything else is checked, and a target that leaves the actions
root is refused with the real path named rather than executed.

The three checks run containment, then existence, then executability, because the
order decides the message: a path that escapes the checkout is a different and
more serious problem than a missing file. None of them is allowed to pass quietly
— a job whose action is absent must fail loudly, since a dispatcher that skips it
is how a maintenance suite silently stops running.

Provenance answers "which revision of this checkout ran this, and was it dirty?",
read from the repository *containing* the actions root — which is normally the
repository itself, since the default root is a subdirectory of the checkout. A
root outside any repository yields empty provenance instead of raising, because
the actions root is legitimately a plain directory in tests and elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import git

from packages.dispatch.registry import Job

# How much of the HEAD sha is recorded: the same seven hex digits `git log`
# abbreviates to, so a recorded commit can be pasted into a log and resolved.
_SHORT_SHA_LENGTH = 7

# `spectre run`'s exit code for "registered, but not dispatchable" — absent, not
# executable, or resolving outside the checkout. Distinct from 2 (unknown job) and
# 5 (the action ran and failed), so a caller can tell a refusal from a failure.
_NOT_DISPATCHABLE = 3


class DispatchError(Exception):
    """A job cannot be dispatched, and the process should exit `exit_code`."""

    def __init__(self, message: str, exit_code: int = _NOT_DISPATCHABLE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class ResolvedAction:
    """A job's action as an absolute path inside the checkout, plus provenance."""

    job: Job
    path: Path
    git_commit: str
    git_dirty: bool


def repo_root() -> Path:
    """The checkout this package was imported from.

    `parents[0]` is `packages/dispatch`, `[1]` is `packages`, `[2]` is the
    repository root. Resolved, because the location an installed wheel is
    unpacked into is not a useful place to look for the actions.
    """
    return Path(__file__).resolve().parents[2]


def actions_root() -> Path:
    """Where actions live: `$SPECTRE_ACTIONS_ROOT`, else `<repo>/scripts`.

    Absolute and fully resolved in *both* branches, because every caller compares
    a resolved path against it. A checkout is free to make its actions directory
    a symlink — which `<repo>/scripts` is allowed to be, and which
    `<repo>/spectre/actions` will be after the repository merge — and comparing
    against the unresolved root would refuse every job with "resolves outside the
    actions root", naming a path that looks entirely legitimate. Resolving here
    rather than at each call site means no caller can forget.

    An empty variable is treated as unset: `Path("")` resolves to the working
    directory, which would make the whole checkout the actions root.
    """
    configured = os.environ.get("SPECTRE_ACTIONS_ROOT")
    if configured:
        return Path(configured).resolve()
    return (repo_root() / "scripts").resolve()


def _provenance(root: Path) -> tuple[str, bool]:
    """(short HEAD sha, dirty) for the repository holding `root`; ("", False)
    when there is none.

    Dirty is the whole checkout's, not just the root's: a run record claims a
    commit, and "that commit" means the tree the checkout was in.

    A repository with no commits raises ValueError from gitpython rather than
    reporting an invalid repository, and it is just as legitimately
    provenance-less as no repository at all.
    """
    try:
        repo = git.Repo(root, search_parent_directories=True)
        return repo.head.commit.hexsha[:_SHORT_SHA_LENGTH], repo.is_dirty()
    except (git.InvalidGitRepositoryError, ValueError):
        return "", False


def resolve(job: Job) -> ResolvedAction:
    """The job's action as a verified absolute path, with the checkout's provenance.

    Raises `DispatchError` naming the path and the reason. Nothing here executes
    anything, and no failure is softened into a skip.
    """
    root = actions_root()
    target = (root / job.action).resolve()

    # An absolute `action` replaces the root rather than extending it, so this
    # also refuses `/etc/whatever` and not just `../` traversal.
    if not target.is_relative_to(root):
        raise DispatchError(f"job {job.name} resolves outside the actions root: {target}")
    if not target.exists():
        raise DispatchError(f"job {job.name} action is missing: {target}")
    if not os.access(target, os.X_OK):
        raise DispatchError(f"job {job.name} action is not executable: {target}")

    git_commit, git_dirty = _provenance(root)
    return ResolvedAction(job=job, path=target, git_commit=git_commit, git_dirty=git_dirty)
