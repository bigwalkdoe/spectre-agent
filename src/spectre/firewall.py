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


def _check_default_policy() -> list[Finding]:
    findings: list[Finding] = []
    if shutil.which("ufw"):
        out = subprocess.run(
            ["ufw", "status", "verbose"], capture_output=True, text=True
        ).stdout
        if "Status: active" in out:
            if "Default: deny" not in out and "Default: DROP" not in out:
                findings.append(
                    Finding(
                        DOMAIN,
                        "Firewall default inbound policy is not deny",
                        Severity.high,
                        "ufw default incoming policy is not set to deny/drop",
                        "Set 'ufw default deny incoming'.",
                    )
                )
        return findings
    if shutil.which("iptables"):
        out = subprocess.run(
            ["iptables", "-L", "INPUT", "-n"], capture_output=True, text=True
        ).stdout
        m = re.search(r"Chain INPUT \(policy (\w+)\)", out)
        if m and m.group(1).upper() == "ACCEPT":
            findings.append(
                Finding(
                    DOMAIN,
                    "iptables INPUT chain defaults to ACCEPT",
                    Severity.high,
                    "iptables -L INPUT shows 'policy ACCEPT'",
                    "Set a default DROP policy and allow only required services.",
                )
            )
        elif not out.strip():
            findings.append(
                Finding(
                    DOMAIN,
                    "iptables INPUT chain has no rules",
                    Severity.medium,
                    "iptables -L INPUT returned no rules",
                    "Define explicit allow rules with a default DROP.",
                )
            )
        return findings
    if shutil.which("nft"):
        out = subprocess.run(
            ["nft", "list", "ruleset"], capture_output=True, text=True
        ).stdout
        if out.strip() and "drop" not in out and "reject" not in out:
            findings.append(
                Finding(
                    DOMAIN,
                    "nftables ruleset has no drop/reject",
                    Severity.medium,
                    "nft list ruleset contains no drop or reject statements",
                    "Add a default drop policy to the input chain.",
                )
            )
    return findings


def check() -> ScanResult:
    findings: list[Finding] = []
    findings += _check_firewall_active()
    findings += _check_default_policy()
    findings += _check_open_ports()
    return ScanResult(DOMAIN, findings)
