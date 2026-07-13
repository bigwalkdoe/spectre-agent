from __future__ import annotations

import subprocess
import time

from spectre.models import DeploymentStatus, Stage, StepResult


def deploy_compose(
    service: str,
    compose_file: str = "docker-compose.yml",
    image_tag: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> StepResult:
    start = time.monotonic()
    env = {**env_vars} if env_vars else None
    if image_tag:
        env = {**(env or {}), "SPECTRE_IMAGE": image_tag}
    try:
        cmd = [
            "docker",
            "compose",
            "-f", compose_file,
            "up",
            "-d",
            "--no-deps",
            service,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            msg = f"deployed {service}"
            if image_tag:
                msg += f" ({image_tag})"
            return StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message=msg,
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "docker compose up failed",
            detail=result.stdout.strip(),
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="docker compose up timed out",
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


def deploy_kubectl(
    service: str,
    image_tag: str,
    namespace: str | None = None,
    context: str | None = None,
) -> StepResult:
    start = time.monotonic()
    try:
        container_name = service.replace("_", "-")
        cmd = ["kubectl", "set", "image", f"deployment/{service}", f"{container_name}={image_tag}"]
        if namespace:
            cmd.extend(["-n", namespace])
        if context:
            cmd.extend(["--context", context])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode == 0:
            return StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message=f"deployed {service} image {image_tag} to kubernetes",
                duration_ms=elapsed,
            )
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message=result.stderr.strip() or "kubectl set image failed",
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="kubectl timed out",
            duration_ms=elapsed,
        )
    except FileNotFoundError:
        elapsed = int((time.monotonic() - start) * 1000)
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="kubectl not found in PATH",
            duration_ms=elapsed,
        )


def _ssh_base_args(
    host: str,
    user: str = "",
    key: str = "",
    port: int = 22,
) -> list[str]:
    args: list[str] = []
    if user:
        args.extend(["-o", f"User={user}"])
    if key:
        args.extend(["-i", key])
    if port and port != 22:
        args.extend(["-p", str(port)])
    args.append(host)
    return args


def deploy_ssh(
    service: str,
    compose_file: str = "docker-compose.yml",
    image_tag: str | None = None,
    hosts: list[str] | None = None,
    ssh_user: str = "",
    ssh_key: str = "",
    ssh_port: int = 22,
    env_vars: dict[str, str] | None = None,
) -> StepResult:
    start = time.monotonic()
    if not hosts:
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.failed,
            message="no SSH hosts configured",
            duration_ms=0,
        )
    host_results: list[str] = []
    all_ok = True
    remote_dir = f"/tmp/spectre-{service}"

    for host in hosts:
        base = _ssh_base_args(host, ssh_user, ssh_key, ssh_port)

        try:
            subprocess.run(
                ["ssh", *base, "mkdir", "-p", remote_dir],
                capture_output=True, text=True, timeout=30,
            )
            user_prefix = f"{ssh_user}@" if ssh_user else ""
            remote_path = f"{user_prefix}{host}:{remote_dir}/docker-compose.yml"
            scp_cmd = ["scp", compose_file, remote_path]
            if ssh_key:
                scp_cmd[1:1] = ["-i", ssh_key]
            subprocess.run(scp_cmd, capture_output=True, text=True, timeout=30)

            env_str = " ".join(
                f"{k}={v}" for k, v in (env_vars or {}).items()
            )
            if image_tag:
                env_str = f"SPECTRE_IMAGE={image_tag} " + env_str
            env_str = env_str.strip()

            prefix = env_str + " " if env_str else ""
            docker_cmd = (
                f"cd {remote_dir} && {prefix}"
                f"docker compose -f docker-compose.yml up -d --no-deps {service}"
            )
            ssh_result = subprocess.run(
                ["ssh", *base, docker_cmd],
                capture_output=True, text=True, timeout=120,
            )
            if ssh_result.returncode == 0:
                host_results.append(f"{host}: ok")
            else:
                host_results.append(f"{host}: {ssh_result.stderr.strip()}")
                all_ok = False
        except subprocess.TimeoutExpired:
            host_results.append(f"{host}: timed out")
            all_ok = False
        except FileNotFoundError:
            host_results.append(f"{host}: ssh/scp not found in PATH")
            all_ok = False

    elapsed = int((time.monotonic() - start) * 1000)
    detail = "; ".join(host_results)
    if all_ok:
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.healthy,
            message=f"deployed {service} to {len(hosts)} remote host(s)",
            detail=detail,
            duration_ms=elapsed,
        )
    return StepResult(
        stage=Stage.deploy,
        status=DeploymentStatus.failed,
        message="SSH deploy failed on one or more hosts",
        detail=detail,
        duration_ms=elapsed,
    )


def compose_stop_ssh(
    service: str,
    compose_file: str = "docker-compose.yml",
    hosts: list[str] | None = None,
    ssh_user: str = "",
    ssh_key: str = "",
    ssh_port: int = 22,
) -> StepResult:
    start = time.monotonic()
    if not hosts:
        return StepResult(
            stage=Stage.deploy,
            status=DeploymentStatus.healthy,
            message="no SSH hosts to clean up",
            duration_ms=0,
        )
    host_results: list[str] = []
    all_ok = True
    remote_dir = f"/tmp/spectre-{service}"

    for host in hosts:
        base = _ssh_base_args(host, ssh_user, ssh_key, ssh_port)
        try:
            result = subprocess.run(
                ["ssh", *base,
                 f"cd {remote_dir} && docker compose -f docker-compose.yml rm -fvs {service}"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                host_results.append(f"{host}: ok")
            else:
                host_results.append(f"{host}: {result.stderr.strip()}")
                all_ok = False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            host_results.append(f"{host}: {e}")
            all_ok = False

    elapsed = int((time.monotonic() - start) * 1000)
    status = DeploymentStatus.healthy if all_ok else DeploymentStatus.failed
    return StepResult(
        stage=Stage.deploy,
        status=status,
        message=f"stopped {service} on {len(hosts)} remote host(s)",
        detail="; ".join(host_results),
        duration_ms=elapsed,
    )


def compose_stop(
    service: str,
    compose_file: str = "docker-compose.yml",
) -> StepResult:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "rm", "-fvs", service],
            capture_output=True, text=True, timeout=60,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        status = DeploymentStatus.healthy if result.returncode == 0 else DeploymentStatus.failed
        return StepResult(
            stage=Stage.deploy,
            status=status,
            message=f"stopped {service}" if status == DeploymentStatus.healthy
                    else (result.stderr.strip() or "docker compose rm failed"),
            duration_ms=elapsed,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            stage=Stage.deploy, status=DeploymentStatus.failed,
            message="docker compose rm timed out",
        )
    except FileNotFoundError:
        return StepResult(
            stage=Stage.deploy, status=DeploymentStatus.failed,
            message="docker not found in PATH",
        )


def _image_tag(service: str, version: str, registry: str = "", image_name: str = "") -> str:
    name = image_name or service
    if registry:
        return f"{registry}/{name}:{version}"
    return f"{service}:{version}"


def deploy(
    service: str,
    version: str,
    deploy_type: str,
    compose_file: str = "docker-compose.yml",
    namespace: str | None = None,
    kube_context: str | None = None,
    env_vars: dict[str, str] | None = None,
    registry: str = "",
    image_name: str = "",
    hosts: list[str] | None = None,
    ssh_user: str = "",
    ssh_key: str = "",
    ssh_port: int = 22,
) -> StepResult:
    tag = _image_tag(service, version, registry, image_name)
    if deploy_type == "docker-compose":
        return deploy_compose(service, compose_file, tag, env_vars)
    if deploy_type == "kubernetes":
        return deploy_kubectl(service, tag, namespace, kube_context)
    if deploy_type == "ssh":
        return deploy_ssh(service, compose_file, tag, hosts, ssh_user, ssh_key, ssh_port, env_vars)
    return StepResult(
        stage=Stage.deploy,
        status=DeploymentStatus.failed,
        message=f"unknown deploy type: {deploy_type}",
    )
