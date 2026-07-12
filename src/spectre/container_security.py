from __future__ import annotations

import json
import re
import shutil
import subprocess

from spectre.findings import Finding, ScanResult, Severity

DOMAIN = "container"


def _runtime() -> str | None:
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    return None


def _list_images(rt: str) -> list[str]:
    out = subprocess.run(
        [rt, "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
    ).stdout
    images = [i.strip() for i in out.splitlines() if i.strip()]
    return [i for i in images if i and i != ":"] or []


def _inspect(rt: str, image: str) -> dict | None:
    out = subprocess.run(
        [rt, "inspect", image], capture_output=True, text=True
    )
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
        return data[0] if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


SECRET_KEY_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key|auth)")


def _analyze(image: str, data: dict) -> list[Finding]:
    findings: list[Finding] = []
    cfg = data.get("Config", {}) or data.get("config", {}) or {}
    user = cfg.get("User", "") or "root(0)"
    if user in ("", "0", "root"):
        findings.append(
            Finding(
                DOMAIN,
                f"Image runs as root: {image}",
                Severity.high,
                f"Image {image} has User='{user or 'unset'}' (defaults to root)",
                "Build the image with a non-root USER.",
            )
        )
    if image.endswith(":latest") or ":" not in image:
        findings.append(
            Finding(
                DOMAIN,
                f"Image uses mutable tag: {image}",
                Severity.medium,
                f"Image {image} uses :latest or untagged reference",
                "Pin images to an immutable digest or specific version tag.",
            )
        )
    elif "@sha256:" not in image:
        findings.append(
            Finding(
                DOMAIN,
                f"Image not pinned to a digest: {image}",
                Severity.low,
                f"Image {image} referenced by tag, not @sha256 digest",
                "Pin the image to an immutable digest for reproducibility.",
            )
        )
    if data.get("HostConfig", {}).get("Privileged"):
        findings.append(
            Finding(
                DOMAIN,
                f"Privileged container image: {image}",
                Severity.critical,
                f"Image {image} configured with Privileged=true",
                "Do not run privileged containers; drop capabilities instead.",
            )
        )
    caps = data.get("HostConfig", {}).get("CapAdd") or []
    if caps:
        findings.append(
            Finding(
                DOMAIN,
                f"Added capabilities in {image}",
                Severity.medium,
                f"Image {image} adds capabilities: {', '.join(caps)}",
                "Avoid CapAdd; run with the default capability set.",
            )
        )
    if data.get("HostConfig", {}).get("ReadonlyRootfs") is False:
        findings.append(
            Finding(
                DOMAIN,
                f"Writable root filesystem: {image}",
                Severity.medium,
                f"Image {image} runs with ReadonlyRootfs=false",
                "Run containers with a read-only root filesystem.",
            )
        )
    if not cfg.get("Healthcheck"):
        findings.append(
            Finding(
                DOMAIN,
                f"No HEALTHCHECK defined: {image}",
                Severity.low,
                f"Image {image} has no healthcheck configured",
                "Add a HEALTHCHECK to enable orchestrator health detection.",
            )
        )
    for env in cfg.get("Env", []) or []:
        if "=" not in env:
            continue
        key, _, value = env.partition("=")
        if SECRET_KEY_RE.search(key) and value:
            findings.append(
                Finding(
                    DOMAIN,
                    f"Possible secret in image env: {image}",
                    Severity.high,
                    f"Image {image} embeds '{key}' with a non-empty value",
                    "Inject secrets at runtime via a secret manager, not the image.",
                )
            )
            break
    return findings


def check() -> ScanResult:
    rt = _runtime()
    if rt is None:
        return ScanResult(
            DOMAIN,
            [
                Finding(
                    DOMAIN,
                    "No container runtime available",
                    Severity.medium,
                    "podman and docker both unavailable",
                    "Install podman or docker to enable image scanning.",
                )
            ],
        )
    findings: list[Finding] = []
    for image in _list_images(rt):
        data = _inspect(rt, image)
        if data is None:
            continue
        findings += _analyze(image, data)
    if not findings:
        findings.append(
            Finding(
                DOMAIN,
                "No container image issues detected",
                Severity.info,
                f"{rt} image scan completed",
                "No action required.",
            )
        )
    return ScanResult(DOMAIN, findings)
