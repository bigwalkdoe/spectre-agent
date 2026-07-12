from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from spectre.findings import Finding, ScanResult, Severity

DOMAIN = "linux"


def _read_file(path: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except PermissionError:
        return None


def _ssh_setting(name: str, content: str | None) -> str | None:
    if content is None:
        return None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.split(None, 1)[0].lower() == name.lower():
            return stripped.split(None, 1)[1] if " " in stripped else ""
    return None


def _service_active(name: str) -> bool:
    if shutil.which("systemctl") is None:
        out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True)
        return bool(out.stdout.strip())
    out = subprocess.run(
        ["systemctl", "is-active", name], capture_output=True, text=True
    )
    return out.stdout.strip() == "active"


def _check_ssh() -> list[Finding]:
    findings: list[Finding] = []
    cfg = _read_file("/etc/ssh/sshd_config")
    if cfg is None:
        findings.append(
            Finding(
                DOMAIN,
                "sshd_config not readable",
                Severity.medium,
                "Could not read /etc/ssh/sshd_config (permission or missing)",
                "Run the SSH audit as root or verify the file exists.",
            )
        )
        return findings

    root_login = _ssh_setting("PermitRootLogin", cfg)
    if root_login is None or root_login.lower() != "no":
        findings.append(
            Finding(
                DOMAIN,
                "Root SSH login not explicitly disabled",
                Severity.high,
                f"PermitRootLogin={root_login or 'unset (defaults to yes on legacy sshd)'}",
                "Set 'PermitRootLogin no' in /etc/ssh/sshd_config.",
            )
        )

    pwd_auth = _ssh_setting("PasswordAuthentication", cfg)
    if pwd_auth is None or pwd_auth.lower() != "no":
        findings.append(
            Finding(
                DOMAIN,
                "SSH password authentication enabled",
                Severity.medium,
                f"PasswordAuthentication={pwd_auth or 'unset'}",
                "Set 'PasswordAuthentication no' and use key-based auth.",
            )
        )

    empty = _ssh_setting("PermitEmptyPasswords", cfg)
    if empty is None or empty.lower() != "no":
        findings.append(
            Finding(
                DOMAIN,
                "Empty SSH passwords permitted",
                Severity.high,
                f"PermitEmptyPasswords={empty or 'unset (defaults to no, but verify)'}",
                "Set 'PermitEmptyPasswords no'.",
            )
        )

    max_auth = _ssh_setting("MaxAuthTries", cfg)
    if max_auth is None or not max_auth.isdigit() or int(max_auth) > 4:
        findings.append(
            Finding(
                DOMAIN,
                "SSH MaxAuthTries too high",
                Severity.low,
                f"MaxAuthTries={max_auth or 'unset (defaults to 6)'}",
                "Set 'MaxAuthTries 4' or fewer.",
            )
        )

    alive = _ssh_setting("ClientAliveInterval", cfg)
    if alive is None or not alive.isdigit() or int(alive) == 0 or int(alive) > 900:
        findings.append(
            Finding(
                DOMAIN,
                "SSH idle timeout not configured",
                Severity.low,
                f"ClientAliveInterval={alive or 'unset (defaults to 0 = never)'}",
                "Set 'ClientAliveInterval 300' to disconnect idle sessions.",
            )
        )
    return findings


def _check_updates() -> list[Finding]:
    findings: list[Finding] = []
    apt_cfg = _read_file("/etc/apt/apt.conf.d/20auto-upgrades")
    dnf_cfg = Path("/etc/dnf/automatic.conf").is_file()
    if apt_cfg is None and not dnf_cfg:
        findings.append(
            Finding(
                DOMAIN,
                "Automatic security updates not configured",
                Severity.medium,
                "No unattended-upgrades or dnf-automatic configuration detected",
                "Enable unattended security updates.",
            )
        )
    return findings


def _check_core_dumps() -> list[Finding]:
    findings: list[Finding] = []
    limits = _read_file("/etc/security/limits.conf") or ""
    hardened = "* hard core 0" in limits or any(
        "hard core 0" in ln for ln in limits.splitlines()
    )
    if not hardened:
        findings.append(
            Finding(
                DOMAIN,
                "Core dumps not disabled",
                Severity.low,
                "No '* hard core 0' entry in /etc/security/limits.conf",
                "Disable core dumps to reduce info leakage.",
            )
        )
    return findings


def _check_boot_password() -> list[Finding]:
    findings: list[Finding] = []
    grub = _read_file("/etc/grub.d/00_header") or _read_file("/boot/grub2/grub.cfg")
    if grub and "set superusers" not in grub and "password" not in grub.lower():
        findings.append(
            Finding(
                DOMAIN,
                "GRUB bootloader not password protected",
                Severity.low,
                "No superuser/password directive found in GRUB config",
                "Set a GRUB boot password to prevent single-user bypass.",
            )
        )
    return findings


def _check_auditd() -> list[Finding]:
    if not _service_active("auditd"):
        return [
            Finding(
                DOMAIN,
                "auditd not running",
                Severity.medium,
                "auditd service is not active",
                "Enable auditd to record system call and login activity.",
            )
        ]
    return []


def _check_tmp_noexec() -> list[Finding]:
    mounts = _read_file("/proc/mounts") or ""
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "/tmp":
            opts = parts[3]
            if "noexec" not in opts:
                return [
                    Finding(
                        DOMAIN,
                        "/tmp is executable",
                        Severity.low,
                        "/tmp mounted without the noexec option",
                        "Remount /tmp with noexec,nosuid,nodev.",
                    )
                ]
    return []


def _check_password_aging() -> list[Finding]:
    findings: list[Finding] = []
    defs = _read_file("/etc/login.defs")
    if defs is None:
        return findings
    max_days = None
    min_days = None
    for line in defs.splitlines():
        if line.startswith("PASS_MAX_DAYS"):
            max_days = int(line.split()[1])
        elif line.startswith("PASS_MIN_DAYS"):
            min_days = int(line.split()[1])
    if max_days is None or max_days > 365:
        findings.append(
            Finding(
                DOMAIN,
                "Password max age too long",
                Severity.low,
                f"PASS_MAX_DAYS={max_days if max_days is not None else 'unset'}",
                "Set PASS_MAX_DAYS to 90 or fewer.",
            )
        )
    if min_days is None or min_days < 1:
        findings.append(
            Finding(
                DOMAIN,
                "Password min age not enforced",
                Severity.low,
                f"PASS_MIN_DAYS={min_days if min_days is not None else 'unset'}",
                "Set PASS_MIN_DAYS to at least 1 to limit rapid changes.",
            )
        )
    return findings


def check() -> ScanResult:
    findings: list[Finding] = []
    findings += _check_ssh()
    findings += _check_updates()
    findings += _check_core_dumps()
    findings += _check_boot_password()
    findings += _check_auditd()
    findings += _check_tmp_noexec()
    findings += _check_password_aging()
    return ScanResult(DOMAIN, findings)
