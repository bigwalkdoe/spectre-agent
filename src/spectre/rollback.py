from __future__ import annotations

import subprocess
import time

from spectre.models import DeploymentStatus, Stage, StepResult
from spectre.state import load_state


def rollback(service: str, environment: str) -> list[StepResult]:
    results: list[StepResult] = []
    state = load_state()
    history = [d for d in state if d.service == service and d.environment == environment]
    history.sort(key=lambda d: d.started_at, reverse=True)

    if len(history) < 2:
        results.append(
            StepResult(
                stage=Stage.rollback,
                status=DeploymentStatus.failed,
                message=f"no previous deployment to rollback to for {service}/{environment}",
            )
        )
        return results

    previous = history[1]

    try:
        start = time.monotonic()
        cmd = [
            "docker", "compose",
            "-f", "docker-compose.yml",
            "up", "-d", "--no-deps", service,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        elapsed = int((time.monotonic() - start) * 1000)
        results.append(
            StepResult(
                stage=Stage.rollback,
                status=DeploymentStatus.healthy,
                message=f"rolled back {service} to {previous.version}",
                duration_ms=elapsed,
            )
        )
    except subprocess.TimeoutExpired:
        results.append(
            StepResult(
                stage=Stage.rollback,
                status=DeploymentStatus.failed,
                message="rollback timed out",
            )
        )
    except FileNotFoundError:
        results.append(
            StepResult(
                stage=Stage.rollback,
                status=DeploymentStatus.failed,
                message="docker not found in PATH",
            )
        )

    return results
