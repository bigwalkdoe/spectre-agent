from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from spectre.findings import Finding, ScanResult, Severity

DOMAIN = "kubernetes"

SYSTEM_NAMESPACES = {
    "kube-system",
    "kube-node-lease",
    "kube-public",
    "kube-flannel",
    "istio-system",
}


def _kubectl(args: list[str]) -> dict[str, Any] | None:
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


def _is_system(namespace: str) -> bool:
    return namespace in SYSTEM_NAMESPACES


def _analyze_pods(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        namespace = meta.get("namespace", "default")
        name = f"{namespace}/{meta.get('name', 'unknown')}"
        system = _is_system(namespace)
        for container in item.get("spec", {}).get("containers", []):
            cname = container.get("name", "container")
            ctx = container.get("securityContext", {}) or {}
            if ctx.get("privileged"):
                if system:
                    findings.append(
                        Finding(
                            DOMAIN,
                            f"Privileged system container in {name}",
                            Severity.low,
                            f"system container {cname} uses privileged=true",
                            "Confirm this privileged workload is a required system component.",
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        DOMAIN,
                        f"Privileged container in {name}",
                        Severity.critical,
                        f"container {cname} has securityContext.privileged=true",
                        "Remove privileged mode; use least-privilege capabilities.",
                    )
                )
            if ctx.get("runAsNonRoot") is False and not system:
                findings.append(
                    Finding(
                        DOMAIN,
                        f"Root container in {name}",
                        Severity.high,
                        f"container {cname} has runAsNonRoot=false",
                        "Set runAsNonRoot=true and a non-zero runAsUser.",
                    )
                )
            if "hostPath" in container and not system:
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


def _check_rbac() -> list[Finding]:
    bindings = _kubectl(["get", "clusterrolebindings", "-o", "json"])
    if bindings is None:
        return []
    risky: list[str] = []
    for b in bindings.get("items", []):
        role = b.get("roleRef", {}).get("name", "")
        if role in ("cluster-admin", "admin"):
            subjects = b.get("subjects", []) or []
            for s in subjects:
                if s.get("kind") == "User" or s.get("kind") == "Group":
                    risky.append(f"{s.get('kind')}/{s.get('name')}")
    if not risky:
        return []
    return [
        Finding(
            DOMAIN,
            "Broad cluster-admin/ admin RBAC binding",
            Severity.high,
            f"clusterrolebindings grant cluster-admin/admin to: {', '.join(risky)}",
            "Scope bindings to least privilege; avoid cluster-admin for users/groups.",
        )
    ]


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
    findings += _check_rbac()
    findings += _check_network_policies()
    return ScanResult(DOMAIN, findings)
