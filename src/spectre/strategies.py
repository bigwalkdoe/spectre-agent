from __future__ import annotations

from spectre.checker import health_check
from spectre.deployer import compose_stop, deploy
from spectre.models import DeploymentStatus, Stage, StepResult, Strategy


def _healthy(step: StepResult) -> bool:
    return step.status == DeploymentStatus.healthy


def rolling(
    service: str,
    version: str,
    deploy_type: str,
    health_url: str,
    compose_file: str = "docker-compose.yml",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> list[StepResult]:
    steps: list[StepResult] = []

    step = deploy(service, version, deploy_type, compose_file, namespace, kube_context, env_vars)
    steps.append(step)
    if not _healthy(step):
        return steps

    step = health_check(health_url)
    steps.append(step)
    return steps


def blue_green(
    service: str,
    version: str,
    deploy_type: str,
    health_url: str,
    compose_file: str = "docker-compose.yml",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> list[StepResult]:
    steps: list[StepResult] = []

    step = deploy(service, version, deploy_type, compose_file, namespace, kube_context, env_vars)
    steps.append(step)
    if not _healthy(step):
        return steps

    step = health_check(health_url)
    steps.append(step)
    if not _healthy(step):
        return steps

    if deploy_type == "docker-compose":
        step = compose_stop(service, compose_file)
        steps.append(step)
    else:
        steps.append(
            StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message="blue-green cleanup handled by kubernetes natively",
            )
        )

    return steps


def canary(
    service: str,
    version: str,
    deploy_type: str,
    health_url: str,
    compose_file: str = "docker-compose.yml",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> list[StepResult]:
    steps: list[StepResult] = []

    step = deploy(service, version, deploy_type, compose_file, namespace, kube_context, env_vars)
    steps.append(step)
    if not _healthy(step):
        return steps

    step = health_check(health_url)
    steps.append(step)
    if not _healthy(step):
        return steps

    step = StepResult(
        stage=Stage.deploy,
        status=DeploymentStatus.healthy,
        message=f"canary {service}@{version} promoted to full rollout",
    )
    steps.append(step)
    return steps


_STRATEGIES = {
    Strategy.rolling: rolling,
    Strategy.blue_green: blue_green,
    Strategy.canary: canary,
}


def run(
    strategy: Strategy | str,
    service: str,
    version: str,
    deploy_type: str,
    health_url: str,
    compose_file: str = "docker-compose.yml",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> list[StepResult]:
    if isinstance(strategy, str):
        try:
            strategy = Strategy(strategy)
        except ValueError:
            strategy = Strategy.rolling
    impl = _STRATEGIES.get(strategy, rolling)
    return impl(
        service, version, deploy_type, health_url,
        compose_file=compose_file,
        namespace=namespace,
        kube_context=kube_context,
        env_vars=env_vars,
    )
