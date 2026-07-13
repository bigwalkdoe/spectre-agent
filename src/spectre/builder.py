from __future__ import annotations

import subprocess
import time

from spectre.models import DeploymentStatus, Stage, StepResult


def _image_tag(service: str, version: str, registry: str = "", image_name: str = "") -> str:
    name = image_name or service
    if registry:
        return f"{registry}/{name}:{version}"
    return f"{service}:{version}"


def build_docker(
    image_tag: str,
    context: str = ".",
    dockerfile: str = "Dockerfile",
) -> StepResult:
    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                "docker", "build",
                "-t", image_tag,
                "-f", dockerfile,
                context,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            return StepResult(
                stage=Stage.build,
                status=DeploymentStatus.healthy,
                message=f"built {image_tag}",
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.build,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "docker build failed",
            detail=result.stdout.strip(),
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.build,
            status=DeploymentStatus.failed,
            message="docker build timed out after 300s",
            duration_ms=elapsed,
        )
    except FileNotFoundError:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.build,
            status=DeploymentStatus.failed,
            message="docker not found in PATH",
            duration_ms=elapsed,
        )


def docker_push(image_tag: str) -> StepResult:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["docker", "push", image_tag],
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            return StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message=f"pushed {image_tag}",
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "docker push failed",
            detail=result.stdout.strip(),
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="docker push timed out after 300s",
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


def build_pip(package_dir: str = ".") -> StepResult:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["pip", "install", "-e", "."],
            capture_output=True,
            text=True,
            cwd=package_dir,
            timeout=120,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            return StepResult(
                stage=Stage.build,
                status=DeploymentStatus.healthy,
                message=f"installed package from {package_dir}",
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.build,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "pip install failed",
            detail=result.stdout.strip(),
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.build,
            status=DeploymentStatus.failed,
            message="pip install timed out",
            duration_ms=elapsed,
        )


def build(
    service: str, version: str, build_type: str,
    registry: str = "", image_name: str = "",
    **kwargs: str,
) -> StepResult:
    tag = _image_tag(service, version, registry, image_name)
    if build_type == "docker":
        return build_docker(tag, **kwargs)
    if build_type in ("pip", "python"):
        return build_pip(**kwargs)
    return StepResult(
        stage=Stage.build,
        status=DeploymentStatus.failed,
        message=f"unknown build type: {build_type}",
    )
