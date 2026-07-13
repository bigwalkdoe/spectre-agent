from __future__ import annotations

from unittest.mock import patch

from spectre.models import DeploymentStatus, Stage, StepResult, Strategy
from spectre.strategies import blue_green, canary, rolling, run


def _ok(stage: str) -> StepResult:
    return StepResult(stage=stage, status=DeploymentStatus.healthy, message="ok")


def _fail(stage: str) -> StepResult:
    return StepResult(stage=stage, status=DeploymentStatus.failed, message="fail")


def test_rolling_returns_deploy_and_health() -> None:
    with patch("spectre.strategies.deploy", return_value=_ok("deploy")), \
         patch("spectre.strategies.health_check", return_value=_ok("health_check")):
        steps = rolling("api", "v1", "docker-compose", "http://localhost:8000/health")
        assert len(steps) == 2
        assert steps[0].stage in ("deploy", Stage.deploy)
        assert steps[1].stage in ("health_check", Stage.health_check)


def test_rolling_stops_on_deploy_fail() -> None:
    with patch("spectre.strategies.deploy", return_value=_fail("deploy")):
        steps = rolling("api", "v1", "docker-compose", "http://localhost:8000/health")
        assert len(steps) == 1
        assert steps[0].status == DeploymentStatus.failed


def test_green_blue_includes_cleanup() -> None:
    with patch("spectre.strategies.deploy", return_value=_ok("deploy")), \
         patch("spectre.strategies.health_check", return_value=_ok("health_check")), \
         patch("spectre.strategies.compose_stop", return_value=_ok("deploy")):
        steps = blue_green("api", "v1", "docker-compose", "http://localhost:8000/health")
        assert len(steps) == 3


def test_green_blue_stops_on_deploy_fail() -> None:
    with patch("spectre.strategies.deploy", return_value=_fail("deploy")):
        steps = blue_green("api", "v1", "docker-compose", "http://localhost:8000/health")
        assert len(steps) == 1


def test_canary_promotes() -> None:
    with patch("spectre.strategies.deploy", return_value=_ok("deploy")), \
         patch("spectre.strategies.health_check", return_value=_ok("health_check")):
        steps = canary("api", "v1", "docker-compose", "http://localhost:8000/health")
        assert len(steps) == 3
        assert "promoted" in steps[2].message


def test_canary_stops_on_deploy_fail() -> None:
    with patch("spectre.strategies.deploy", return_value=_fail("deploy")):
        steps = canary("api", "v1", "docker-compose", "http://localhost:8000/health")
        assert len(steps) == 1


def test_run_rolling_returns_steps() -> None:
    with patch("spectre.strategies.deploy", return_value=_ok("deploy")), \
         patch("spectre.strategies.health_check", return_value=_ok("health_check")):
        steps = run(
            Strategy.rolling, "api", "v1", "docker-compose",
            "http://localhost:8000/health",
        )
        assert len(steps) == 2


def test_run_string_strategy() -> None:
    with patch("spectre.strategies.deploy", return_value=_ok("deploy")), \
         patch("spectre.strategies.health_check", return_value=_ok("health_check")):
        steps = run(
            "rolling", "api", "v1", "docker-compose",
            "http://localhost:8000/health",
        )
        assert len(steps) == 2


def test_run_invalid_fallback_to_rolling() -> None:
    with patch("spectre.strategies.deploy", return_value=_ok("deploy")), \
         patch("spectre.strategies.health_check", return_value=_ok("health_check")):
        steps = run(
            "bogus", "api", "v1", "docker-compose",
            "http://localhost:8000/health",
        )
        assert len(steps) == 2
