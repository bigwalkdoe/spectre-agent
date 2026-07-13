from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from spectre.findings import ScanResult, Severity

DOMAIN = "remediation"


class RemediationStatus(StrEnum):
    applied = "applied"
    skipped = "skipped"
    failed = "failed"
    manual = "manual"
    dry_run = "dry-run"


@dataclass
class RemediationResult:
    domain: str
    title: str
    status: RemediationStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_LINUX_FIXES: dict[str, tuple[str, str, str]] = {
    "Root SSH login not explicitly disabled": (
        "/etc/ssh/sshd_config",
        "PermitRootLogin",
        "no",
    ),
    "SSH password authentication enabled": (
        "/etc/ssh/sshd_config",
        "PasswordAuthentication",
        "no",
    ),
    "Empty SSH passwords permitted": (
        "/etc/ssh/sshd_config",
        "PermitEmptyPasswords",
        "no",
    ),
    "Core dumps not disabled": (
        "/etc/security/limits.conf",
        "* hard core",
        "0",
    ),
    "Password max age too long": (
        "/etc/login.defs",
        "PASS_MAX_DAYS",
        "90",
    ),
    "Password min age not enforced": (
        "/etc/login.defs",
        "PASS_MIN_DAYS",
        "1",
    ),
}

_MANUAL_DOMAINS = {"kubernetes", "firewall", "ssh", "container"}


def _set_kv_file(path: str, key: str, value: str, apply: bool) -> tuple[RemediationStatus, str]:
    p = Path(path)
    if not p.is_file():
        return RemediationStatus.failed, f"file not found: {path}"
    try:
        original = p.read_text(encoding="utf-8", errors="ignore")
    except PermissionError:
        return RemediationStatus.failed, f"permission denied reading {path}"

    target = f"{key} {value}"
    lines = original.splitlines()
    changed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == key or stripped.startswith(key + " "):
            if stripped == target:
                return RemediationStatus.skipped, f"already set: {target}"
            lines[i] = target
            changed = True
            break
    if not changed:
        lines.append(target)
        changed = True

    if not apply:
        return RemediationStatus.dry_run, f"would set: {target}"
    try:
        backup = f"{path}.spectre.bak"
        if not Path(backup).exists():
            shutil.copy2(p, backup)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except PermissionError:
        return RemediationStatus.failed, f"permission denied writing {path}"
    return RemediationStatus.applied, f"set {target} (backup: {backup})"


def _remediate_linux(result: ScanResult, apply: bool) -> list[RemediationResult]:
    out: list[RemediationResult] = []
    for f in result.findings:
        if f.title not in _LINUX_FIXES:
            continue
        path, key, value = _LINUX_FIXES[f.title]
        status, detail = _set_kv_file(path, key, value, apply)
        out.append(RemediationResult(f.domain, f.title, status, detail))
    return out


def _remediate_manual(result: ScanResult) -> list[RemediationResult]:
    out: list[RemediationResult] = []
    for f in result.findings:
        if f.severity in (Severity.critical, Severity.high):
            out.append(
                RemediationResult(
                    f.domain,
                    f.title,
                    RemediationStatus.manual,
                    f"Manual remediation required: {f.recommendation}",
                )
            )
    return out


def remediate(result: ScanResult, apply: bool = False) -> list[RemediationResult]:
    if result.domain == "linux":
        return _remediate_linux(result, apply)
    if result.domain in _MANUAL_DOMAINS:
        return _remediate_manual(result)
    return []
