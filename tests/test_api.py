"""Tests for the Spectre REST API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_health_check() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_agents() -> None:
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert len(data["agents"]) == 8


def test_list_workflows() -> None:
    resp = client.get("/api/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert "workflows" in data
    assert "morning-startup" in data["workflows"]


def test_get_agent_status() -> None:
    resp = client.get("/api/agents/linux")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_percent" in data


def test_get_agent_not_found() -> None:
    resp = client.get("/api/agents/nonexistent")
    assert resp.status_code == 404


def test_system_status() -> None:
    resp = client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "linux" in data
    assert "devops" in data


def test_run_workflow() -> None:
    resp = client.post("/api/workflows/morning-startup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow"] == "morning-startup"
    assert data["status"] in ("success", "failed")


def test_run_workflow_not_found() -> None:
    resp = client.post("/api/workflows/nonexistent")
    assert resp.status_code == 400


def test_dashboard_html() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Spectre Dashboard" in resp.text


def test_list_reports() -> None:
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_decisions() -> None:
    resp = client.get("/api/decisions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_config_roundtrip() -> None:
    resp = client.put("/api/config/test_key?value=test_value")
    assert resp.status_code == 200

    resp = client.get("/api/config/test_key")
    assert resp.status_code == 200
    assert resp.json()["value"] == "test_value"


def test_config_not_found() -> None:
    resp = client.get("/api/config/nonexistent_key_xyz")
    assert resp.status_code == 404


def test_workflow_history() -> None:
    resp = client.get("/api/workflows/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
