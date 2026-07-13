from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from spectre.models import Deployment, DeploymentStatus


def render_json(deployment: Deployment) -> str:
    return json.dumps(deployment.to_dict(), indent=2)


def render_markdown(deployment: Deployment) -> str:
    lines = [
        f"# Deployment: {deployment.service}",
        "",
        f"- **service**: {deployment.service}",
        f"- **environment**: {deployment.environment}",
        f"- **version**: {deployment.version}",
        f"- **status**: {deployment.status.value}",
        f"- **started**: {deployment.started_at}",
        f"- **completed**: {deployment.completed_at}",
        "",
        "## Steps",
        "",
    ]
    for step in deployment.steps:
        icon = "✓" if step.status == DeploymentStatus.healthy else "✗"
        lines.append(f"- {icon} **{step.stage}**: {step.message}")
        if step.detail:
            lines.append(f"  - detail: {step.detail}")
        lines.append(f"  - duration: {step.duration_ms}ms")
        lines.append("")
    return "\n".join(lines)


def write_report(deployment: Deployment, path: str, fmt: str = "json") -> Path:
    target = Path(path)
    rendered = render_json(deployment) if fmt == "json" else render_markdown(deployment)
    target.write_text(rendered + "\n", encoding="utf-8")
    return target


def record_run(deployment: Deployment, path: str = "memory/changelog.md") -> Path:
    target = Path(path)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    block = [
        f"\n## Deploy {stamp}",
        "",
        f"- **service**: {deployment.service}",
        f"- **environment**: {deployment.environment}",
        f"- **version**: {deployment.version}",
        f"- **status**: {deployment.status.value}",
        "",
    ]
    failed = [s for s in deployment.steps if s.status == DeploymentStatus.failed]
    if failed:
        block.append("### Failed Steps")
        block.append("")
        for step in failed:
            block.append(f"- {step.stage}: {step.message}")
        block.append("")

    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    target.write_text(existing + "\n".join(block), encoding="utf-8")
    return target
