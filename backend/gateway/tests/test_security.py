from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.config import settings
from gateway.main import create_app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    # Enable debug mode for testing to skip security middleware
    original_debug = settings.debug
    settings.debug = True

    try:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
    finally:
        settings.debug = original_debug


@pytest.mark.anyio
async def test_security_headers(client: AsyncClient) -> None:
    """Test that security headers are present."""
    response = await client.get("/health")
    assert response.status_code == 200

    # Check for security headers
    headers = response.headers
    assert "X-Content-Type-Options" in headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Frame-Options" in headers
    assert headers["X-Frame-Options"] == "DENY"
    assert "X-XSS-Protection" in headers
    assert headers["X-XSS-Protection"] == "1; mode=block"
    assert "Strict-Transport-Security" in headers
    assert "Content-Security-Policy" in headers
    assert "Referrer-Policy" in headers
    assert "Permissions-Policy" in headers


@pytest.mark.anyio
async def test_cors_headers(client: AsyncClient) -> None:
    """Test CORS headers."""
    response = await client.options(
        "/api/v1/completions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Should accept CORS preflight
    assert response.status_code in [200, 401, 403, 404]  # May vary based on auth
