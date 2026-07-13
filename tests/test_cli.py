from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from spectre.cli import main


def test_deploy_help() -> None:
    try:
        with patch("sys.stdout"):
            main(["deploy", "api", "staging", "v1", "--help"])
    except SystemExit as e:
        assert e.code == 0


def test_status_no_deployments(tmp_path: Path) -> None:
    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"):
        rc = main(["status"])
    assert rc == 0


def test_list_no_deployments(tmp_path: Path) -> None:
    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"):
        rc = main(["list"])
    assert rc == 0


def test_rollback_missing(tmp_path: Path) -> None:
    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"):
        rc = main(["rollback", "api", "staging"])
    assert rc == 1


def test_ci_flag_accepted(tmp_path: Path) -> None:
    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"), \
         patch("spectre.cli.run_deploy") as mock_run:
        from spectre.models import Deployment, DeploymentStatus
        mock_run.return_value = Deployment(
            service="api", environment="staging", version="v1",
            status=DeploymentStatus.healthy,
        )
        rc = main(["deploy", "api", "staging", "v1", "--ci"])
    assert rc == 0


def test_ci_flag_writes_summary(tmp_path: Path, monkeypatch: object) -> None:
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))  # type: ignore[arg-type]

    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"), \
         patch("spectre.cli.run_deploy") as mock_run:
        from spectre.models import Deployment, DeploymentStatus, Stage, StepResult
        mock_run.return_value = Deployment(
            service="api", environment="staging", version="v1",
            status=DeploymentStatus.healthy,
            steps=[
                StepResult(
                    stage=Stage.build, status=DeploymentStatus.healthy,
                    message="built", duration_ms=500,
                ),
                StepResult(
                    stage=Stage.deploy, status=DeploymentStatus.healthy,
                    message="deployed", duration_ms=1000,
                ),
            ],
        )
        rc = main(["deploy", "api", "staging", "v1", "--ci"])
    assert rc == 0
    assert summary_file.is_file()
    content = summary_file.read_text()
    assert "Spectre Deploy" in content
    assert "api" in content
    assert "built" in content


def test_force_flag_accepted(tmp_path: Path) -> None:
    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"), \
         patch("spectre.cli.run_deploy") as mock_run:
        from spectre.models import Deployment, DeploymentStatus
        mock_run.return_value = Deployment(
            service="api", environment="staging", version="v1",
            status=DeploymentStatus.healthy,
        )
        rc = main(["deploy", "api", "staging", "v1", "--force"])
    assert rc == 0


def test_deploy_failure_exit_code(tmp_path: Path) -> None:
    with patch("spectre.state._STATE_DIR", tmp_path / ".spectre"), \
         patch("spectre.cli.run_deploy") as mock_run:
        from spectre.models import Deployment, DeploymentStatus
        mock_run.return_value = Deployment(
            service="api", environment="staging", version="v1",
            status=DeploymentStatus.failed,
        )
        rc = main(["deploy", "api", "staging", "v1", "--ci"])
    assert rc == 1
