"""Tests for action path resolution and the provenance every run records.

Every test points `SPECTRE_ACTIONS_ROOT` at a `tmp_path`: the resolver's default
root is the real `<repo>/scripts`, and no test may read or execute the host's own
maintenance scripts.

Containment is the point of this module. A wrapper script was once a symlink to a
copy of itself left elsewhere on the host, so the scheduler's path check passed
while the code that actually ran was not the reviewed code. The target is
therefore fully resolved — symlinks followed — before anything else is checked,
and a target outside the actions root is refused by name.

The happy-path tests build their action with `_write_action`, which chmods it:
dispatch refuses a non-executable action, and a file written at the default 0o644
is not a dispatchable action, so without it these tests would fail on the wrong
check.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from packages.dispatch.resolve import DispatchError, actions_root, repo_root, resolve
from tests.dispatch.conftest import make_job

_BODY = "#!/bin/bash\nexit 0\n"

# Passed per-invocation rather than left to the host's git config, so the
# repository built below can commit on any machine.
_IDENTITY = ("-c", "user.name=Spectre Test", "-c", "user.email=test@example.invalid")


def _write_action(path: Path) -> None:
    """A dispatchable action: `write_text` alone leaves it 0o644, and dispatch
    refuses a non-executable action, so a happy-path fixture that skips the chmod
    fails on the wrong check."""
    path.write_text(_BODY)
    path.chmod(0o755)


def _git(root: Path, *args: str) -> str:
    """Run git in `root` and return its stdout.

    `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` are pointed at /dev/null so the host's
    git config cannot decide the branch name, the identity or a signing key: the
    repository under test is built the same way on every machine.
    """
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


@pytest.fixture
def git_actions_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An actions root that is a real git repository with one committed action."""
    root = tmp_path / "actions"
    root.mkdir()
    _write_action(root / "ok.sh")
    _git(root, "init", "-q")
    _git(root, "add", "ok.sh")
    _git(root, *_IDENTITY, "commit", "-q", "-m", "add action")
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(root))
    return root


def test_resolve_returns_absolute_path_inside_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _write_action(tmp_path / "ok.sh")
    got = resolve(make_job())
    assert got.path == (tmp_path / "ok.sh").resolve()
    assert got.path.is_relative_to(tmp_path.resolve())


def test_resolve_rejects_symlink_escaping_the_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 1: the fedora-optimize wrapper shape."""
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_action(outside / "ok.sh")
    root = tmp_path / "actions"
    root.mkdir()
    (root / "ok.sh").symlink_to(outside / "ok.sh")
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(root))
    with pytest.raises(DispatchError) as e:
        resolve(make_job())
    assert "outside the actions root" in str(e.value)
    assert "ok.sh" in str(e.value)


def test_resolve_rejects_missing_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing action must fail loudly, never skip silently."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    with pytest.raises(DispatchError) as e:
        resolve(make_job())
    assert e.value.exit_code == 3
    assert "ok.sh" in str(e.value)


def test_resolve_rejects_non_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    p = tmp_path / "ok.sh"
    p.write_text(_BODY)
    p.chmod(0o644)
    with pytest.raises(DispatchError) as e:
        resolve(make_job())
    assert "not executable" in str(e.value)


def test_git_provenance_is_read_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _write_action(tmp_path / "ok.sh")
    got = resolve(make_job())
    assert isinstance(got.git_commit, str)
    assert isinstance(got.git_dirty, bool)


def test_actions_root_defaults_below_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPECTRE_ACTIONS_ROOT", raising=False)
    assert actions_root() == repo_root() / "scripts"


def test_an_empty_actions_root_env_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SPECTRE_ACTIONS_ROOT=` set but empty. `Path("")` resolves to the working
    directory, which would make the entire checkout the actions root — and the
    containment guard would then bless every file in it."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", "")
    assert actions_root() == repo_root() / "scripts"


def test_an_actions_root_reached_through_a_symlink_contains_its_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlinked actions root is a legitimate deployment, so containment must be
    judged against where the root really is, not where it appears to be."""
    real = tmp_path / "real-actions"
    real.mkdir()
    _write_action(real / "ok.sh")
    link = tmp_path / "actions"
    link.symlink_to(real)
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(link))
    got = resolve(make_job())
    assert got.path == (real / "ok.sh").resolve()
    assert got.path.is_relative_to(real.resolve())


def test_the_default_actions_root_is_resolved_before_the_containment_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default root is `<repo>/scripts`, and a checkout is free to make that
    a symlink — which it will be once the actions move to `<repo>/spectre/actions`.
    Comparing the resolved action against the *unresolved* root refused every job
    with "resolves outside the actions root", naming a location that looks
    entirely legitimate. A bug report, from an entirely correct deployment."""
    real = tmp_path / "real-actions"
    real.mkdir()
    _write_action(real / "ok.sh")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "scripts").symlink_to(real)
    monkeypatch.delenv("SPECTRE_ACTIONS_ROOT", raising=False)
    monkeypatch.setattr("packages.dispatch.resolve.repo_root", lambda: checkout)

    got = resolve(make_job())
    assert got.path == (real / "ok.sh").resolve()
    assert got.path.is_relative_to(real.resolve())


# What the resolver reads about the checkout it resolved from. The happy-path
# assertions above hold whether or not the actions root is a repository, which
# means they would pass even if gitpython were never called at all — so the
# provenance contract is pinned here, in both directions.


def test_git_commit_is_the_short_head_sha(git_actions_root: Path) -> None:
    got = resolve(make_job())
    assert got.git_commit == _git(git_actions_root, "rev-parse", "--short", "HEAD")
    assert got.git_dirty is False


def test_git_dirty_flips_when_a_committed_action_changes(git_actions_root: Path) -> None:
    """A dirty checkout must be recorded, or a run record cannot say the run used
    unreviewed code."""
    assert resolve(make_job()).git_dirty is False
    action = git_actions_root / "ok.sh"
    action.write_text("#!/bin/bash\nexit 1\n")
    assert resolve(make_job()).git_dirty is True


def test_provenance_is_empty_outside_a_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The actions root is a plain directory in tests, and legitimately so
    elsewhere; provenance degrades to empty rather than raising."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _write_action(tmp_path / "ok.sh")
    got = resolve(make_job())
    assert (got.git_commit, got.git_dirty) == ("", False)


def test_provenance_is_empty_in_a_repository_with_no_commits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`git init` alone raises from gitpython rather than reporting a missing
    repository, and it is just as legitimately provenance-less."""
    root = tmp_path / "actions"
    root.mkdir()
    _write_action(root / "ok.sh")
    _git(root, "init", "-q")
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(root))
    got = resolve(make_job())
    assert (got.git_commit, got.git_dirty) == ("", False)
