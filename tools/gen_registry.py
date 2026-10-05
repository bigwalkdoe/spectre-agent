#!/usr/bin/python3
"""Regenerate `packages/dispatch/registry_data.json` from the maintenance suite.

One-off tooling, committed so the registry can be regenerated and diffed against
the suite tree. Regeneration is a MANUAL verification step, deliberately not a
test: this script reads the real suite checkout at `$SPECTRE_SUITE_ROOT`, which
the hermetic test suite must never touch. Drift between this script and the
committed JSON is caught by `spectre actions verify` (Plan 3), which takes an
injectable host inventory.

    SPECTRE_SUITE_ROOT=/path/to/spectre-system-maintenance-suite \
      /usr/bin/python3 tools/gen_registry.py

Writes exactly one file, next to this script's repository. Reads the suite tree
read-only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "packages" / "dispatch" / "registry_data.json"

SUITE_ROOT = Path(os.environ.get("SPECTRE_SUITE_ROOT", "/home/deon/dev/github/spectre-system-maintenance-suite"))
SCRIPTS = SUITE_ROOT / "scripts"

# The label-exec-context helper is a systemd glue script, not a dispatchable job.
EXCLUDED = {"systemd/label-exec-context.sh"}

# Load-time defaults, mirrored in packages/dispatch/registry.py.
DEFAULTS: dict[str, Any] = {
    "sudo": False,
    "timeout": 1800,
    "mutates": False,
    "concurrency": "allow",
    "schedule_hint": None,
    "replaces": [],
}

# Verified host inventory: the crontab entries and systemd units each job
# supersedes. A unit that was never installed on this host is deliberately
# absent — `replaces` is the ledger of live schedulers, not of shipped files.
REPLACES: dict[str, list[str]] = {
    "backups/backup-databases": ["crontab:0 1 * * *"],
    "backups/backup-all": ["crontab:0 2 * * 6", "user:backup.service"],
    "backups/replicate-backups": ["crontab:40 4 * * *"],
    "backups/check-backup-health": ["crontab:50 4 * * *"],
    "maintenance/vacuum-databases": ["crontab:30 2 * * *"],
    "maintenance/cleanup-temp": ["crontab:0 2 * * *"],
    "maintenance/cleanup-downloads": ["crontab:0 3 * * 0"],
    "maintenance/cleanup-cache": ["crontab:0 4 * * 1"],
    "maintenance/cleanup-unused-resources": ["crontab:0 4 * * 0", "user:docker-cleanup.service"],
    "maintenance/check-disk-space": ["system:disk-space-check.service"],
    "performance/check-performance": ["system:performance-check.service", "user:performance-check.service"],
    "security/run-security-hardening": ["system:security-scan.service", "user:security-scan.service"],
    "maintenance/run-maintenance": ["user:maintenance.service"],
    "maintenance/network-monitor": ["user:network-monitor.service"],
}

# Sourced from each script's own header comment; condensed to one line.
SUMMARIES: dict[str, str] = {
    # backups/
    "backups/backup-all": "Run every backup job and print a summary report",
    "backups/backup-configurations": "Back up system and application configuration files",
    "backups/backup-databases": "Back up PostgreSQL and Redis databases",
    "backups/backup-docker-volumes": "Back up this Compose project's named Docker volumes",
    "backups/backup-encryption": "Encrypt backup archives before they leave the host",
    "backups/backup-projects": "Back up critical project directories",
    "backups/backup-verification": "Verify backup integrity and completeness",
    "backups/check-backup-health": "Verify backups exist, are readable, non-empty and recent",
    "backups/replicate-backups": "Replicate backups to a remote host, S3 and/or B2",
    "backups/restore-databases": "Restore PostgreSQL databases from backup archives",
    "backups/restore-docker-volumes": "Restore named Docker volumes from archives",
    "backups/restore-from-remote": "Restore data from off-site backup locations",
    "backups/setup-offsite-backup": "Configure rsync, S3 and B2 off-site backup destinations",
    # top level
    "check-config-consistency": "Check monitoring config names real services and targets",
    "check-docs-references": "Fail when docs tell a reader to run a script that is absent",
    "deploy-enhanced-monitoring": "Deploy the enhanced monitoring components",
    "deploy-monitoring": "Deploy the Prometheus and Grafana monitoring stack",
    "detect-distribution": "Detect the Linux distribution and set package-manager paths",
    "setup-grafana-dashboards": "Install the Grafana dashboards",
    "setup-notification-channels": "Configure Alertmanager notification channels and prove delivery",
    "setup-prometheus-alerts": "Copy the Prometheus alert rules into the Prometheus container",
    # maintenance/
    "maintenance/audit-trail": "Generate centralized audit logs for system activity",
    "maintenance/check-disk-space": "Monitor disk usage and alert on low space",
    "maintenance/check-performance": "Monitor system performance metrics and alert on anomalies",
    "maintenance/cleanup-cache": "Remove cache files older than the configured age",
    "maintenance/cleanup-downloads": "Remove old files from the downloads directory",
    "maintenance/cleanup-logs": "Rotate and prune logs",
    "maintenance/cleanup-system": "Run distribution-agnostic system maintenance tasks",
    "maintenance/cleanup-temp": "Remove old files from the temporary directories",
    "maintenance/cleanup-unused-resources": "Reclaim unused Docker resources and stale backups",
    "maintenance/compliance-report": "Generate compliance reports for security and operations",
    "maintenance/network-monitor": "Monitor network connectivity and performance",
    "maintenance/network-security-hardening": "Apply network security best practices",
    "maintenance/run-maintenance": "Run every maintenance task and generate reports",
    "maintenance/system-health-check": "Run a comprehensive system health analysis",
    "maintenance/vacuum-databases": "Vacuum and analyze PostgreSQL databases",
    # ml-anomaly/
    "ml-anomaly/run_ml_pipeline": "Run ML anomaly detection and auto-remediation",
    "ml-anomaly/setup_ml_anomaly": "Set up ML anomaly detection and free-LLM remediation",
    # multi-server/
    "multi-server/manage-servers": "Manage the configured fleet of hosts",
    # network/
    "network/network-monitor": "Monitor network connectivity and performance",
    "network/network-security-hardening": "Apply network security best practices",
    "network/optimize-network-config": "Tune the distribution-agnostic network configuration",
    "network/setup-vpn": "Set up WireGuard server and client configuration",
    # performance/
    "performance/check-performance": "Report CPU and memory usage",
    "performance/cloud-cost-tracker": "Track cloud resource costs",
    "performance/optimize-docker-resources": "Set resource limits on Compose containers",
    "performance/optimize-system-performance": "Apply system performance optimizations",
    "performance/resource-rightsizing": "Analyze usage and recommend rightsizing",
    # project-specific/
    "project-specific/backup-all-projects": "Back up every configured project",
    "project-specific/backup-modelink": "Back up the Modelink project with its own configuration",
    "project-specific/health-check-modelink": "Health-check the Modelink project",
    # security/
    "security/advanced-threat-detection": "Run advanced threat detection and response",
    "security/api-security-hardening": "Harden the API surface",
    "security/docker-security-hardening": "Harden Docker container security",
    "security/install-ids-ips": "Install and configure Suricata and OSSEC",
    "security/monitor-api-security": "Monitor API security events",
    "security/run-security-hardening": "Run every security job and report findings",
    "security/scan-dependencies": "Scan application dependencies for known vulnerabilities",
    "security/scan-docker-images": "Scan Docker images for known vulnerabilities",
    "security/security-integration": "Wire all security features into one framework",
    "security/setup-rate-limiting": "Install fail2ban and configure API rate limiting",
}

# The plan's override table, as (matcher, overrides). First match wins.
#
# `maintenance/vacuum-databases` is not in the plan's table; it was added on
# 2026-10-06 after an audit of all 14 scheduled jobs found VACUUM/ANALYZE to be
# the only one wrongly left at the read-only defaults. The other three scheduled
# jobs that keep the defaults — check-disk-space, network-monitor,
# check-performance — were audited as genuinely read-only.
OVERRIDES: list[tuple[Any, dict[str, Any]]] = [
    (lambda n: n.startswith("backups/"), {"mutates": True, "concurrency": "forbid"}),
    (lambda n: n.startswith("maintenance/cleanup-"), {"mutates": True, "concurrency": "forbid"}),
    (lambda n: n == "maintenance/run-maintenance", {"mutates": True, "concurrency": "forbid"}),
    (lambda n: n == "maintenance/vacuum-databases", {"mutates": True, "concurrency": "forbid"}),
    (lambda n: n.startswith("security/"), {"sudo": True, "mutates": True, "concurrency": "forbid"}),
    (lambda n: n.startswith("network/"), {"sudo": True, "mutates": True}),
    (lambda n: n.startswith("performance/optimize-"), {"sudo": True, "mutates": True}),
    (lambda n: n.startswith(("deploy-", "setup-")), {"sudo": True, "mutates": True}),
    (lambda n: n.startswith("project-specific/"), {"mutates": True, "concurrency": "forbid"}),
]


def group_for(relative: str) -> str:
    """First path segment, or the filename stem for a top-level script."""
    if "/" in relative:
        return relative.split("/", 1)[0]
    return relative.removesuffix(".sh")


def overrides_for(name: str) -> dict[str, Any]:
    for matcher, values in OVERRIDES:
        if matcher(name):
            return dict(values)
    return {}


def schedule_hint_for(replaces: list[str]) -> str | None:
    """The crontab expression this job supersedes, when there is one."""
    for entry in replaces:
        if entry.startswith("crontab:"):
            return entry.removeprefix("crontab:")
    return None


def build_entries(scripts: list[str]) -> list[dict[str, Any]]:
    entries = []
    for relative in scripts:
        name = relative.removesuffix(".sh")
        if name not in SUMMARIES:
            raise ValueError(f"no summary for {name}")

        values = {**DEFAULTS, **overrides_for(name)}

        replaces = REPLACES.get(name, [])
        hint = schedule_hint_for(replaces)
        if hint is not None:
            values["schedule_hint"] = hint
        if replaces:
            values["replaces"] = replaces

        entry: dict[str, Any] = {
            "name": name,
            "action": relative,
            "group": group_for(relative),
            "summary": SUMMARIES[name],
        }
        for key, value in values.items():
            if value != DEFAULTS[key]:
                entry[key] = value
        entries.append(entry)

    entries.sort(key=lambda entry: entry["name"])
    return entries


def main() -> int:
    if not SCRIPTS.is_dir():
        print(f"suite scripts not found: {SCRIPTS}", file=sys.stderr)
        print("set SPECTRE_SUITE_ROOT to the suite checkout", file=sys.stderr)
        return 1

    scripts = sorted(p.relative_to(SCRIPTS).as_posix() for p in SCRIPTS.rglob("*.sh"))
    scripts = [s for s in scripts if s not in EXCLUDED]
    entries = build_entries(scripts)

    unmatched = sorted(set(REPLACES) - {entry["name"] for entry in entries})
    if unmatched:
        print(f"replaces names no discovered script: {unmatched}", file=sys.stderr)
        return 1

    OUT.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")

    deviating = sum(1 for entry in entries if len(entry) > 4)
    print(f"suite root:  {SUITE_ROOT}")
    print(f"wrote {len(entries)} jobs to {OUT}")
    print(f"  deviating from defaults: {deviating}")
    print(f"  with replaces:           {sum(1 for entry in entries if entry.get('replaces'))}")
    print(f"  with schedule_hint:      {sum(1 for entry in entries if entry.get('schedule_hint'))}")
    print(f"  groups:                  {len({entry['group'] for entry in entries})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
