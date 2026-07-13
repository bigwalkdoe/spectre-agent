from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from spectre.findings import Finding, ScanResult, Severity

DOMAIN = "ssh"


def _log_path() -> str | None:
    for cand in ("/var/log/auth.log", "/var/log/secure", "/var/log/auth.log.1"):
        if Path(cand).is_file():
            return cand
    return None


def _read_log() -> str | None:
    path = _log_path()
    if path:
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except PermissionError:
            return None
    if shutil.which("journalctl"):
        out = subprocess.run(
            ["journalctl", "-u", "sshd", "--no-pager", "-n", "5000"],
            capture_output=True,
            text=True,
        ).stdout
        if out.strip():
            return out
    return None


def _analyze(content: str) -> list[Finding]:
    findings: list[Finding] = []
    fail_ips: Counter[str] = Counter()
    invalid_ips: Counter[str] = Counter()
    accepted_password = 0
    fail_re = re.compile(r"Failed password for .* from (\d+\.\d+\.\d+\.\d+)")
    invalid_re = re.compile(r"Invalid user .* from (\d+\.\d+\.\d+\.\d+)")
    accepted_re = re.compile(r"Accepted password for .* from (\d+\.\d+\.\d+\.\d+)")
    for line in content.splitlines():
        m = fail_re.search(line)
        if m:
            fail_ips[m.group(1)] += 1
            continue
        m = invalid_re.search(line)
        if m:
            invalid_ips[m.group(1)] += 1
            continue
        if accepted_re.search(line):
            accepted_password += 1
    for ip, count in fail_ips.items():
        if count >= 10:
            findings.append(
                Finding(
                    DOMAIN,
                    f"SSH brute-force pattern from {ip}",
                    Severity.high,
                    f"{count} failed password attempts from {ip}",
                    f"Block {ip} and review sshd allowlists/fail2ban.",
                )
            )
    for ip, count in invalid_ips.items():
        if count >= 5 and ip not in fail_ips:
            findings.append(
                Finding(
                    DOMAIN,
                    f"SSH probing unknown users from {ip}",
                    Severity.medium,
                    f"{count} 'Invalid user' attempts from {ip}",
                    f"Block {ip}; consider disabling password auth.",
                )
            )
    if accepted_password >= 5:
        findings.append(
            Finding(
                DOMAIN,
                "Frequent password-based SSH logins",
                Severity.medium,
                f"{accepted_password} 'Accepted password' events in sampled window",
                "Prefer key-based auth; disable PasswordAuthentication.",
            )
        )
    if not fail_ips and not invalid_ips and accepted_password == 0:
        findings.append(
            Finding(
                DOMAIN,
                "No SSH auth failures observed in window",
                Severity.info,
                "No 'Failed password' or 'Invalid user' entries in sampled log",
                "No action required.",
            )
        )
    return findings


def _check_fail2ban() -> list[Finding]:
    if shutil.which("fail2ban-client") is None:
        return [
            Finding(
                DOMAIN,
                "fail2ban not installed",
                Severity.medium,
                "fail2ban-client not found on PATH",
                "Install and enable fail2ban to auto-ban brute-force sources.",
            )
        ]
    out = subprocess.run(
        ["fail2ban-client", "status"], capture_output=True, text=True
    ).stdout
    if "Status" not in out:
        return [
            Finding(
                DOMAIN,
                "fail2ban not active",
                Severity.medium,
                "fail2ban-client status returned no active jails",
                "Start the fail2ban service and enable the sshd jail.",
            )
        ]
    return []


def check() -> ScanResult:
    content = _read_log()
    if content is None:
        return ScanResult(
            DOMAIN,
            [
                Finding(
                    DOMAIN,
                    "SSH auth log unavailable",
                    Severity.medium,
                    "Cannot read /var/log/auth.log, /var/log/secure, or journalctl sshd",
                    "Run as root or grant access to auth logs.",
                )
            ],
        )
    findings = _analyze(content)
    findings += _check_fail2ban()
    return ScanResult(DOMAIN, findings)
