from __future__ import annotations

from unittest.mock import patch

from spectre.checker import health_check, health_check_multi, pre_check
from spectre.models import DeploymentStatus, Stage


def test_pre_check_no_git_context() -> None:
    result = pre_check("api", context="/tmp")
    assert result.stage == Stage.pre_check
    assert result.status in (DeploymentStatus.healthy, DeploymentStatus.failed)
    assert result.duration_ms >= 0


def test_health_check_refused_fast() -> None:
    result = health_check("http://localhost:1/health", timeout=3, interval=1)
    assert result.stage == Stage.health_check
    assert result.status == DeploymentStatus.failed
    assert "unhealthy" in result.message
    assert result.duration_ms >= 0


def test_health_check_expected_code_202() -> None:
    with patch("spectre.checker.urlopen") as mock_open:
        class MockResp:
            status = 202
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        mock_open.return_value = MockResp()
        result = health_check("http://localhost:8000/health", timeout=5, expected_codes={200, 202})
    assert result.status == DeploymentStatus.healthy
    assert "202" in result.message


def test_health_check_unexpected_code() -> None:
    with patch("spectre.checker.urlopen") as mock_open:
        class MockResp:
            status = 503
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        mock_open.return_value = MockResp()
        result = health_check("http://localhost:8000/health", timeout=3, interval=1)
    assert result.status == DeploymentStatus.failed


def test_health_check_multi_all_pass() -> None:
    with patch("spectre.checker._single_health") as mock_single:
        mock_single.return_value = (True, "healthy: HTTP 200")
        results = health_check_multi(
            ["http://localhost:8000/health", "http://localhost:8001/health"],
            timeout=5,
        )
    assert len(results) == 2
    assert all(r.status == DeploymentStatus.healthy for r in results)


def test_health_check_multi_one_fails() -> None:
    with patch("spectre.checker._single_health") as mock_single:
        mock_single.side_effect = [
            (True, "healthy: HTTP 200"),
            (False, "connection refused"),
        ]
        results = health_check_multi(
            ["http://localhost:8000/health", "http://localhost:8001/health"],
            timeout=5,
        )
    assert len(results) == 2
    assert results[0].status == DeploymentStatus.healthy
    assert results[1].status == DeploymentStatus.failed


def test_health_check_backoff_retries() -> None:
    call_count: list[int] = [0]

    def mock_urlopen(*args, **kwargs):
        call_count[0] += 1
        raise OSError("connection refused")

    with patch("spectre.checker.time.sleep"), \
         patch("spectre.checker.urlopen", side_effect=mock_urlopen):
        result = health_check("http://localhost:1/health", timeout=5, interval=1)
    assert result.status == DeploymentStatus.failed
    assert call_count[0] >= 2

