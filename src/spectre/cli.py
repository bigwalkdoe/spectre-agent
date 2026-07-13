from __future__ import annotations

import argparse
import sys

from spectre.config import resolve_environment, resolve_service
from spectre.models import DeploymentStatus
from spectre.orchestrator import run
from spectre.report import record_run, write_report
from spectre.rollback import rollback
from spectre.state import list_deployments


def _print_deployment(d: object, prefix: str = "") -> None:
    from spectre.models import Deployment
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
    deploy_parser.add_argument("--compose-file", default=None)
    deploy_parser.add_argument("--health-url", default=None)
    deploy_parser.add_argument("--build-context", default=None)
    deploy_parser.add_argument("--dockerfile", default=None)
    deploy_parser.add_argument("--namespace", default=None)
    deploy_parser.add_argument("--kube-context", default=None)
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

    args = parser.parse_args(argv)

    if args.command == "deploy":
        svc_overrides = {
            "build_type": args.build_type,
            "deploy_type": args.deploy_type,
            "build_context": args.build_context,
            "dockerfile": args.dockerfile,
        }
        service = resolve_service(args.service, args.services, svc_overrides)

        env_overrides = {
            "compose_file": args.compose_file,
            "kube_namespace": args.namespace,
            "kube_context": args.kube_context,
        }
        env = resolve_environment(args.environment, args.environments, env_overrides)

        health_url = args.health_url or f"http://localhost:{service.port}{service.health_endpoint}"

        deployment = run(
            service=service.name,
            environment=env.name,
            version=args.version,
            build_type=service.build_type,
            deploy_type=service.deploy_type,
            compose_file=env.compose_file,
            health_url=health_url,
            build_context=service.build_context,
            dockerfile=service.dockerfile,
            namespace=env.kube_namespace,
            kube_context=env.kube_context,
            env_vars=env.env_vars or None,
        )
        _print_deployment(deployment)
        print()

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
