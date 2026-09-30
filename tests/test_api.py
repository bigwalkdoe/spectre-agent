"""Tests for the Spectre REST API."""

from __future__ import annotations

import httpx
import pytest

from apps.api.main import app

TEST_API_KEY = "test-api-key-not-a-real-secret"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API refuses to serve unauthenticated, so every test needs a key."""
    monkeypatch.setenv("SPECTRE_API_KEY", TEST_API_KEY)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    """Create an async test client that presents the API key."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": TEST_API_KEY}
    ) as ac:
        yield ac


@pytest.fixture
async def anon_client() -> httpx.AsyncClient:
    """Create an async test client with no API key."""
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


# ── Authentication ────────────────────────────────────────────────────────────


async def test_refuses_to_serve_without_key(anon_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed: an unset SPECTRE_API_KEY must not open the API up."""
    monkeypatch.delenv("SPECTRE_API_KEY", raising=False)
    resp = await anon_client.get("/api/agents")
    assert resp.status_code == 503


async def test_rejects_missing_key(anon_client: httpx.AsyncClient) -> None:
    resp = await anon_client.get("/api/agents")
    assert resp.status_code == 401


async def test_rejects_wrong_key(anon_client: httpx.AsyncClient) -> None:
    resp = await anon_client.get("/api/agents", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/health"),
        ("GET", "/api/version"),
        ("GET", "/api/system/status"),
        ("GET", "/"),
        ("POST", "/api/workflows/morning-startup"),
        ("PUT", "/api/config/some_key?value=v"),
    ],
)
async def test_every_endpoint_requires_auth(anon_client: httpx.AsyncClient, method: str, path: str) -> None:
    """No endpoint may be reachable without the API key."""
    resp = await anon_client.request(method, path)
    assert resp.status_code == 401, f"{method} {path} was reachable without auth"


# ── Workflow load confinement ─────────────────────────────────────────────────


async def test_load_workflows_rejects_path_outside_root(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/workflows/load", params={"directory": "/etc"})
    assert resp.status_code == 400


async def test_load_workflows_allows_configured_root(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    root = tmp_path / "workflows"  # type: ignore[operator]
    root.mkdir()
    (root / "custom.yaml").write_text(
        "name: custom-wf\ndescription: test\nsteps:\n  - agent: linux\n    action: system-health-check\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SPECTRE_WORKFLOW_ROOTS", str(root))

    resp = await client.post("/api/workflows/load", params={"directory": str(root)})
    assert resp.status_code == 200
    assert resp.json()["loaded"] == 1


# ── Dashboard regressions ─────────────────────────────────────────────────────


async def test_dashboard_has_no_python_lint_directives(client: httpx.AsyncClient) -> None:
    """A `# noqa` inside the served HTML is invalid JavaScript and killed the page."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "noqa" not in resp.text
    assert "apiFetch('/api/system/status')" in resp.text
