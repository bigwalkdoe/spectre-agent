from __future__ import annotations

import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from spectre.models import DeploymentStatus, Stage, StepResult


def pre_check(service_name: str, context: str = ".") -> StepResult:
    start = time.monotonic()
    checks: list[str] = []

    if not _git_clean(context):
        checks.append("git working tree has uncommitted changes")

    if not _required_tools_available(service_name):
        checks.append("required tools missing (docker, docker-compose, kubectl)")

    elapsed = int((time.monotonic() - start) * 1000)
    if checks:
        return StepResult(
            stage=Stage.pre_check,
            status=DeploymentStatus.failed,
            message="; ".join(checks),
            duration_ms=elapsed,
        )
    return StepResult(
        stage=Stage.pre_check,
        status=DeploymentStatus.healthy,
        message="all pre-deploy checks passed",
        duration_ms=elapsed,
    )


def health_check(url: str, timeout: int = 30, interval: int = 2) -> StepResult:
    start = time.monotonic()
    deadline = start + timeout

    last_error = ""
    while time.monotonic() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=interval) as resp:
                if resp.status == 200:
                    elapsed = int((time.monotonic() - start) * 1000)
                    return StepResult(
                        stage=Stage.health_check,
                        status=DeploymentStatus.healthy,
                        message=f"healthy: HTTP {resp.status}",
                        duration_ms=elapsed,
                    )
                last_error = f"HTTP {resp.status}"
        except URLError as e:
            last_error = str(e.reason)
        except OSError as e:
            last_error = str(e)
        time.sleep(interval)

    elapsed = int((time.monotonic() - start) * 1000)
    return StepResult(
        stage=Stage.health_check,
        status=DeploymentStatus.failed,
        message=f"unhealthy after {timeout}s: {last_error}",
        duration_ms=elapsed,
    )


def _git_clean(context: str = ".") -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=context,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return True


def _required_tools_available(service_name: str) -> bool:
    tools = ["docker"]
    return all(_tool_exists(t) for t in tools)


def _tool_exists(name: str) -> bool:
    try:
        subprocess.run(
            [name, "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
