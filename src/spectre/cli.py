from __future__ import annotations

import argparse
import os
import sys

from spectre.config import resolve_environment, resolve_service
from spectre.dashboard import serve as serve_dashboard
from spectre.models import Deployment, DeploymentStatus, Strategy
from spectre.orchestrator import run as run_deploy
from spectre.report import record_run, write_report
from spectre.rollback import rollback
from spectre.secrets import collect_secrets, merge_secrets
from spectre.state import list_deployments


def _print_deployment(d: object, prefix: str = "") -> None:
    if not isinstance(d, Deployment):
        return
    icon = "✓" if d.status == DeploymentStatus.healthy else "✗"
    print(f"{prefix}{icon} {d.service}/{d.environment} {d.version} [{d.status.value}]")
    print(f"{prefix}   started: {d.started_at}")
    if d.completed_at:
        print(f"{prefix}   completed: {d.completed_at}")
    for step in d.steps:
        step_icon = "✓" if step.status == DeploymentStatus.healthy else "✗"
        print(f"{prefix}   {step_icon} {step.stage}: {step.message} ({step.duration_ms}ms)")


def _write_step_summary(deployment: Deployment) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## Spectre Deploy",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Service | `{deployment.service}` |",
        f"| Environment | `{deployment.environment}` |",
        f"| Version | `{deployment.version}` |",
        f"| Status | `{deployment.status.value}` |",
        f"| Duration | `{deployment.started_at}` → `{deployment.completed_at}` |",
        "",
        "### Steps",
        "",
    ]
    for step in deployment.steps:
        icon = ":white_check_mark:" if step.status == DeploymentStatus.healthy else ":x:"
        lines.append(f"- {icon} **{step.stage}**: {step.message} ({step.duration_ms}ms)")
        if step.detail:
            lines.append(f"  - `{step.detail}`")
    lines.append("")
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spectre",
        description="Spectre — deployment orchestrator",
    )
    parser.add_argument(
        "--services", default="config/services.toml",
        help="Services config file (TOML or JSON)",
    )
    parser.add_argument(
        "--environments", default="config/environments.toml",
        help="Environments config file (TOML or JSON)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    deploy_parser = sub.add_parser("deploy", help="Deploy a service")
    deploy_parser.add_argument("service", help="Service name")
    deploy_parser.add_argument("environment", help="Target environment")
    deploy_parser.add_argument("version", help="Version tag (git sha or semver)")
    deploy_parser.add_argument("--build-type", default=None, choices=["docker", "pip"])
    choices = ["docker-compose", "kubernetes"]
    deploy_parser.add_argument("--deploy-type", default=None, choices=choices)
    strat_choices = [s.value for s in Strategy]
    deploy_parser.add_argument("--strategy", default=None, choices=strat_choices)
    deploy_parser.add_argument("--compose-file", default=None)
    deploy_parser.add_argument("--health-url", default=None)
    deploy_parser.add_argument("--build-context", default=None)
    deploy_parser.add_argument("--dockerfile", default=None)
    deploy_parser.add_argument("--namespace", default=None)
    deploy_parser.add_argument("--kube-context", default=None)
    deploy_parser.add_argument(
        "--registry", default=None, help="Container registry (e.g., ghcr.io/org)"
    )
    deploy_parser.add_argument(
        "--push", action="store_true", help="Push image to registry after build"
    )
    deploy_parser.add_argument("--force", action="store_true", help="Bypass deployment lock")
    deploy_parser.add_argument(
        "--secrets", metavar="PATH",
        help="Path to .env file with secrets (merged with config secrets)",
    )
    deploy_parser.add_argument("--ci", action="store_true", help="CI mode (GitHub Actions output)")
    deploy_parser.add_argument("--report", metavar="PATH", help="Write deployment report")
    deploy_parser.add_argument(
        "--record", action="store_true", help="Append to memory/changelog.md"
    )

    sub.add_parser("status", help="Show current deployment status")

    list_parser = sub.add_parser("list", help="List deployments")
    list_parser.add_argument("--service", default=None, help="Filter by service")
    list_parser.add_argument("--environment", default=None, help="Filter by environment")

    rollback_parser = sub.add_parser("rollback", help="Rollback a service")
    rollback_parser.add_argument("service", help="Service name")
    rollback_parser.add_argument("environment", help="Target environment")

    dash_parser = sub.add_parser("dashboard", help="Start web dashboard")
    dash_parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    dash_parser.add_argument("--host", default="127.0.0.1", help="Bind address")

    args = parser.parse_args(argv)

    if args.command == "deploy":
        svc_overrides = {
            "build_type": args.build_type,
            "deploy_type": args.deploy_type,
            "strategy": args.strategy,
            "build_context": args.build_context,
            "dockerfile": args.dockerfile,
            "registry": args.registry,
        }
        service = resolve_service(args.service, args.services, svc_overrides)
        if args.push:
            service.push_image = True

        env_overrides = {
            "compose_file": args.compose_file,
            "kube_namespace": args.namespace,
            "kube_context": args.kube_context,
        }
        env = resolve_environment(args.environment, args.environments, env_overrides)

        secrets = collect_secrets(
            service_secrets=service.secrets,
            environment_secrets=env.secrets,
            secrets_file=service.secrets_file or None,
            cli_secrets_file=args.secrets,
        )
        merged_env = merge_secrets(env.env_vars or None, secrets)

        health_url = args.health_url or f"http://localhost:{service.port}{service.health_endpoint}"

        if args.ci:
            print("::group::Spectre Deploy")

        deployment = run_deploy(
            service=service.name,
            environment=env.name,
            version=args.version,
            build_type=service.build_type,
            deploy_type=service.deploy_type,
            strategy=service.strategy,
            compose_file=env.compose_file,
            health_url=health_url,
            build_context=service.build_context,
            dockerfile=service.dockerfile,
            namespace=env.kube_namespace,
            kube_context=env.kube_context,
            env_vars=merged_env,
            registry=service.registry,
            image_name=service.image_name,
            push_image=service.push_image,
            force=args.force,
        )
        _print_deployment(deployment)
        print()

        if args.ci:
            _write_step_summary(deployment)
            for step in deployment.steps:
                if step.status == DeploymentStatus.failed:
                    print(f"::error::[{step.stage}] {step.message}")
                else:
                    print(f"::notice::[{step.stage}] {step.message}")
            print("::endgroup::")

        if args.report:
            path = write_report(deployment, args.report)
            print(f"report written: {path}")

        if args.record:
            path = record_run(deployment)
            print(f"run recorded: {path}")

        return 1 if deployment.status == DeploymentStatus.failed else 0

    elif args.command == "status":
        deployments = list_deployments()
        if not deployments:
            print("no deployments recorded")
            return 0
        latest = deployments[0]
        print(f"current deployment: {latest.service}/{latest.environment}")
        _print_deployment(latest)
        return 0

    elif args.command == "list":
        deployments = list_deployments(args.service, args.environment)
        if not deployments:
            print("no deployments found")
            return 0
        for d in deployments:
            _print_deployment(d, prefix="  ")
            print()
        return 0

    elif args.command == "rollback":
        results = rollback(args.service, args.environment)
        for r in results:
            icon = "✓" if r.status == DeploymentStatus.healthy else "✗"
            print(f"{icon} {r.stage}: {r.message}")
        failed = any(r.status == DeploymentStatus.failed for r in results)
        return 1 if failed else 0

    elif args.command == "dashboard":
        serve_dashboard(host=args.host, port=args.port)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
