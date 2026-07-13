from __future__ import annotations

from spectre.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    Service,
    Stage,
    StepResult,
)


def test_deployment_default_status() -> None:
    d = Deployment(service="api", environment="staging", version="v1")
    assert d.status == DeploymentStatus.pending
    assert d.steps == []


def test_deployment_to_dict_roundtrip() -> None:
    d = Deployment(
        service="api",
        environment="staging",
        version="v1",
        status=DeploymentStatus.healthy,
        steps=[
            StepResult(
                stage=Stage.build,
                status=DeploymentStatus.healthy,
                message="built image",
                duration_ms=1200,
            ),
        ],
        started_at="2024-01-01T00:00:00Z",
        completed_at="2024-01-01T00:01:00Z",
    )
    restored = Deployment.from_dict(d.to_dict())
    assert restored.service == "api"
    assert restored.status == DeploymentStatus.healthy
    assert len(restored.steps) == 1
    assert restored.steps[0].stage == Stage.build
    assert restored.steps[0].duration_ms == 1200


def test_step_result_defaults() -> None:
    r = StepResult(stage=Stage.pre_check, status=DeploymentStatus.healthy, message="ok")
    assert r.detail == ""
    assert r.duration_ms == 0


def test_service_from_dict() -> None:
    data = {"name": "api", "build_type": "docker", "port": 9000, "unknown": "ignored"}
    svc = Service.from_dict(data)
    assert svc.name == "api"
    assert svc.build_type == "docker"
    assert svc.port == 9000
    assert not hasattr(svc, "unknown")


def test_environment_from_dict() -> None:
    data = {"name": "prod", "hosts": ["app1"], "extra": "x"}
    env = Environment.from_dict(data)
    assert env.name == "prod"
    assert env.hosts == ["app1"]


def test_deployment_status_enum() -> None:
    assert DeploymentStatus.pending.value == "pending"
    assert DeploymentStatus.healthy.value == "healthy"
    assert DeploymentStatus.failed.value == "failed"
    assert DeploymentStatus.rolled_back.value == "rolled_back"


def test_stage_enum() -> None:
    stages = [s.value for s in Stage]
    assert stages == [
        "pre_check",
        "build",
        "deploy",
        "health_check",
        "record",
        "rollback",
    ]
