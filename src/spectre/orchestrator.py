from __future__ import annotations

from datetime import UTC, datetime

from spectre.builder import build
from spectre.checker import pre_check
from spectre.models import (
    Deployment,
    DeploymentStatus,
    Strategy,
)
from spectre.state import append_deployment
from spectre.strategies import run as run_strategy


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    service: str,
    environment: str,
    version: str,
    build_type: str = "docker",
    deploy_type: str = "docker-compose",
    strategy: str = "rolling",
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
    strategy_enum = Strategy(strategy)

    strat_steps = run_strategy(
        strategy_enum, service, version, deploy_type, health_url,
        compose_file=compose_file,
        namespace=namespace,
        kube_context=kube_context,
        env_vars=env_vars,
    )
    deployment.steps.extend(strat_steps)

    failed = any(s.status != DeploymentStatus.healthy for s in strat_steps)
    if failed:
        deployment.status = DeploymentStatus.failed
        deployment.completed_at = _now()
        append_deployment(deployment)
        return deployment

    deployment.status = DeploymentStatus.healthy
    deployment.completed_at = _now()
    append_deployment(deployment)
    return deployment
