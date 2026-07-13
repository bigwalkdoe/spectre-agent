from __future__ import annotations

import subprocess
import time

from spectre.models import DeploymentStatus, Stage, StepResult


def deploy_compose(
    service: str,
    compose_file: str = "docker-compose.yml",
    env_vars: dict[str, str] | None = None,
) -> StepResult:
    start = time.monotonic()
    env = {**env_vars} if env_vars else None
    try:
        cmd = [
            "docker",
            "compose",
            "-f", compose_file,
            "up",
            "-d",
            "--no-deps",
            service,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            return StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message=f"deployed {service} via docker compose",
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "docker compose up failed",
            detail=result.stdout.strip(),
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="docker compose up timed out",
            duration_ms=elapsed,
        )
    except FileNotFoundError:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="docker not found in PATH",
            duration_ms=elapsed,
        )


def deploy_kubectl(
    service: str,
    image_tag: str,
    namespace: str | None = None,
    context: str | None = None,
) -> StepResult:
    start = time.monotonic()
    try:
        cmd = ["kubectl", "set", "image", f"deployment/{service}", f"{service}={image_tag}"]
        if namespace:
            cmd.extend(["-n", namespace])
        if context:
            cmd.extend(["--context", context])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            return StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message=f"deployed {service} image {image_tag} to kubernetes",
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "kubectl set image failed",
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="kubectl timed out",
            duration_ms=elapsed,
        )
    except FileNotFoundError:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="kubectl not found in PATH",
            duration_ms=elapsed,
        )


def deploy(
    service: str,
    version: str,
    deploy_type: str,
    compose_file: str = "docker-compose.yml",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> StepResult:
    if deploy_type == "docker-compose":
        return deploy_compose(service, compose_file, env_vars)
    if deploy_type == "kubernetes":
        image_tag = f"{service}:{version}"
        return deploy_kubectl(service, image_tag, namespace, kube_context)
    return StepResult(
        stage=Stage.deploy,
        status=DeploymentStatus.failed,
        message=f"unknown deploy type: {deploy_type}",
    )
