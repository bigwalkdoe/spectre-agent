"""Tests for the Spectre REST API."""

from __future__ import annotations

import httpx
import pytest

from apps.api.main import app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    """Create an async test client."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health_check(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_list_agents(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert len(data["agents"]) == 8


async def test_list_workflows(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert "workflows" in data
    assert "morning-startup" in data["workflows"]


async def test_get_agent_status(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/agents/linux")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_percent" in data


async def test_get_agent_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/agents/nonexistent")
    assert resp.status_code == 404


async def test_system_status(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "linux" in data
    assert "devops" in data


async def test_run_workflow(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/workflows/morning-startup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow"] == "morning-startup"
    assert data["status"] in ("success", "failed")


async def test_run_workflow_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/workflows/nonexistent")
    assert resp.status_code == 400


async def test_dashboard_html(client: httpx.AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Spectre Dashboard" in resp.text


async def test_list_reports(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/reports")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_decisions(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/decisions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_config_roundtrip(client: httpx.AsyncClient) -> None:
    resp = await client.put("/api/config/test_key?value=test_value")
    assert resp.status_code == 200

    resp = await client.get("/api/config/test_key")
    assert resp.status_code == 200
    assert resp.json()["value"] == "test_value"


async def test_config_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/config/nonexistent_key_xyz")
    assert resp.status_code == 404


async def test_workflow_history(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/workflows/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
