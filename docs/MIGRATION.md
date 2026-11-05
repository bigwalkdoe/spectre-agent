# Spectre Consolidation — Migration Guide

This document operationalizes the design in
`docs/superpowers/specs/2026-10-05-spectre-consolidation-design.md`.
Each phase is independently verifiable and reversible.

## Phase 0 — Salvage + prune `/usr/local/bin` (host, sudo)

Status: **partially done**. `fedora-optimize.sh` is already absent from the
host, so it cannot be salvaged; its timer silently skips via `ConditionPathExists`.

```bash
sudo systemctl disable --now fedora-optimize.timer fedora-optimize.service
sudo actions/install-host.sh   # repairs venv, installs spectre, shims tracked scripts
```

`install-host.sh` leaves `aws`, `k6`, and other non-script binaries in
`/usr/local/bin` untouched.

## Phase 1 — Repo merge (done)

- All ~90 bash actions live under `actions/` (renamed from `scripts/`).
- Dispatch layer (`packages/dispatch/`) resolves, runs, and records them.
- `spectre actions verify` is the CI gate; currently green (0 findings).
- Transitional forwarder generator: `actions/generate-forwarders.sh <target>`.

## Phase 2 — Install CLI + verify (done for the repo)

```bash
spectre actions verify        # 0 blocking findings
spectre actions list          # 61 jobs
spectre run detect-distribution
```

## Phase 3 — Repoint schedulers (host, sudo, one at a time)

For each of the 14 crontab entries and 10 systemd units:
1. Replace the absolute script path with `spectre run <job>`.
2. Run the job manually; confirm a run record appears (`spectre actions show`).
3. Confirm `spectre actions verify` shows zero `legacy-path` findings.

The two agent units (`spectre.service`, `spectre-api.service`) need their
module paths updated to `spectre.daemon` / `spectre.api` (not covered by
forwarders).

## Phase 4 — Remove shims + delete fork (host)

Only after Phase 3 reports zero legacy paths:
- Remove forwarder shims.
- Delete `/home/deon/scripts`.
- Archive `spectre-agent`'s predecessor repos read-only.

## Phase 5 — README truth pass (done)

README no longer advertises Loki, Wazuh, Trivy, ZAP, SonarQube, Vault,
k6/Locust, PgBouncer, or read-replica (none implemented).

## Open questions (from the design spec)

- `performance-check` and `security-scan` run twice (system + user scope) —
  confirm before retiring one of each in Phase 3.
- Group-running semantics (`spectre run security --audit`) undecided.
- Manual-run approval for `mutates=True` jobs undecided.
EOF
cd /home/deon/dev/github/spectre-agent && git add docs/MIGRATION.md && git commit -m "docs: add MIGRATION.md operationalizing the consolidation phases" 2>&1 | tail -3 && git push origin main 2>&1 | tail -3