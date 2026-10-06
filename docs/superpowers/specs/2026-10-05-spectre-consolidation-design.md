# Spectre Consolidation — Design Spec

**Date:** 2026-10-05
**Status:** Draft for review
**Canonical repo:** `spectre-system-maintenance-suite` (renaming to `spectre`)

## 1. Intent

Two problems, in priority order:

1. **Phantom state.** Work gets executed from a location that is no longer
   authoritative, or two tools disagree about system state. There have been real
   incidents: a fork under `/home/deon/scripts` "ran nightly for the life of the
   crontab, targeted containers from another project, and reported success over
   empty files."
2. **Too many places to operate.** It is not knowable from memory whether a job
   lives in the suite, the Python agent, or `~/scripts`.

Success means: one repository, one command surface, one authoritative copy of
every job, and a recorded answer to "what ran, from where, at which commit" for
every execution — scheduled or interactive.

Explicitly *not* the goal: rewriting the bash into Python. The scheduled system
works today and must keep working through the migration.

## 2. Current state

Three implementations of substantially the same jobs:

| | contents | status |
|---|---|---|
| `spectre-system-maintenance-suite` | ~90 bash actions, systemd units, crontab, Prometheus/Grafana/OPA, Terraform/Ansible | **live** — owns all scheduling |
| `spectre-system-maintenance-agent` | ~5.8k LOC Python, 8 agents, 31 CLI commands, FastAPI, TUI, daemon, 317 tests | **live** |
| `/home/deon/scripts` | 180 files, not a git repository | **dead fork** |

### 2.1 The fork is a fork

Of the fork's scripts, 30 share a path with the suite: 2 byte-identical
(`performance/resource-rightsizing.sh`, `security/setup-rate-limiting.sh`) and 28
diverged, totalling 2018 lines in the fork against 3441 in the suite. 62 files are
unique to the fork.

### 2.2 The suite duplicates itself

Two divergent copies of the same job inside one repository:
`maintenance/network-monitor.sh` (181 lines) vs `network/monitor-network.sh` (55);
`maintenance/network-security-hardening.sh` (238) vs `network/…` (60);
`maintenance/check-system-performance.sh` (159) vs `performance/…` (27).

### 2.3 The two repos barely talk

`linux_agent` implements health/dnf/flatpak/journal/SELinux/firewall;
`security_agent` implements SELinux/firewall/ports/SSH/secrets. The only coupling
is the suite scraping `GET /api/security/summary` over HTTP. The agent never
invokes a suite script.

### 2.4 The README advertises capabilities that do not exist

Prometheus, Grafana, Alertmanager and blackbox-exporter are running (2 days up).
Loki, Promtail, Wazuh, OWASP ZAP, SonarQube, Trivy, PgBouncer, read-replica,
HashiCorp Vault and the k6/Locust load-testing suite have **no deployment on this
host** and, for the first group, no implementation in the suite repository either.
Their only implementations are in the untracked fork.

### 2.5 Four dispatch paths exist

- 14 crontab entries → all already point into the suite repo (12 into `scripts/`,
  2 into `prometheus/`).
- 10 job-dispatching systemd units → 9 point into the suite repo, 1
  (`fedora-optimize.service`) into the untracked fork wrapper.
- 2 further units run the Python agent itself (`spectre.service`,
  `spectre-api.service`).
- The repository's own `systemd/*.service` files → a third divergent copy,
  dispatching through `/usr/local/bin`. `ml-anomaly-fix.service` points at
  `/opt/spectre-system-maintenance/scripts/ml-anomaly/run_ml_pipeline.sh`, **a path
  that does not exist on this host**. That unit is dead.
- `/usr/local/bin` → 40+ scripts installed from a mix of suite and fork.
  `cleanup-downloads.sh` there is byte-identical to the fork's copy, not the
  suite's.

### 2.5a Two jobs currently run twice

`performance-check` and `security-scan` exist in **both** system and user scope,
and both copies are `enabled` and `active`, pointing at the same script. Each
therefore fires twice per trigger. The consolidation removes the possibility by
construction — one job name, one registry entry, one scheduler — but the
double-run should be treated as a live defect to confirm and retire in Phase 3,
not merely to tidy.

### 2.6 One genuinely live item in the dead fork

```
fedora-optimize.timer          weekly, Persistent=true
  └─> fedora-optimize.service   ConditionPathExists=/home/deon/scripts/fedora-optimize.sh
        └─> /usr/local/sbin/fedora-optimize     (82-byte wrapper)
              └─> exec /home/deon/scripts/fedora-optimize.sh   (814 lines, untracked, root)
```

Deleting or moving that file makes the unit **silently skip**. `ConditionPathExists`
fails, nothing errors, nothing reports, and the job simply stops running.

## 3. Decisions

| # | Decision |
|---|---|
| 1 | One repository, one entry point. Bash survives as dispatched actions. |
| 2 | Canonical repo is the **suite** repo, renamed to `spectre`. |
| 3 | Scheduled work calls `spectre <command>`. Nothing else dispatches a job. |
| 4 | Actions report via a CLI-generated wrapper envelope; structured payloads optional. |
| 5 | The CLI imports the Python agent in-process; bash runs as subprocesses. |
| 6 | The fork is salvaged where live, dropped otherwise. |
| 7 | Everything lives under one `spectre/` namespace (repo infrastructure excepted). |

## 4. Repository layout

```
spectre/                                    ← repo root (renamed from …-suite)
├── spectre/                                ← Python package
│   ├── __main__.py                         ← python -m spectre
│   ├── cli/  api/  tui/  daemon/
│   ├── agents/                             ← from packages/*_agent/
│   │   └── linux/ security/ devops/ monitoring/ ai/ developer/ docs/ publishing/
│   ├── core/  memory/  plugins/  workflow_engine/  config/
│   └── dispatch/                           ← new
│       ├── registry.py  envelope.py  records.py
├── spectre/actions/                        ← the bash, now "actions"
│   ├── backups/(13)  maintenance/(12)  network/(4)  performance/(5)
│   ├── security/(11)  project-specific/(3)  multi-server/(1)
│   ├── ml-anomaly/(4 .sh + 3 .py)
│   └── {detect-distribution,check-config-consistency,check-docs-references,
│        deploy-monitoring,deploy-enhanced-monitoring,setup-prometheus-alerts,
│        setup-grafana-dashboards,setup-notification-channels}.sh
├── spectre/monitoring/
│   ├── prometheus/  grafana-dashboards/  grafana-provisioning/
│   ├── exporters/                          ← the 2 exporter .sh, out of prometheus/
│   └── docker-compose.monitoring.yml
├── spectre/deploy/                         ← was cloud-deployment/
├── spectre/policies/                       ← OPA rego, one home
├── spectre/web-dashboard/
├── spectre/systemd/                        ← regenerated; every unit calls `spectre run`
├── config/  docs/  tests/  .github/        ← repo infrastructure, at root
├── install.sh  pyproject.toml  CHANGELOG.md  SECURITY.md
```

**`actions/` not `scripts/`:** these stop being loose scripts and become the
CLI's dispatched surface with a defined contract.

**Deviation from a literal single namespace:** `docs/`, `tests/`, `config/` and
`.github/` stay at the repository root. Nesting them buys nothing for either
stated pain, while breaking the default paths for pytest, ruff, mypy and every
CI action already in use.

The layout resolves three duplications outright: `security/opa/policies/` and the
fork's `security/opa/policies/` collapse into one `spectre/policies/`; the two
`network-monitor.sh` copies collapse to one; and the shipped systemd units stop
addressing `/usr/local/bin` and the non-existent `/opt/…` path.

## 5. Dispatch layer

### 5.1 Command surface

Actions are namespaced to keep the surface usable — 31 existing commands plus
~90 actions would otherwise be 121 top-level commands.

```bash
spectre run backups/backup-all          # one action
spectre run maintenance/cleanup-cache   # slash-namespaced, mirrors the tree
spectre run security --audit            # group: runs the group's actions in order
spectre actions list                    # every job: sudo / mutates / timeout / schedule
spectre actions show backups/backup-all # resolved path, git commit, owning scheduler
spectre actions verify                  # preflight; also a CI gate
```

### 5.2 Registry

Explicit list in `spectre/dispatch/registry.py` — not filesystem discovery.

```python
Job(
    name="backups/backup-all",
    action="backups/backup-all.sh",
    group="backups",
    summary="Full backup: databases, volumes, configs, projects",
    sudo=False, timeout=1800, mutates=True, concurrency="forbid",
    schedule_hint="0 2 * * 6",
    replaces=["crontab:0 2 * * 6", "user:backup.service"],
)
```

Explicit beats convention-scanning because the metadata is the point. `sudo` and
`mutates` let the CLI refuse a destructive job without confirmation and let the
TUI badge it. `replaces` makes the registry the **migration ledger**: all 19
crontab entries and 10 job-dispatching systemd units mapped to the job
superseding each. That
mapping is how the repoint is proven lossless, and `actions verify` fails if a
live scheduler names a job absent from the registry.

### 5.3 Path resolution

Actions resolve from the installed package location — never `PATH`, never `$PWD`.

```python
root = Path(spectre.__file__).resolve().parent.parent
target = (root / "spectre" / "actions" / job.action).resolve()
if not target.is_relative_to(root):
    raise DispatchError(f"{job.name} resolves outside the checkout: {target}")
```

`resolved_path` and `git rev-parse HEAD` are recorded in the envelope. The
containment check is the specific fix for `fedora-optimize`: a wrapper or symlink
pointing at a stale tree now fails loudly rather than running for a week.

### 5.4 Delegation

Where an agent command already has a bash equivalent, the Python implementation
becomes a delegator. Roughly 30 actions stop having a Python twin.

| agent command | becomes |
|---|---|
| `clean` | dispatches the 6 `maintenance/cleanup-*` actions |
| `backup` / `restore` | dispatches `backups/*` |
| `security --audit` | dispatches `security/run-security-hardening.sh` + audit actions |
| `optimize` | dispatches `performance/optimize-*` |
| `report` | dispatches `compliance-report.sh` / `cloud-cost-tracker.sh` |

Remaining commands stay Python, having no bash equivalent: `doctor`, `status`,
`monitor`, `dashboard`, `kernel`, `workflows`, `plugins`, `models`, `containers`,
`config`, `events`, `service_bus`, `core`, `init`, `import-data`, `export`,
`logs`, `version`, `daemon`, `services`.

### 5.5 `spectre actions verify`

- every registered job resolves to an existing, executable file inside the checkout
- every registered job passes `bash -n`
- every live crontab/systemd entry names a registered job, and every job is
  either scheduled or marked manual
- every unit in `spectre/systemd/` calls `spectre`, not a `/usr/local/bin` or `/opt/…` path
- no action is reachable from both `maintenance/` and its category twin

The last check makes the `network-monitor.sh` duplication permanent-detectable.

## 6. Action contract and run records

### 6.1 Envelope

Generated by the CLI around every invocation, whether or not the script is aware
of it.

```json
{
  "job": "backups/backup-all",
  "trigger": "cron",
  "started_at": "2026-10-05T02:00:00+00:00",
  "duration_ms": 41230,
  "exit_code": 0,
  "resolved_path": "<repo>/spectre/actions/backups/backup-all.sh",
  "git_commit": "f493805",
  "git_dirty": false,
  "stdout_tail": "…", "stderr_tail": "…",
  "status": "success",
  "payload": null
}
```

`git_dirty` matters as much as `git_commit`: a run from a modified checkout is
exactly the "which code actually ran" question.

### 6.2 Storage

Extend the existing `MaintenanceRecord` in `~/.config/spectre/memory.db`
(SQLite via SQLModel). No second database, no new dependency.

```python
class MaintenanceRecord(SQLModel, table=True):
    # existing: timestamp, agent, action, status, log_output, duration_ms
    trigger: str          # cron | systemd | cli | tui | api | daemon
    exit_code: int | None
    resolved_path: str
    git_commit: str
    git_dirty: bool
    payload: str | None
```

### 6.3 Optional structured payload

A script opts in with a fenced block on its final line:

```
```spectre
{"findings":[{"severity":"high","rule":"backup-stale","message":"…"}],"metrics":{"bytes":42}}
```
```

Parsed into `payload`. Anything carrying `findings[]` also lands in the existing
`SecurityIncident` table, which already backs `/api/security/summary` — so bash
findings feed the same Prometheus metrics the Python security agent feeds. One
findings store, two producers. Scripts emitting nothing still get a full envelope,
which keeps this a migration rather than a 90-script rewrite.

### 6.4 Concurrency

Cron overlaps are real: `backup-all` at 02:00 and `vacuum-databases` at 02:30,
plus two exporters every 5 minutes. Default SQLite would raise `database is
locked`. Therefore `PRAGMA journal_mode=WAL` and `busy_timeout=5000` on connect,
and the run record written in one short transaction **after** the subprocess
exits — never held open across it.

### 6.5 Retention

Two exporters on a 5-minute timer produce 210,240 records/year, and `log_output`
is unbounded. `log_output` and the tails are capped at 64 KB, keeping head *and*
tail — a failed backup's first error matters as much as its last line. Pruning
reuses `cleanup-logs.sh`: 90 days for jobs whose `schedule_hint` is sub-hourly,
1 year otherwise.

## 7. Agent integration

### 7.1 One scheduler

After the repoint, crontab, systemd timers and `spectre schedule` would all be
able to run jobs — the second pain reproduced inside the new repo. So:

- **`spectre schedule` retires as a job scheduler.** `schedule run <job>` becomes
  `spectre run <job>`; `add` / `remove` / `list` go. No capability is lost, since
  cron and systemd cover it and are the surfaces actually watched.
- **`spectre workflows` stays** — data-driven YAML orchestration is a different
  concern from scheduling, has 4 test files, and composes over `spectre run`, so
  workflow-invoked jobs land in the same run records.

### 7.2 Daemon

Stops being a scheduler; becomes the long-lived host for TUI, API, plugins and
the event bus. `spectre daemon start|stop|status` remains. **The cron path never
touches it** — a daemon crash must not be able to stop backups.

### 7.3 TUI and API

TUI gains an actions view (sudo/mutates/last-run/last-status) and a runs view fed
from `MaintenanceRecord`. API gains `GET /api/actions`, `GET /api/runs`, and
`POST /api/runs/{job}` — the last being how the TUI triggers a job, so
interactive and scheduled runs differ only by `trigger`.

### 7.4 `GET /api/security/summary`

Stays byte-compatible. Currently a contract between two repos; after the merge it
is internal, but `security-metrics-exporter.sh` still scrapes it and the README
field table remains the specification. Both documented properties survive:
`last_scan_timestamp` derived from recorded scans rather than request time, and
`has_ever_scanned` preserved. Its drift check moves into the merged CI, since a
contract whose two sides share a repository is exactly the kind that lapses
quietly.

### 7.5 Out of scope

The 8 agents each implement the same 8 `BaseAgent` lifecycle methods across 1757
lines, of which only ~35 `_run_*` methods are unique. Collapsing that into a
declarative per-agent spec is worthwhile but is not required by the merge; it
deserves its own change with its own tests.

## 8. Migration

### 8.1 Salvage verdict

Rule applied: *salvage if a live scheduler references it, or it is installed on
`PATH` as a user-facing tool.*

| file | reason |
|---|---|
| `fedora-optimize.sh` (814 L) | weekly root timer via `/usr/local/sbin/fedora-optimize` |
| `archive-project.sh` | present in `/usr/local/bin`; manual tool, unscheduled |

All other fork-unique files are dropped: the Loki stack, Wazuh, ZAP, SonarQube,
load-testing, PgBouncer, read-replica, Vault. Their README claims are corrected
in Phase 5. `resource-rightsizing.sh` and `setup-rate-limiting.sh` were already
byte-identical to suite copies.

### 8.2 Stop installing to `/usr/local/bin`

This permanently kills the contamination class rather than cleaning it once. A
script on `PATH` that nothing should call is phantom state waiting to happen —
and `cleanup-downloads.sh` there is currently the fork's copy. After this change
`/usr/local/bin` receives `spectre` and nothing else. The regenerated units call
`spectre run`, so they no longer need it.

### 8.3 Forwarder shims

A 3-line forwarder at every old path:

```bash
#!/usr/bin/env bash
# transitional forwarder — pre-merge absolute paths land here
exec spectre run backups/backup-all "$@"
```

Cron and systemd keep their existing absolute paths, but all 24 schedulers
instantly begin recording provenance through the CLI *before* anything is
repointed. The migration is observable from the first minute, and repointing
becomes cleanup rather than the risky part.

### 8.4 Phases

| | phase | done when |
|---|---|---|
| 0 | Salvage `fedora-optimize.sh` + `archive-project.sh`; prune `/usr/local/bin` | `fedora-optimize.timer` still fires green |
| 1 | Merge both repos into the `spectre/` tree on a branch; place forwarder shims at all ~90 old paths | nothing on the host has changed |
| 2 | Install the CLI; `spectre actions verify` green | 24 schedulers producing run records |
| 3 | Repoint schedulers one at a time — 14 crontab entries, 10 units — verifying each | `actions verify` shows zero legacy paths |
| 4 | Remove shims; delete `/home/deon/scripts`; archive the agent repo read-only | no path outside the repo is referenced |
| 5 | README truth pass; merged CI | docs match what `actions list` reports |

Each phase is independently verifiable and reversible.

### 8.5 `fedora-optimize` specifically

Becomes a registered job with `sudo=True`; the three-hop chain collapses:

```
before:  timer → service(ConditionPathExists=untracked) → /usr/local/sbin wrapper → untracked script
after:   spectre systemd timer → spectre run host/fedora-optimize   [sudo, recorded, commit known]
```

`ConditionPathExists` is removed because it is what made deletion silent. A
missing action now exits non-zero and says so.

### 8.6 The two agent units need editing too

`spectre.service` runs `python3 -m apps.daemon.main` and `spectre-api.service`
runs `uvicorn apps.api.main:app`. Both module paths change under the new layout,
to `spectre.daemon` and `spectre.api`. These are not action dispatches, so they
are not covered by the forwarder shims and must be updated explicitly in Phase 3.

## 9. Testing and CI

Two configurations become one, keeping every tool already in use.

| gate | tool | source |
|---|---|---|
| Python tests | pytest | agent's 317 |
| Python lint/type | ruff + mypy | agent's `ci.yml` |
| Bash lint | shellcheck + `bash -n` | suite's `lint.yml` |
| Registry consistency | `spectre actions verify` | new |
| Doc drift | merged checker | 2 checks today, merged |

`tests/test_schedule_ownership.sh` stops hardcoding path assertions and reads the
registry's `replaces` map, so scheduler↔registry consistency is one query instead
of a list that drifts.

The doc-drift check gains a clause it lacks today: **the README must not advertise
a capability absent from `actions list`.** That is the check which would have
caught the Loki/Wazuh/ZAP claims, and it keeps Phase 5 from silently regressing.

## 10. Failure modes

| condition | behaviour |
|---|---|
| job not in registry | exit 2, `unknown job`, suggest `spectre actions list` |
| registered but file absent | `missing`, non-zero, names the path — **never** a silent skip |
| resolves outside the checkout | hard error — the stale-copy guard |
| exceeds `timeout` | kill the process *group*, `timeout` status, keep partial output |
| non-zero exit | `failed`, record exit code and stderr tail |
| needs `sudo`, not root, non-interactive | refuse with the exact command to run; do not half-attempt |
| concurrent run of a `concurrency="forbid"` job | refuse, naming the holding PID and start time |
| SQLite busy | WAL + `busy_timeout=5000`; short write after exit |

**Silent skip is a bug class here.** `ConditionPathExists` is precisely how
`fedora-optimize` would have quietly stopped running, so a missing action must
fail loudly.

**`concurrency="forbid"`** defaults to `forbid` for `mutates=True` jobs and
`allow` for read-only ones such as the exporters. Without it, 02:00 `backup-all`
and a hand-run `spectre run backups/backup-all` would interleave against the same
target directory.

## 11. Risks

| risk | mitigation |
|---|---|
| Big-bang rename breaks a scheduler before it is verified | forwarder shims (8.3); Phases 1–2 change no host surface |
| A dropped fork file was actually in use | salvage rule based on live schedulers and `PATH`, not judgement (8.1); Phase 0 completes before any deletion |
| Registry drifts from disk | `actions verify` in CI and as a manual command (5.5) |
| README re-diverges from reality | doc-drift clause on advertised capabilities (9) |
| `/usr/local/bin` re-contaminates | installation stops writing there (8.2); `verify` rejects non-`spectre` unit paths |
| Record store grows without bound | 64 KB output cap and tiered retention (6.5) |
| 317 agent tests break against the new layout | Phase 1 keeps them green; layout change and behaviour change are separable commits |

## 12. Open questions

1. **`arcaden-labs` runs a second Grafana/Prometheus pair** (both containers in
   `Created` state) alongside the standalone pair this repo runs. Out of scope
   here; noted because it is a third monitoring stack.
2. **`spectre.service` (daemon) is `activating`**, having been `active` moments
   earlier. Whether the daemon is flapping should be settled before Phase 2, when
   the daemon's narrowed role is verified.
3. **`performance-check` and `security-scan` run twice** (§2.5a) — enabled and
   active in both system and user scope. Confirm the duplicate execution is real
   (compare run counts on both sides) before Phase 3 retires one of each pair.
4. **Job namespacing.** `spectre run security --audit` runs a group; whether
   groups need ordering or dependency semantics is undecided. Section 5.1
   specifies sequential execution in registry order.
5. **Manual-run approval.** `sudo` and `mutates` are recorded and badged, but
   whether a mutating action invoked from the TUI or API requires explicit
   confirmation is not specified here.
