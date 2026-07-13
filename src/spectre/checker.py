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


def _single_health(
    url: str,
    timeout: int,
    interval: int,
    expected_codes: set[int],
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout
    current_interval: float = interval
    last_error = ""

    while time.monotonic() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=max(1, int(current_interval))) as resp:
                if resp.status in expected_codes:
                    return True, f"healthy: HTTP {resp.status}"
                last_error = f"HTTP {resp.status} (expected {sorted(expected_codes)})"
        except URLError as e:
            last_error = str(e.reason)
        except OSError as e:
            last_error = str(e)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep_time = min(current_interval, remaining)
        time.sleep(sleep_time)
        current_interval = min(current_interval * 1.5, 10.0)

    return False, last_error


def health_check(
    url: str,
    timeout: int = 30,
    interval: int = 2,
    expected_codes: set[int] | None = None,
) -> StepResult:
    start = time.monotonic()
    codes = expected_codes or {200}
    ok, msg = _single_health(url, timeout, interval, codes)
    elapsed = int((time.monotonic() - start) * 1000)
    if ok:
        return StepResult(
            stage=Stage.health_check,
            status=DeploymentStatus.healthy,
            message=msg,
            duration_ms=elapsed,
        )
    return StepResult(
        stage=Stage.health_check,
        status=DeploymentStatus.failed,
        message=f"unhealthy after {timeout}s: {msg}",
        duration_ms=elapsed,
    )


def health_check_multi(
    urls: list[str],
    timeout: int = 30,
    interval: int = 2,
    expected_codes: set[int] | None = None,
) -> list[StepResult]:
    codes = expected_codes or {200}
    results: list[StepResult] = []
    for url in urls:
        step = health_check(url, timeout, interval, codes)
        results.append(step)
    return results


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
