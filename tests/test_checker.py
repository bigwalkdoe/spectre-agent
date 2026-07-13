from __future__ import annotations

from spectre.checker import health_check, pre_check
from spectre.models import DeploymentStatus, Stage


def test_pre_check_no_git_context() -> None:
    result = pre_check("api", context="/tmp")
    assert result.stage == Stage.pre_check
    assert result.status in (DeploymentStatus.healthy, DeploymentStatus.failed)
    assert result.duration_ms >= 0


def test_health_check_refused_fast() -> None:
    result = health_check("http://localhost:1/health", timeout=3, interval=1)
    assert result.stage == Stage.health_check
    assert result.status == DeploymentStatus.failed
    assert "unhealthy" in result.message
    assert result.duration_ms >= 0
