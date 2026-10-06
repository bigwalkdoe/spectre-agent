# Dispatch Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `spectre` a `run` command that executes any maintenance action as a subprocess and records a provenance-bearing envelope for every run, plus an `actions` command group that can prove the registry matches what is actually on disk and what the host schedulers actually reference.

**Architecture:** A new `packages/dispatch/` package holds a checked-in job registry, path resolution that refuses to leave the checkout, envelope construction, subprocess execution, per-job locking, and run-record persistence. `apps/cli/dispatch_cmds.py` registers a `run` command and an `actions` sub-app onto the existing Typer `app`. The actions root is resolved from `SPECTRE_ACTIONS_ROOT`, defaulting to `<repo>/scripts` — which is correct only after the Plan 2 move, so Plan 1 ships the registry as checked-in data and keeps every test hermetic against a tmpdir.

**Tech Stack:** Python 3.11+, Typer, Rich, SQLModel/SQLite, structlog, pytest, ruff, mypy.

**Spec:** `spectre-system-maintenance-suite/docs/superpowers/specs/2026-10-05-spectre-consolidation-design.md` — sections 5 (dispatch layer), 6 (contract and run records), 10 (failure modes). Plans 2 and 3 implement spec sections 4, 7, 8, 9 and are not in scope here.

## Global Constraints

- Every repository is `spectre-system-maintenance-agent`. **This plan does not modify the suite repo** — it only reads it.
- `mypy` runs with `disallow_untyped_defs = true`. Every `def` in this plan is fully annotated, including tests.
- `ruff` line-length is 120, target `py311`, rules `E,F,I,B,UP`.
- `pytest` `testpaths = ["tests"]`, `asyncio_mode = "auto"`. Baseline on `main` is **324 passed**.
- **Run tests as `/usr/bin/python3 -m pytest`, never bare `pytest`.** `~/.local/bin/python3`
  (3.12) shadows `/usr/bin/python3` (3.14) on `PATH` and does not have typer, sqlmodel,
  gitpython or structlog installed; `~/.local/bin/pytest` therefore fails on import.
  `/usr/bin/python3` is the interpreter the project actually runs under.
- `tests/conftest.py` sets `SPECTRE_CONFIG_DIR` to a tmpdir *before* importing anything from `packages.memory.db`, and autouse-stubs `subprocess.run` for five agent modules. **`packages.dispatch.*` must never be added to `_SUBPROCESS_CONSUMERS`** — the dispatch layer is supposed to execute real scripts, and its tests do so against fixture scripts in a tmpdir.
- Tests must be hermetic. No test may read the real `~/.config/spectre`, the real crontab, or the real systemd units. Host inspection is injected, never global.
- `apps/cli/main.py` is already 1542 lines. Do not grow it beyond the two-line registration in Task 7.
- Registry contents are **generated once from the suite tree, then committed as data.** Do not hand-maintain 61 entries, and do not add a runtime filesystem scan.

## Review Focus

Five conditions the spec requires but no happy-path test exercises. Each is pinned to a task below.

1. **An action's real path is a symlink pointing outside the checkout** — the `fedora-optimize` wrapper shape. Dispatch must refuse and name the resolved outside path, never execute it.
2. **An action emits more than 64 KB of output** — the two 5-minute exporters will. Envelope keeps head *and* tail with an elision marker; it must never truncate the tail, because the tail carries the exit-bearing lines.
3. **Two invocations of a `concurrency="forbid"` job overlap** — 02:00 cron plus a hand-run. The second must refuse naming the holding PID and start time, and must not have executed anything.
4. **A timed-out action leaves orphaned grandchildren.** The kill must target the process *group*, not the direct child.
5. **SQLite is contended** — two exporters plus a cron job writing simultaneously. The run record must still land after `busy_timeout`.

---

### Task 1: Job registry

**Files:**
- Create: `packages/dispatch/__init__.py`
- Create: `packages/dispatch/registry.py`
- Create: `packages/dispatch/registry_data.json`
- Create: `tests/dispatch/conftest.py`
- Test: `tests/dispatch/test_registry.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `class Job` — frozen dataclass, fields: `name: str`, `action: str`, `group: str`, `summary: str`, `sudo: bool`, `timeout: int`, `mutates: bool`, `concurrency: str`, `schedule_hint: str | None`, `replaces: list[str]`.
  - `JOBS: list[Job]` — all registered jobs, sorted by `name`.
  - `def get_job(name: str) -> Job` — raises `KeyError` if absent.
  - `def jobs_in_group(group: str) -> list[Job]` — sorted by `name`.
  - `def groups() -> list[str]` — sorted unique group names.
  - `tests/dispatch/conftest.py` exposes `make_job`, used by Tasks 2, 4, 5, 8:
    `def make_job(action: str = "ok.sh", **overrides: object) -> Job` — builds a
    `Job` from `action` with test-friendly defaults (`group="t"`, `summary=""`,
    `sudo=False`, `timeout=10`, `mutates=False`, `concurrency="allow"`,
    `schedule_hint=None`, `replaces=[]`), applying `overrides`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_registry.py
from packages.dispatch.registry import JOBS, Job, get_job, groups, jobs_in_group


def test_registry_has_61_jobs() -> None:
    assert len(JOBS) == 61


def test_job_names_are_unique_and_sorted() -> None:
    names = [j.name for j in JOBS]
    assert len(names) == len(set(names))
    assert names == sorted(names)


def test_every_job_name_matches_its_action_path() -> None:
    # name is the action path minus the .sh suffix
    for j in JOBS:
        assert j.name == j.action.removesuffix(".sh")


def test_label_exec_context_helper_is_not_registered() -> None:
    assert not any("label-exec-context" in j.name for j in JOBS)


def test_get_job_raises_for_unknown() -> None:
    try:
        get_job("backups/nope")
    except KeyError as e:
        assert "backups/nope" in str(e)
    else:
        raise AssertionError("expected KeyError")


def test_jobs_in_group_and_groups_agree() -> None:
    assert set(groups()) == {j.group for j in JOBS}
    assert jobs_in_group("backups") == sorted(
        (j for j in JOBS if j.group == "backups"), key=lambda j: j.name
    )


def test_pinned_values() -> None:
    j = get_job("backups/backup-all")
    assert j.sudo is False
    assert j.mutates is True
    assert j.concurrency == "forbid"
    assert j.timeout == 1800

    j = get_job("maintenance/check-disk-space")
    assert j.mutates is False
    assert j.concurrency == "allow"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch'`

- [ ] **Step 3: Implement `registry.py` and the shared test factory**

`Job` as a frozen dataclass with the fields above; `concurrency` constrained to `{"allow", "forbid"}`. `JOBS` loads `registry_data.json` (a sibling file, resolved via `Path(__file__).with_name(...)` so it works from an installed wheel) and validates each entry on load, raising `ValueError` naming the offending job if `concurrency` is invalid or `name` disagrees with `action`.

Defaults applied at load time when a JSON entry omits a key: `sudo=False`, `timeout=1800`, `mutates=False`, `concurrency="allow"`, `schedule_hint=None`, `replaces=[]`.

- [ ] **Step 4: Generate `registry_data.json` from the suite tree**

One-off, not a runtime scan. Enumerate `.sh` files under
`../spectre-system-maintenance-suite/scripts/`, skipping `systemd/label-exec-context.sh`.
Job name is the path relative to `scripts/` minus `.sh`. Group is the first path
segment, except that top-level scripts use their filename stem as the group.

Apply these overrides — everything else takes the defaults:

| jobs | override |
|---|---|
| `backups/*` | `mutates=true`, `concurrency="forbid"` |
| `maintenance/cleanup-*` | `mutates=true`, `concurrency="forbid"` |
| `maintenance/run-maintenance` | `mutates=true`, `concurrency="forbid"` |
| `security/*` | `sudo=true`, `mutates=true`, `concurrency="forbid"` |
| `network/*` | `sudo=true`, `mutates=true` |
| `performance/optimize-*` | `sudo=true`, `mutates=true` |
| `deploy-*`, `setup-*` | `sudo=true`, `mutates=true` |
| `project-specific/*` | `mutates=true`, `concurrency="forbid"` |
| `maintenance/check-*`, `maintenance/system-health-check` | all defaults |

Set `replaces` from the verified host inventory in Step 5.

- [ ] **Step 5: Populate `replaces` from the host inventory**

These are measured facts, not guesses. Populate `replaces` for exactly these,
using the strings verbatim:

- `backups/backup-databases` → `"crontab:0 1 * * *"`
- `backups/backup-all` → `"crontab:0 2 * * 6"`, `"user:backup.service"`
- `backups/replicate-backups` → `"crontab:40 4 * * *"`
- `backups/check-backup-health` → `"crontab:50 4 * * *"`
- `maintenance/vacuum-databases` → `"crontab:30 2 * * *"`
- `maintenance/cleanup-temp` → `"crontab:0 2 * * *"`
- `maintenance/cleanup-downloads` → `"crontab:0 3 * * 0"`
- `maintenance/cleanup-cache` → `"crontab:0 4 * * 1"`
- `maintenance/cleanup-unused-resources` → `"crontab:0 4 * * 0"`, `"user:docker-cleanup.service"`
- `maintenance/check-disk-space` → `"system:disk-space-check.service"`
- `performance/check-performance` → `"system:performance-check.service"`, `"user:performance-check.service"`
- `security/run-security-hardening` → `"system:security-scan.service"`, `"user:security-scan.service"`
- `maintenance/run-maintenance` → `"user:maintenance.service"`
- `maintenance/network-monitor` → `"user:network-monitor.service"`

All other jobs get `replaces: []` and are marked manual.

- [ ] **Step 6: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_registry.py -v`
Expected: PASS, 7 tests

- [ ] **Step 7: Commit**

```bash
git add packages/dispatch/__init__.py packages/dispatch/registry.py \
        packages/dispatch/registry_data.json tests/dispatch/conftest.py \
        tests/dispatch/test_registry.py
git commit -m "feat(dispatch): explicit job registry with migration ledger"
```

---

### Task 2: Path resolution and provenance

**Files:**
- Create: `packages/dispatch/resolve.py`
- Test: `tests/dispatch/test_resolve.py`

**Interfaces:**
- Consumes: `Job` from `packages.dispatch.registry`.
- Produces:
  - `class DispatchError(Exception)` — carries an `exit_code: int` attribute.
  - `class ResolvedAction` — frozen dataclass: `job: Job`, `path: Path`, `git_commit: str`, `git_dirty: bool`.
  - `def actions_root() -> Path` — `$SPECTRE_ACTIONS_ROOT` if set, else `<repo_root>/scripts`.
  - `def resolve(job: Job) -> ResolvedAction` — resolves, enforces containment, reads git provenance.
  - `def repo_root() -> Path` — `Path(packages.dispatch.__file__).resolve().parents[2]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_resolve.py
import os
import subprocess
from pathlib import Path

import pytest

from packages.dispatch.resolve import DispatchError, actions_root, resolve
from tests.dispatch.conftest import make_job


def test_resolve_returns_absolute_path_inside_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    (tmp_path / "ok.sh").write_text("#!/bin/bash\nexit 0\n")
    got = resolve(make_job())
    assert got.path == (tmp_path / "ok.sh").resolve()
    assert got.path.is_relative_to(tmp_path.resolve())


def test_resolve_rejects_symlink_escaping_the_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 1: the fedora-optimize wrapper shape."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "ok.sh").write_text("#!/bin/bash\nexit 0\n")
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
    p.write_text("#!/bin/bash\nexit 0\n")
    p.chmod(0o644)
    with pytest.raises(DispatchError) as e:
        resolve(make_job())
    assert "not executable" in str(e.value)


def test_git_provenance_is_read_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    (tmp_path / "ok.sh").write_text("#!/bin/bash\nexit 0\n")
    got = resolve(make_job())
    assert isinstance(got.git_commit, str)
    assert isinstance(got.git_dirty, bool)


def test_actions_root_defaults_below_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPECTRE_ACTIONS_ROOT", raising=False)
    assert actions_root().name == "scripts"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_resolve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch.resolve'`

- [ ] **Step 3: Implement `resolve.py`**

`repo_root()` walks up from `packages/dispatch/__init__.py`: `parents[0]` is `dispatch`, `[1]` is `packages`, `[2]` is the repo root.

`resolve()` builds `(actions_root() / job.action).resolve()` and applies, in order:
1. containment — `target.is_relative_to(actions_root().resolve())`, else `DispatchError("job <name> resolves outside the actions root: <target>")`
2. existence — else `DispatchError` with `exit_code = 3`
3. executability — `os.access(target, os.X_OK)`, else `DispatchError` naming the path

Git provenance comes from `gitpython` (already a dependency), reading `HEAD` short SHA and dirty state from the repo containing the actions root. Wrap both reads so a non-git directory yields `git_commit=""` and `git_dirty=False` rather than raising — the actions root may legitimately be a plain directory in tests.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_resolve.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add packages/dispatch/resolve.py tests/dispatch/test_resolve.py
git commit -m "feat(dispatch): resolve actions from the checkout with a containment guard"
```

---

### Task 3: Envelope, payload parsing, output truncation

**Files:**
- Create: `packages/dispatch/envelope.py`
- Test: `tests/dispatch/test_envelope.py`

**Interfaces:**
- Consumes: `ResolvedAction` from `packages.dispatch.resolve`.
- Produces:
  - `OUTPUT_LIMIT = 65536`
  - `class Status(str, Enum)` — `SUCCESS`, `FAILED`, `TIMEOUT`, `MISSING`, `REFUSED`.
  - `class Envelope` — frozen dataclass: `job: str`, `trigger: str`, `started_at: datetime`, `duration_ms: int`, `exit_code: int | None`, `resolved_path: str`, `git_commit: str`, `git_dirty: bool`, `stdout_tail: str`, `stderr_tail: str`, `status: Status`, `payload: dict | None`.
  - `def status_for_exit_code(code: int) -> Status` — `0` → `SUCCESS`, else `FAILED`.
  - `def truncate_output(text: str, limit: int = OUTPUT_LIMIT) -> str` — head+tail with a marker naming how many bytes were elided.
  - `def parse_payload(stdout: str) -> dict | None` — extracts a trailing ```` ```spectre ```` fenced JSON block; returns `None` if absent or unparseable, never raises.
  - `def build_envelope(...) -> Envelope`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_envelope.py
import json
from datetime import UTC, datetime

from packages.dispatch.envelope import (
    Envelope, Status, parse_payload, status_for_exit_code, truncate_output,
)


def test_status_comes_from_exit_code_not_output_text() -> None:
    """A script can print 'error' and exit 0, or stay silent and exit 1."""
    assert status_for_exit_code(0) is Status.SUCCESS
    assert status_for_exit_code(1) is Status.FAILED
    assert status_for_exit_code(127) is Status.FAILED


def test_truncate_keeps_head_and_tail() -> None:
    """Review Focus 2: the 5-minute exporters exceed the limit."""
    text = "A" * 100_000
    got = truncate_output(text, limit=1000)
    assert got.startswith("A")
    assert got.endswith("A")
    assert "elided" in got
    assert len(got) < 1000 + 200


def test_truncate_is_a_noop_under_the_limit() -> None:
    assert truncate_output("short", limit=65536) == "short"


def test_parse_payload_reads_trailing_fence() -> None:
    out = "doing work\n```spectre\n" + json.dumps({"metrics": {"bytes": 42}}) + "\n```\n"
    assert parse_payload(out) == {"metrics": {"bytes": 42}}


def test_parse_payload_returns_none_when_absent() -> None:
    assert parse_payload("plain output\n") is None


def test_parse_payload_returns_none_when_invalid_json() -> None:
    assert parse_payload("```spectre\n{not json}\n```\n") is None


def test_parse_payload_ignores_a_non_final_fence() -> None:
    out = "```spectre\n{\"a\": 1}\n```\ntrailing prose\n"
    assert parse_payload(out) is None


def test_envelope_is_immutable() -> None:
    e = Envelope(
        job="backups/backup-all", trigger="cli",
        started_at=datetime.now(UTC), duration_ms=1, exit_code=0,
        resolved_path="/x", git_commit="abc", git_dirty=False,
        stdout_tail="", stderr_tail="", status=Status.SUCCESS, payload=None,
    )
    try:
        e.status = Status.FAILED  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("expected frozen")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_envelope.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch.envelope'`

- [ ] **Step 3: Implement `envelope.py`**

`truncate_output` keeps `limit // 2` bytes from each end and joins them with a
marker of the form `"\n... [{n} bytes elided] ...\n"`, so the total stays under
`limit` plus the marker.

`parse_payload` requires the fence to be the final non-empty content: split on
lines, scan backwards for the closing ``` ``` ```, then backwards again for the
opening ```` ```spectre ````, and `json.loads` what lies between. Any mismatch
returns `None`.

`build_envelope(resolved: ResolvedAction, trigger: str, started_at: datetime,
duration_ms: int, exit_code: int | None, stdout: str, stderr: str,
status: Status) -> Envelope` applies `truncate_output` to both streams and
`parse_payload` to stdout.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_envelope.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add packages/dispatch/envelope.py tests/dispatch/test_envelope.py
git commit -m "feat(dispatch): run envelope with payload parsing and bounded output"
```

---

### Task 4: Runner

**Files:**
- Create: `packages/dispatch/runner.py`
- Test: `tests/dispatch/test_runner.py`

**Interfaces:**
- Consumes: `ResolvedAction` (Task 2), `Envelope` / `Status` / `build_envelope` (Task 3).
- Produces:
  - `class RunOutcome` — frozen dataclass: `envelope: Envelope`, `returncode: int | None`.
  - `def run_action(resolved: ResolvedAction, args: list[str], trigger: str,
    timeout: int | None = None, env: dict[str, str] | None = None) -> RunOutcome`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_runner.py
import os
import stat
import time
from pathlib import Path

import pytest

from packages.dispatch.resolve import resolve
from packages.dispatch.runner import run_action
from tests.dispatch.conftest import make_job


def _write(root: Path, name: str, body: str) -> None:
    p = root / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(root: Path, name: str, body: str, **kw):
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
    """Review Focus 4: a script's own children must die with it."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    marker = tmp_path / "grandchild.txt"
    body = (
        "#!/bin/bash\n"
        f"( sleep 30; touch {marker} ) &\n"
        "sleep 30\n"
    )
    got = _run(tmp_path, "slow.sh", body, timeout=1)
    assert got.envelope.status.value == "timeout"
    time.sleep(2)
    assert not marker.exists(), "grandchild survived the timeout kill"


def test_timeout_keeps_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    _write(tmp_path, "ok.sh", "#!/bin/bash\necho \"arg=$1\"\n")
    got = run_action(resolve(make_job("ok.sh")), ["--apply"], trigger="cli")
    assert "arg=--apply" in got.envelope.stdout_tail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch.runner'`

- [ ] **Step 3: Implement `runner.py`**

Run with `subprocess.Popen(args=[str(resolved.path), *args], stdout=PIPE,
stderr=PIPE, text=True, start_new_session=True, env=merged_env)`.
`start_new_session=True` puts the child in its own process group so a timeout
can `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`, wait 2s, then
`SIGKILL`. Catch `subprocess.TimeoutExpired`, drain whatever was captured, and
return status `TIMEOUT` with `returncode=None`.

On timeout, capture partial output from the pipes rather than discarding it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_runner.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add packages/dispatch/runner.py tests/dispatch/test_runner.py
git commit -m "feat(dispatch): run actions as subprocesses with process-group timeouts"
```

---

### Task 5: Per-job concurrency lock

**Files:**
- Create: `packages/dispatch/lock.py`
- Test: `tests/dispatch/test_lock.py`

**Interfaces:**
- Consumes: `Job` from `packages.dispatch.registry`.
- Produces:
  - `class LockUnavailable(Exception)` — carries `pid: int` and `started_at: datetime`.
  - `class JobLock` — context manager. `__init__(self, job: Job)`, `acquire()`, `release()`.
  - `def lock_path(job: Job) -> Path` — `$SPECTRE_CONFIG_DIR/jobs/<name>.lock`, `SPECTRE_CONFIG_DIR` defaulting to `~/.config/spectre`.
  - `def read_lock(path: Path) -> tuple[int, datetime] | None` — returns `(pid, started_at)`, or `None` if absent or stale.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_lock.py
import os
import time
from pathlib import Path

import pytest

from packages.dispatch.lock import JobLock, LockUnavailable, lock_path
from tests.dispatch.conftest import make_job


def _job(mutates: bool = True, concurrency: str = "forbid"):
    return make_job(
        "backups/backup-all.sh",
        mutates=mutates, concurrency=concurrency, timeout=1800,
    )


def test_allow_concurrency_jobs_never_block(tmp_path: Path) -> None:
    os.environ["SPECTRE_CONFIG_DIR"] = str(tmp_path)
    j = _job(mutates=False, concurrency="allow")
    with JobLock(j):
        with JobLock(j):
            pass


def test_forbid_refuses_the_second_holder(tmp_path: Path) -> None:
    """Review Focus 3: overlapping invocations must not interleave."""
    os.environ["SPECTRE_CONFIG_DIR"] = str(tmp_path)
    j = _job()
    with JobLock(j):
        try:
            JobLock(j).acquire()
        except LockUnavailable as e:
            assert e.pid == os.getpid()
        else:
            raise AssertionError("expected LockUnavailable")


def test_lock_is_released_on_exit(tmp_path: Path) -> None:
    os.environ["SPECTRE_CONFIG_DIR"] = str(tmp_path)
    j = _job()
    with JobLock(j):
        pass
    JobLock(j).acquire()  # must not raise


def test_lock_is_released_when_the_body_raises(tmp_path: Path) -> None:
    os.environ["SPECTRE_CONFIG_DIR"] = str(tmp_path)
    j = _job()
    try:
        with JobLock(j):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    JobLock(j).acquire()


def test_stale_lock_from_a_dead_pid_is_reclaimed(tmp_path: Path) -> None:
    os.environ["SPECTRE_CONFIG_DIR"] = str(tmp_path)
    j = _job()
    p = lock_path(j)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"pid": 999999, "started_at": "2026-01-01T00:00:00+00:00"}')
    with JobLock(j):
        pass


def test_lock_path_uses_the_config_dir(tmp_path: Path) -> None:
    os.environ["SPECTRE_CONFIG_DIR"] = str(tmp_path)
    assert lock_path(_job()) == tmp_path / "jobs" / "backups" / "backup-all.lock"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_lock.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch.lock'`

- [ ] **Step 3: Implement `lock.py`**

`JobLock.__init__` returns immediately into a no-op state when
`job.concurrency == "allow"`. Otherwise `acquire()` does
`mkdir(parents=True, exist_ok=True)` on the lock's parent, then `os.open` with
`O_CREAT | O_EXCL` on the lock file, writing `{"pid": ..., "started_at": ...}`.
On `FileExistsError`, call `read_lock`; if that returns a pid that is not alive
(`os.kill(pid, 0)` raises `ProcessLookupError`) or is older than
`job.timeout * 2`, remove the file and retry once. Otherwise raise
`LockUnavailable(pid, started_at)`.

`release()` unlinks the file only if it still contains this process's pid, so a
reclaimed lock is never deleted out from under its new holder.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_lock.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add packages/dispatch/lock.py tests/dispatch/test_lock.py
git commit -m "feat(dispatch): per-job locks so mutating actions cannot interleave"
```

---

### Task 6: Run records

**Files:**
- Modify: `packages/memory/db.py` — extend `MaintenanceRecord`, add `PRAGMA` setup, add `save_run` / `recent_runs`
- Test: `tests/dispatch/test_records.py`

**Interfaces:**
- Consumes: `Envelope` / `Status` (Task 3).
- Produces:
  - `MaintenanceRecord` gains: `trigger: str`, `exit_code: int | None`, `resolved_path: str`, `git_commit: str`, `git_dirty: bool`, `payload: str | None`, `stderr_tail: str | None`.
  - `def ensure_schema() -> list[str]` — idempotent column additions; returns the names of columns it added. Called from `init_db()`.
  - `def save_run(envelope: Envelope, agent: str = "dispatch") -> int` — returns the new row id. When `envelope.payload` carries a `findings` list, each entry is also inserted into `SecurityIncident` in the same transaction.
  - `def recent_runs(limit: int = 50, job: str | None = None) -> list[MaintenanceRecord]` — newest first.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_records.py
import threading
from datetime import UTC, datetime

from packages.memory.db import MaintenanceRecord, recent_runs, save_run
from packages.dispatch.envelope import Envelope, Status


def _env(job: str = "backups/backup-all", status: Status = Status.SUCCESS,
         payload: dict | None = None) -> Envelope:
    return Envelope(
        job=job, trigger="cron", started_at=datetime.now(UTC), duration_ms=5,
        exit_code=0, resolved_path="/x/backup-all.sh", git_commit="f493805",
        git_dirty=True, stdout_tail="out", stderr_tail="err",
        status=status, payload=payload if payload is not None else {"metrics": {"bytes": 42}},
    )


def test_save_run_round_trips_provenance() -> None:
    rid = save_run(_env())
    row = next(r for r in recent_runs(limit=10) if r.id == rid)
    assert row.trigger == "cron"
    assert row.resolved_path == "/x/backup-all.sh"
    assert row.git_commit == "f493805"
    assert row.git_dirty is True
    assert row.payload is not None and "bytes" in row.payload


def test_recent_runs_filters_by_job() -> None:
    save_run(_env(job="a/one"))
    save_run(_env(job="b/two"))
    got = recent_runs(job="b/two")
    assert got and all(r.action == "b/two" for r in got)


def test_recent_runs_is_newest_first() -> None:
    save_run(_env(job="a/one"))
    save_run(_env(job="a/two"))
    got = recent_runs(job="a/one") + recent_runs(job="a/two")
    ts = [r.timestamp for r in got]
    assert ts == sorted(ts, reverse=True)


def test_concurrent_writers_all_land() -> None:
    """Review Focus 5: exporters and a cron job write simultaneously."""
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(5):
                save_run(_env(job=f"a/{n}-{i}"))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    assert len(recent_runs(limit=200)) >= 20


def test_ensure_schema_adds_columns_to_a_pre_migration_table(tmp_path) -> None:
    """The live DB has 140k rows and no migration tooling. create_all will
    NOT alter it, so ensure_schema must issue the ALTER TABLEs itself."""
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE maintenancerecord (id INTEGER PRIMARY KEY, timestamp DATETIME, "
        "agent VARCHAR, action VARCHAR, status VARCHAR, log_output VARCHAR, duration_ms INTEGER)"
    )
    con.execute(
        "INSERT INTO maintenancerecord (timestamp, agent, action, status, log_output, duration_ms) "
        "VALUES ('2026-01-01 00:00:00', 'linux', 'dnf-upgrade', 'success', 'x', 1)"
    )
    con.commit()
    con.close()

    from packages.memory.db import ensure_schema

    added = ensure_schema(db_path=db)
    assert "trigger" in added and "git_commit" in added

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(maintenancerecord)")}
    assert {"trigger", "exit_code", "resolved_path", "git_commit", "git_dirty", "payload"} <= cols
    assert con.execute("SELECT count(*) FROM maintenancerecord").fetchone()[0] == 1
    con.close()


def test_ensure_schema_is_idempotent(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "new.db"
    sqlite3.connect(db).close()
    from packages.memory.db import ensure_schema

    ensure_schema(db_path=db)
    assert ensure_schema(db_path=db) == []


def test_findings_in_a_payload_become_security_incidents() -> None:
    """Spec 6.3: bash findings feed the same store the Python agent uses,
    so /api/security/summary and the exporter see both producers."""
    from packages.memory.db import get_security_incidents

    save_run(_env(payload={"findings": [
        {"severity": "high", "rule": "backup-stale", "message": "last dump is 9 days old"},
        {"severity": "low", "rule": "log-noise", "message": "…"},
    ]}))
    incidents = get_security_incidents(resolved=False, limit=200)
    assert {"backup-stale", "log-noise"} <= {i.rule_id for i in incidents}
    assert next(i for i in incidents if i.rule_id == "backup-stale").severity == "high"


def test_run_without_findings_creates_no_incidents() -> None:
    from packages.memory.db import get_security_incidents

    before = len(get_security_incidents())
    save_run(_env())
    assert len(get_security_incidents()) == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_records.py -v`
Expected: FAIL — `ImportError: cannot import name 'save_run'`

- [ ] **Step 3: Extend `MaintenanceRecord`, add the migration, and add the PRAGMAs**

Add the six fields from the Interfaces block to the model, giving each a default
so new instances are valid: `trigger="legacy"`, `exit_code=None`,
`resolved_path=""`, `git_commit=""`, `git_dirty=False`, `payload=None`.

**`SQLModel.metadata.create_all()` does not alter an existing table.** The live
`~/.config/spectre/memory.db` is 28 MB with 140,385 `maintenancerecord` rows and
this repo has no Alembic, so without an explicit migration every query against it
raises `OperationalError: no such column: maintenancerecord.trigger`.

Implement `ensure_schema(db_path: Path | None = None) -> list[str]` using raw
sqlite3, not the SQLAlchemy engine:

1. If `db_path` is `None`, use `DB_FILE`.
2. Read `PRAGMA table_info(maintenancerecord)`. If the table does not exist,
   return `[]` — `create_all` will make it with the new columns.
3. For each of the six columns absent from that set, issue
   `ALTER TABLE maintenancerecord ADD COLUMN <name> <type> NOT NULL DEFAULT <default>`,
   using `TEXT DEFAULT ''` for the string columns, `INTEGER` for `exit_code`
   and `git_dirty`, and a nullable `TEXT` for `payload` and `stderr_tail`.
4. Return the list of added column names.

Call `ensure_schema()` from `init_db()` after `SQLModel.metadata.create_all(...)`,
so both a fresh and an existing database end up with the same columns.

Immediately after `create_engine(...)`, wrap the connection setup in a
`@event.listens_for(engine, "connect")` hook that executes
`PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`.

- [ ] **Step 4: Implement `save_run` and `recent_runs`**

`save_run` builds a `MaintenanceRecord` from the envelope — `action=env.job`,
`agent="dispatch"`, `status=env.status.value`, `log_output=env.stdout_tail`,
`stderr_tail=env.stderr_tail`,
`duration_ms=env.duration_ms`, plus the six new fields — serialises `payload`
with `json.dumps` when not `None`, and writes it through the existing
`Session(engine)` pattern.

In the **same** session, if `envelope.payload` has a `findings` list, insert one
`SecurityIncident` per entry mapping `severity` → `severity`, `rule` →
`rule_id`, `message` → `message`, with `resolved=False`. A finding missing
`severity` defaults to `"medium"`; one missing `message` is stored as `""`. Skip
entries that are not dicts. Do this in one transaction so a run record and its
findings cannot diverge.

`recent_runs` uses `select(MaintenanceRecord).order_by(desc(...))` with an
optional `action == job` filter and `.limit(limit)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_records.py -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Run the full suite to confirm nothing regressed**

Run: `/usr/bin/python3 -m pytest -q`
Expected: PASS — the existing 317 tests plus the new ones. Pay attention to
`tests/test_security_summary.py`, which reads `MaintenanceRecord`'s sibling
tables, and `tests/test_models.py`, which may assert on the table schema.

- [ ] **Step 7: Commit**

```bash
git add packages/memory/db.py tests/dispatch/test_records.py
git commit -m "feat(memory): record dispatch provenance and enable WAL for concurrent writers"
```

---

### Task 7: CLI — `spectre run` and `spectre actions`

**Files:**
- Create: `apps/cli/dispatch_cmds.py`
- Modify: `apps/cli/main.py` — add the registration call (2 lines)
- Test: `tests/dispatch/test_cli_dispatch.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces:
  - `def register(app: typer.Typer) -> None` — attaches `run` and the `actions` sub-app.
  - CLI surface: `spectre run <job> [-- args...]`, `spectre actions list|show|verify`.
  - Exit codes: `0` success, `2` unknown job, `3` missing/non-executable action, `4` lock held, `5` run failed or timed out.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_cli_dispatch.py
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app

runner = CliRunner()


def _write(root: Path, name: str, body: str) -> None:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "actions"
    _write(root, "backups/backup-all.sh", "#!/bin/bash\necho backed up\nexit 0\n")
    _write(root, "backups/backup-fail.sh", "#!/bin/bash\necho nope >&2\nexit 3\n")
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(root))
    monkeypatch.setenv("SPECTRE_CONFIG_DIR", str(tmp_path / "cfg"))
    return root


def test_run_executes_and_streams(actions: Path) -> None:
    r = runner.invoke(app, ["run", "backups/backup-all"])
    assert r.exit_code == 0
    assert "backed up" in r.stdout


def test_run_unknown_job_exits_2(actions: Path) -> None:
    r = runner.invoke(app, ["run", "backups/nope"])
    assert r.exit_code == 2
    assert "unknown job" in r.stdout


def test_run_missing_action_exits_3(actions: Path) -> None:
    r = runner.invoke(app, ["run", "backups/backup-databases"])
    assert r.exit_code == 3


def test_run_failure_exits_5_and_records(actions: Path) -> None:
    from packages.memory.db import recent_runs
    r = runner.invoke(app, ["run", "backups/backup-fail"])
    assert r.exit_code == 5
    assert "nope" in r.stdout
    assert any(x.action == "backups/backup-fail" for x in recent_runs(limit=20))


def test_run_records_a_real_commit_when_actions_are_a_repo(actions: Path) -> None:
    """Full wiring: resolve -> provenance -> run record, against a real repo."""
    import subprocess

    from packages.memory.db import recent_runs

    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=actions, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=actions, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=actions, check=True, env=env)

    runner.invoke(app, ["run", "backups/backup-all"])
    row = recent_runs(limit=1)[0]
    expected = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=actions,
        capture_output=True, text=True, check=True, env=env,
    ).stdout.strip()
    assert row.git_commit == expected
    assert row.git_dirty is False


def test_run_forwards_arguments(actions: Path) -> None:
    _write(actions, "backups/backup-all.sh", "#!/bin/bash\necho \"a=$1\"\n")
    r = runner.invoke(app, ["run", "backups/backup-all", "--", "--dry-run"])
    assert "a=--dry-run" in r.stdout


def test_run_records_provenance(actions: Path) -> None:
    from packages.memory.db import recent_runs
    runner.invoke(app, ["run", "backups/backup-all"])
    row = recent_runs(limit=1)[0]
    assert row.trigger == "cli"
    assert row.resolved_path.endswith("backups/backup-all.sh")
    # A plain tmp_path actions root is not a git repository, so provenance
    # degrades to empty rather than raising. Assert the degradation here; the
    # real git-reading path is pinned by tests/dispatch/test_resolve.py.
    assert row.git_commit == ""
    assert row.git_dirty is False


def test_actions_list_shows_the_registry() -> None:
    r = runner.invoke(app, ["actions", "list"])
    assert r.exit_code == 0
    assert "backups/backup-all" in r.stdout
    assert "backups/backup-databases" in r.stdout


def test_actions_show_reports_provenance() -> None:
    r = runner.invoke(app, ["actions", "show", "backups/backup-all"])
    assert r.exit_code == 0
    assert "backup-all.sh" in r.stdout


def test_actions_show_unknown_exits_2() -> None:
    r = runner.invoke(app, ["actions", "show", "nope/nope"])
    assert r.exit_code == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_cli_dispatch.py -v`
Expected: FAIL — `No such command "run"`.

- [ ] **Step 3: Implement `dispatch_cmds.py`**

Build `actions_app = typer.Typer(no_args_is_help=True)` with `list` and `show`
only. `verify` is added in Task 8; registering it here as a stub would be a
command that decides nothing.

`run` is a Typer command taking `job: str` and `args: list[str]` via
`typer.Argument(..., context_settings={"allow_extra_args": True, "ignore_unknown_options": True})`.
Its body: look up the job (unknown → print `unknown job` and `typer.Exit(2)`),
`resolve()` (`DispatchError` → print and exit `e.exit_code`), acquire
`JobLock` (`LockUnavailable` → print holder pid and start, exit 4), `run_action`,
`save_run`, print the summary, then exit `0` on `SUCCESS`, `5` otherwise.
Because `main()` already maps `typer.Exit` to its code, raising is enough.

`register(app)` attaches the `run` command and
`app.add_typer(actions_app, name="actions")`.

- [ ] **Step 4: Register from `main.py`**

Two lines: import `register` from `apps.cli.dispatch_cmds`, and call
`register(app)` immediately after the `app = typer.Typer(...)` construction.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_cli_dispatch.py -v`
Expected: PASS, 9 tests

- [ ] **Step 6: Run the full suite**

Run: `/usr/bin/python3 -m pytest -q`
Expected: PASS. `tests/test_cli.py` enumerates commands via `--help`; confirm
no existing assertion asserts the total command count.

- [ ] **Step 7: Commit**

```bash
git add apps/cli/dispatch_cmds.py apps/cli/main.py tests/dispatch/test_cli_dispatch.py
git commit -m "feat(cli): add spectre run and spectre actions"
```

---

### Task 8: `spectre actions verify`

**Files:**
- Create: `packages/dispatch/verify.py`
- Modify: `apps/cli/dispatch_cmds.py` — add the `verify` command
- Test: `tests/dispatch/test_verify.py`

**Interfaces:**
- Consumes: `JOBS`, `get_job` (Task 1); `actions_root`, `resolve` (Task 2).
- Produces:
  - `class HostInventory` — frozen dataclass, injectable: `cron_entries: list[tuple[str, str]]` (schedule, command), `unit_exec_starts: list[tuple[str, str]]` (unit name, ExecStart).
  - `class Finding` — frozen dataclass: `code: str`, `detail: str`.
  - `def read_host_inventory() -> HostInventory` — the only function that touches the real host; parses `crontab -l` and greps systemd unit files. Never called from tests.
  - `def verify(inventory: HostInventory | None = None) -> list[Finding]` — `None` means call `read_host_inventory()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_verify.py
import stat
from pathlib import Path

import pytest

from packages.dispatch.verify import HostInventory, verify
from tests.dispatch.conftest import make_job


def _mk(tmp_path: Path, name: str, body: str = "#!/bin/bash\nexit 0\n") -> None:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def test_missing_action_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    codes = [f.code for f in verify(HostInventory([], []))]
    assert "missing" in codes
    assert "not-executable" not in codes


def test_non_executable_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _mk(tmp_path, "backups/backup-all.sh")
    (tmp_path / "backups/backup-all.sh").chmod(0o644)
    codes = [f.code for f in verify(HostInventory([], []))]
    assert "not-executable" in codes


def test_syntax_error_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _mk(tmp_path, "backups/backup-all.sh", "#!/bin/bash\nif [\n")
    codes = [f.code for f in verify(HostInventory([], []))]
    assert "syntax" in codes


def test_scheduler_naming_an_unregistered_job_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    inv = HostInventory([("0 1 * * *", "/x/scripts/backups/ghost.sh")], [])
    details = " ".join(f.detail for f in verify(inv))
    assert "ghost" in details


def test_scheduler_calling_a_legacy_path_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    inv = HostInventory(
        [("0 1 * * *", "/usr/local/bin/backup-all.sh")],
        [("legacy.service", "ExecStart=/usr/local/bin/backup-all.sh")],
    )
    codes = [f.code for f in verify(inv)]
    assert "legacy-path" in codes


def test_duplicate_action_in_two_groups_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The network-monitor.sh duplication, made permanently detectable."""
    monkeypatch.setenv("SPECTRE_ACTIONS_ROOT", str(tmp_path))
    _mk(tmp_path, "maintenance/network-monitor.sh")
    _mk(tmp_path, "network/network-monitor.sh")
    import packages.dispatch.verify as verify_mod
    monkeypatch.setattr(verify_mod, "JOBS", [
        make_job("maintenance/network-monitor.sh", group="maintenance"),
        make_job("network/network-monitor.sh", group="network"),
    ])
    findings = [f for f in verify_mod.verify(HostInventory([], [])) if f.code == "duplicate"]
    assert findings
    assert "network-monitor.sh" in findings[0].detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_verify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch.verify'`

- [ ] **Step 3: Implement `verify.py`**

`verify` returns findings for these codes, each `detail` naming the job and the
offending path:

| code | condition |
|---|---|
| `missing` | job's action absent from the actions root |
| `not-executable` | present but `os.access(..., os.X_OK)` is false |
| `syntax` | `bash -n <path>` exits non-zero; detail carries its stderr |
| `legacy-path` | a cron entry or unit ExecStart references a path outside the actions root and outside `spectre` itself |
| `unregistered` | a scheduler references an action basename no registry job claims |
| `duplicate` | two registry jobs share a basename |

`verify` must reference the registry as a module attribute (`from packages.dispatch
import registry` then `registry.JOBS`), not a `from ... import JOBS` binding, so
Task 8's duplicate test can monkeypatch it.

`read_host_inventory()` runs `crontab -l` (empty list on any failure) and reads
`/etc/systemd/system/*.service` plus `~/.config/systemd/user/*.service`,
extracting `ExecStart=` values. It must never raise.

- [ ] **Step 4: Wire `verify` into the CLI**

Add a `verify` command to the existing `actions_app` that prints findings as a Rich
table and exits `1` if any finding has code in `{missing, not-executable,
syntax, duplicate}`, `0` otherwise. `legacy-path` and `unregistered` are
advisory during the migration and exit `0` — Plan 3 is what clears them.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_verify.py -v`
Expected: PASS

- [ ] **Step 6: Run against the real host and record the baseline**

```bash
SPECTRE_ACTIONS_ROOT=../spectre-system-maintenance-suite/scripts \
  /usr/bin/python3 -m apps.cli.main actions verify
```

Expect `missing` findings for every registered job (the tmpdir fixtures are not
present here) — this run confirms the registry's 61 entries each name a real
suite script. Then re-run with the suite scripts staged in a tmpdir copy and
confirm zero `missing`. **Paste the finding counts into the PR description**;
they are the baseline Plan 3 clears.

- [ ] **Step 7: Run the full suite and commit**

```bash
/usr/bin/python3 -m pytest -q
git add packages/dispatch/verify.py apps/cli/dispatch_cmds.py tests/dispatch/test_verify.py
git commit -m "feat(dispatch): spectre actions verify — registry, disk, and scheduler consistency"
```

---
---

### Task 9: Retention prune

**Files:**
- Create: `packages/dispatch/retention.py`
- Test: `tests/dispatch/test_retention.py`

**Interfaces:**
- Consumes: `JOBS`, `get_job` (Task 1).
- Produces:
  - `HIGH_FREQUENCY_JOBS: frozenset[str]` — job names whose `schedule_hint` implies sub-hourly execution; the two Prometheus exporters plus `maintenance/check-disk-space` and `performance/check-performance`.
  - `def cutoff_for(job: Job, now: datetime) -> datetime` — `now - 90 days` for a job in `HIGH_FREQUENCY_JOBS`, else `now - 365 days`.
  - `def prune(now: datetime | None = None) -> dict[str, int]` — deletes `MaintenanceRecord` rows past their job's cutoff; returns `{job_name_or_"unknown": rows_deleted}`.
  - `def record_growth() -> dict[str, int]` — current row count per job, for `spectre actions list`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_retention.py
from datetime import UTC, datetime, timedelta

from packages.dispatch.registry import Job
from packages.dispatch.retention import HIGH_FREQUENCY_JOBS, cutoff_for, prune
from tests.dispatch.conftest import make_job


def _hours_ago(n: int):
    return datetime.now(UTC) - timedelta(hours=n)


def test_high_frequency_jobs_keep_90_days() -> None:
    j = make_job("prometheus/security-metrics-exporter.sh", schedule_hint="*/5 * * * *")
    assert j.name.split("/")[-1] in HIGH_FREQUENCY_JOBS
    assert cutoff_for(j, datetime.now(UTC)) == datetime.now(UTC) - timedelta(days=90)


def test_other_jobs_keep_a_year() -> None:
    j = make_job("backups/backup-all.sh")
    assert cutoff_for(j, datetime.now(UTC)) >= datetime.now(UTC) - timedelta(days=365)


def test_prune_removes_only_expired_rows() -> None:
    from packages.dispatch.envelope import Envelope, Status
    from packages.memory.db import recent_runs, save_run

    def put(job: str, when: datetime) -> None:
        save_run(Envelope(
            job=job, trigger="cron", started_at=when, duration_ms=1, exit_code=0,
            resolved_path="/x", git_commit="", git_dirty=False,
            stdout_tail="", stderr_tail="", status=Status.SUCCESS, payload=None,
        ))

    put("backups/backup-all", _hours_ago(1))        # keep: 1 hour old
    put("backups/backup-all", _hours_ago(24 * 400)) # drop: ~400 days old
    removed = prune()
    assert removed.get("backups/backup-all", 0) >= 1
    assert any(r.timestamp > _hours_ago(24 * 30) for r in recent_runs(limit=500))


def test_prune_is_idempotent() -> None:
    prune()
    assert sum(prune().values()) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_retention.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'packages.dispatch.retention'`

- [ ] **Step 3: Implement `retention.py`**

`cutoff_for` returns `now - timedelta(days=90 or 365)` per the rule above;
`prune` issues one `DELETE FROM maintenancerecord WHERE action = ? AND timestamp < ?`
per job that has rows, using `Session(engine)`. Rows whose `action` matches no
registered job are pruned at the 365-day cutoff under the key `"unknown"`, so a
job removed from the registry cannot pin rows forever.

- [ ] **Step 4: Surface growth in `actions list`**

Add `record_growth()`'s per-job counts as a final column in the existing
`spectre actions list` table.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/dispatch/test_retention.py -v`
Expected: PASS

- [ ] **Step 6: Measure the live database before deciding whether this is urgent**

```bash
/usr/bin/python3 -c "
import sqlite3, os
c = sqlite3.connect(os.path.expanduser('~/.config/spectre/memory.db'))
for t in ('maintenancerecord','securityincident','systemmetric'):
    print(t, c.execute(f'select count(*) from {t}').fetchone()[0])
print('bytes', os.path.getsize(os.path.expanduser('~/.config/spectre/memory.db')))
"
```

`maintenancerecord` already holds ~140k rows in 28 MB, so retention is a live
need rather than a future one. Record the numbers in the PR description; do
**not** delete anything as part of this task — pruning the live database is a
Plan 3 operation, once `actions list` shows the growth it is cleaning up.

- [ ] **Step 7: Commit**

```bash
git add packages/dispatch/retention.py apps/cli/dispatch_cmds.py tests/dispatch/test_retention.py
git commit -m "feat(dispatch): tiered retention for run records and growth reporting"
```


## Definition of Done

- `spectre run <job>` executes any of the 61 registered actions and writes a
  run record carrying `trigger`, `resolved_path`, `git_commit`, `git_dirty`,
  `exit_code`, `duration_ms`, bounded stdout/stderr, and any structured payload.
- `spectre actions list|show|verify` work; `verify` is green against a staged
  copy of the suite scripts.
- A symlinked or missing action fails loudly with a non-zero exit — never a
  silent skip.
- Overlapping runs of a `concurrency="forbid"` job are refused, naming the holder.
- A timed-out action leaves no surviving grandchildren.
- A structured payload's `findings` land in `SecurityIncident`, so
  `/api/security/summary` and the exporter see bash and Python findings alike.
- `prune()` enforces 90-day retention for sub-hourly jobs and 365-day otherwise,
  and `actions list` reports per-job row growth.
- `ensure_schema()` migrates an existing `maintenancerecord` table in place; the
  live 28 MB / 140k-row database survives the schema change with its rows intact.
- `pytest -q` passes with the original 324 tests plus the new ones.
- No test reads the real `~/.config/spectre`, the real crontab, or real systemd units.
- Nothing in the suite repo has been modified, no host scheduler has changed, and
  no live data has been deleted.
