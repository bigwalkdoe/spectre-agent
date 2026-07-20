from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from src.api.main import create_app


async def test_health() -> None:
    app = create_app()
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_ping() -> None:
    app = create_app()
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/ping")
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "pong"
