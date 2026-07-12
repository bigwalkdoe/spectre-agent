from __future__ import annotations

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


def check() -> ScanResult:
    findings: list[Finding] = []
    findings += _check_ssh()
    findings += _check_updates()
    findings += _check_core_dumps()
    findings += _check_boot_password()
    return ScanResult(DOMAIN, findings)
