from __future__ import annotations

import json
import shutil
import subprocess

from spectre.findings import Finding, ScanResult, Severity

DOMAIN = "kubernetes"


def _kubectl(args: list[str]) -> dict | None:
    if shutil.which("kubectl") is None:
        return None
    try:
        out = subprocess.run(
            ["kubectl", *args], capture_output=True, text=True, timeout=30
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return None


def _analyze_pods(data: dict) -> list[Finding]:
    findings: list[Finding] = []
    items = data.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = f"{meta.get('namespace', 'default')}/{meta.get('name', 'unknown')}"
        spec = item.get("spec", {})
        for container in spec.get("containers", []):
            cname = container.get("name", "container")
            ctx = container.get("securityContext", {})
            if ctx.get("privileged"):
                findings.append(
                    Finding(
                        DOMAIN,
                        f"Privileged container in {name}",
                        Severity.critical,
                        f"container {cname} has securityContext.privileged=true",
                        "Remove privileged mode; use least-privilege capabilities.",
                    )
                )
            run_as = ctx.get("runAsNonRoot")
            if run_as is False:
                findings.append(
                    Finding(
                        DOMAIN,
                        f"Root container in {name}",
                        Severity.high,
                        f"container {cname} has runAsNonRoot=false",
                        "Set runAsNonRoot=true and a non-zero runAsUser.",
                    )
                )
            if "hostPath" in container:
                findings.append(
                    Finding(
                        DOMAIN,
                        f"Host path mount in {name}",
                        Severity.high,
                        f"container {cname} mounts hostPath",
                        "Avoid hostPath mounts; use volumes or emptyDir.",
                    )
                )
    return findings


def _check_network_policies() -> list[Finding]:
    np = _kubectl(["get", "networkpolicies", "-A", "-o", "json"])
    if np is None:
        return []
    if not np.get("items"):
        return [
            Finding(
                DOMAIN,
                "No NetworkPolicies defined",
                Severity.medium,
                "kubectl get networkpolicies -A returned no items",
                "Define default-deny and explicit allow NetworkPolicies.",
            )
        ]
    return []


def check() -> ScanResult:
    pods = _kubectl(["get", "pods", "-A", "-o", "json"])
    if pods is None:
        return ScanResult(
            DOMAIN,
            [
                Finding(
                    DOMAIN,
                    "kubectl unavailable or not authorized",
                    Severity.medium,
                    "Cannot reach the Kubernetes API (kubectl missing or no context)",
                    "Install kubectl and configure a kubeconfig with read access.",
                )
            ],
        )
    findings = _analyze_pods(pods)
    findings += _check_network_policies()
    return ScanResult(DOMAIN, findings)
