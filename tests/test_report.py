from __future__ import annotations

from pathlib import Path

from spectre.models import Deployment, DeploymentStatus, Stage, StepResult
from spectre.report import (
    record_run,
    render_json,
    render_markdown,
    write_report,
)


def _deployment() -> Deployment:
    return Deployment(
        service="api",
        environment="staging",
        version="v1.2.3",
        status=DeploymentStatus.healthy,
        steps=[
            StepResult(
                stage=Stage.build,
                status=DeploymentStatus.healthy,
                message="built image",
                duration_ms=1500,
            ),
            StepResult(
                stage=Stage.deploy,
                status=DeploymentStatus.healthy,
                message="deployed via compose",
                duration_ms=3000,
            ),
        ],
        started_at="2024-06-01T00:00:00Z",
        completed_at="2024-06-01T00:01:00Z",
    )


def _failed_deployment() -> Deployment:
    dep = _deployment()
    dep.status = DeploymentStatus.failed
    dep.steps = [
        StepResult(
            stage=Stage.build,
            status=DeploymentStatus.failed,
            message="docker build failed",
            duration_ms=500,
        ),
    ]
    return dep


def test_render_json_contains_fields() -> None:
    out = render_json(_deployment())
    assert "api" in out
    assert "staging" in out
    assert "v1.2.3" in out
    assert "healthy" in out


def test_render_markdown_contains_service() -> None:
    out = render_markdown(_deployment())
    assert "api" in out
    assert "healthy" in out


def test_render_markdown_shows_failed() -> None:
    out = render_markdown(_failed_deployment())
    assert "failed" in out
    assert "docker build failed" in out


def test_write_report_creates_file(tmp_path: Path) -> None:
    path = str(tmp_path / "deploy.json")
    result = write_report(_deployment(), path, fmt="json")
    assert result.is_file()
    content = result.read_text()
    assert "v1.2.3" in content


def test_record_run_appends(tmp_path: Path) -> None:
    changelog = tmp_path / "changelog.md"
    changelog.write_text("# Changelog\n")
    record_run(_deployment(), str(changelog))
    text = changelog.read_text()
    assert "Deploy" in text
    assert "api" in text
    assert "healthy" in text


def test_record_run_failed_includes_failed_steps(tmp_path: Path) -> None:
    changelog = tmp_path / "changelog.md"
    changelog.write_text("# Changelog\n")
    record_run(_failed_deployment(), str(changelog))
    text = changelog.read_text()
    assert "Failed Steps" in text
    assert "docker build failed" in text
