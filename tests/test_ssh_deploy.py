from __future__ import annotations

from unittest.mock import patch

from spectre.deployer import _ssh_base_args, deploy, deploy_ssh, compose_stop_ssh
from spectre.models import DeploymentStatus, StepResult, Stage


def test_ssh_base_args_host_only() -> None:
    args = _ssh_base_args("example.com")
    assert args == ["example.com"]


def test_ssh_base_args_with_user() -> None:
    args = _ssh_base_args("example.com", user="deploy")
    assert args == ["-o", "User=deploy", "example.com"]


def test_ssh_base_args_with_key() -> None:
    args = _ssh_base_args("example.com", key="/path/to/key")
    assert args == ["-i", "/path/to/key", "example.com"]


def test_ssh_base_args_with_port() -> None:
    args = _ssh_base_args("example.com", port=2222)
    assert args == ["-p", "2222", "example.com"]


def test_ssh_base_args_all() -> None:
    args = _ssh_base_args("example.com", user="deploy", key="/key", port=2222)
    assert args == ["-o", "User=deploy", "-i", "/key", "-p", "2222", "example.com"]


def test_deploy_ssh_no_hosts() -> None:
    result = deploy_ssh("api", hosts=None)
    assert result.status.value == "failed"
    assert "no SSH hosts" in result.message


def test_deploy_ssh_empty_hosts() -> None:
    result = deploy_ssh("api", hosts=[])
    assert result.status.value == "failed"
    assert "no SSH hosts" in result.message


@patch("subprocess.run")
def test_deploy_ssh_success(mock_run) -> None:
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    mock_run.return_value.stdout = ""

    result = deploy_ssh("api", hosts=["host1.example.com"], ssh_user="deploy")

    assert result.status.value == "healthy"
    assert "1 remote host(s)" in result.message
    assert mock_run.call_count >= 3  # ssh mkdir, scp, ssh compose


@patch("subprocess.run")
def test_deploy_ssh_one_host_fails(mock_run) -> None:
    def side_effect(*args, **kwargs):
        class Result:
            returncode = 0
            stderr = ""
            stdout = ""
        return Result()

    mock_run.side_effect = side_effect
    results = []
    call = [0]

    def fail_on_second(*args, **kwargs):
        call[0] += 1
        class Result:
            pass
        r = Result()
        if call[0] == 3:  # the docker compose call for second host
            r.returncode = 1
            r.stderr = "error"
        else:
            r.returncode = 0
            r.stderr = ""
        r.stdout = ""
        return r

    mock_run.side_effect = fail_on_second

    result = deploy_ssh("api", hosts=["host1", "host2"], ssh_user="deploy")
    assert result.status.value == "failed"
    assert "failed on one or more hosts" in result.message


@patch("subprocess.run")
def test_compose_stop_ssh_success(mock_run) -> None:
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""

    result = compose_stop_ssh("api", hosts=["host1.example.com"])
    assert result.status.value == "healthy"
    assert "stopped" in result.message


@patch("subprocess.run")
def test_compose_stop_ssh_no_hosts(mock_run) -> None:
    result = compose_stop_ssh("api", hosts=[])
    assert result.status.value == "healthy"


@patch("spectre.deployer.deploy_ssh")
def test_deploy_routes_to_ssh(mock_deploy_ssh) -> None:
    mock_deploy_ssh.return_value = StepResult(
        stage=Stage.deploy, status=DeploymentStatus.healthy, message="ok",
    )
    result = deploy("api", "v1", "ssh", hosts=["h1"])
    assert result.status == DeploymentStatus.healthy
    mock_deploy_ssh.assert_called_once()


def test_deploy_unknown_type() -> None:
    result = deploy("api", "v1", "unknown")
    assert result.status.value == "failed"
    assert "unknown deploy type" in result.message
