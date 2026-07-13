from __future__ import annotations

from datetime import UTC, datetime

from spectre.builder import build
from spectre.checker import health_check, pre_check
from spectre.deployer import deploy
from spectre.models import (
    Deployment,
    DeploymentStatus,
)
from spectre.state import append_deployment


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    service: str,
    environment: str,
    version: str,
    build_type: str = "docker",
    deploy_type: str = "docker-compose",
    compose_file: str = "docker-compose.yml",
    health_url: str = "http://localhost:8000/health",
    build_context: str = ".",
    dockerfile: str = "Dockerfile",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> Deployment:
    deployment = Deployment(
        service=service,
        environment=environment,
        version=version,
        status=DeploymentStatus.pending,
        started_at=_now(),
    )

    step = pre_check(service, build_context)
    deployment.steps.append(step)
    if step.status != DeploymentStatus.healthy:
        deployment.status = DeploymentStatus.failed
        deployment.completed_at = _now()
        append_deployment(deployment)
        return deployment

    deployment.status = DeploymentStatus.building
    step = build(service, version, build_type, context=build_context, dockerfile=dockerfile)
    deployment.steps.append(step)
    if step.status != DeploymentStatus.healthy:
        deployment.status = DeploymentStatus.failed
        deployment.completed_at = _now()
        append_deployment(deployment)
        return deployment

    deployment.status = DeploymentStatus.deploying
    step = deploy(
        service, version, deploy_type,
        compose_file=compose_file,
        namespace=namespace,
        kube_context=kube_context,
        env_vars=env_vars,
    )
    deployment.steps.append(step)
    if step.status != DeploymentStatus.healthy:
        deployment.status = DeploymentStatus.failed
        deployment.completed_at = _now()
        append_deployment(deployment)
        return deployment

    step = health_check(health_url)
    deployment.steps.append(step)
    if step.status != DeploymentStatus.healthy:
        deployment.status = DeploymentStatus.failed
        deployment.completed_at = _now()
        append_deployment(deployment)
        return deployment

    deployment.status = DeploymentStatus.healthy
    deployment.completed_at = _now()
    append_deployment(deployment)
    return deployment
