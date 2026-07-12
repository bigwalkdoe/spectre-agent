from __future__ import annotations

import re
import shutil
import subprocess

from spectre.findings import Finding, ScanResult, Severity

DOMAIN = "firewall"


def _active_backend() -> str:
    if shutil.which("nft") and subprocess.run(
        ["nft", "list", "ruleset"], capture_output=True, text=True
    ).stdout.strip():
        return "nftables"
    if shutil.which("ufw") and "Status: active" in subprocess.run(
        ["ufw", "status", "verbose"], capture_output=True, text=True
    ).stdout:
        return "ufw"
    if shutil.which("iptables"):
        return "iptables"
    return "none"


def _check_firewall_active() -> list[Finding]:
    backend = _active_backend()
    if backend == "none":
        return [
            Finding(
                DOMAIN,
                "No host firewall detected",
                Severity.high,
                "iptables, nftables, and ufw all unavailable or inactive",
                "Install and enable a host firewall (ufw/nftables).",
            )
        ]
    return []


def _check_open_ports() -> list[Finding]:
    findings: list[Finding] = []
    out = subprocess.run(
        ["ss", "-tuln"], capture_output=True, text=True
    ).stdout
    if not out:
        return findings
    risky = {"22", "23", "3389", "6379", "5432", "3306", "9200", "11211"}
    seen: set[str] = set()
    for line in out.splitlines()[1:]:
        m = re.search(r":(\d+)\s", line)
        if not m:
            continue
        port = m.group(1)
        if port in risky and port not in seen:
            seen.add(port)
            findings.append(
                Finding(
                    DOMAIN,
                    f"Sensitive service exposed on port {port}",
                    Severity.high,
                    f"`ss -tuln` shows listener on :{port}",
                    f"Restrict port {port} to trusted networks via the firewall.",
                )
            )
    return findings


def check() -> ScanResult:
    findings: list[Finding] = []
    findings += _check_firewall_active()
    findings += _check_open_ports()
    return ScanResult(DOMAIN, findings)
