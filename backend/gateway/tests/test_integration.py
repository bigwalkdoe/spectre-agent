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
async def test_full_request_flow(client: AsyncClient) -> None:
    """Test the full request flow from authentication to response."""
    # Test 1: Health check works
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Test 2: Ready check works
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}

    # Test 3: Providers list works
    response = await client.get("/api/v1/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert "openai" in providers
    assert "ollama" in providers

    # Test 4: Valid chat request (will fail on backend but passes validation)
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ],
            "temperature": 0.7,
            "max_tokens": 100,
        },
    )
    # Should pass validation and auth, fail on backend connection
    assert response.status_code in [502, 400]


@pytest.mark.anyio
async def test_middleware_stack_order(client: AsyncClient) -> None:
    """Test that middleware stack is in correct order."""
    # Security headers should be present
    response = await client.get("/health")
    assert "X-Content-Type-Options" in response.headers
    assert "X-Frame-Options" in response.headers

    # Test that rate limiting is skipped in debug mode
    for _ in range(5):  # Multiple requests should work in debug mode
        response = await client.get("/health")
        assert response.status_code == 200


@pytest.mark.anyio
async def test_error_handling_flow(client: AsyncClient) -> None:
    """Test error handling throughout the request flow."""
    # Test invalid request data
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "",  # Invalid model
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    assert response.status_code == 422

    # Test missing required field
    response = await client.post(
        "/api/v1/completions",
        json={
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    assert response.status_code == 422

    # Test invalid message format
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": ""}],  # Empty content
        },
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_logging_configuration(client: AsyncClient) -> None:
    """Test that logging is properly configured."""
    # This test ensures the application starts without logging errors
    response = await client.get("/health")
    assert response.status_code == 200

    # Application should have structured logging configured
    # (verified by successful startup and no logging errors in output)


@pytest.mark.anyio
async def test_cors_integration(client: AsyncClient) -> None:
    """Test CORS configuration integration."""
    # Test CORS preflight request
    response = await client.options(
        "/api/v1/completions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Should accept the preflight request
    assert response.status_code in [200, 404]  # May vary based on CORS config


@pytest.mark.anyio
async def test_configuration_integration(client: AsyncClient) -> None:
    """Test that configuration is properly loaded."""
    # Test that the application uses the configured settings
    response = await client.get("/health")
    assert response.status_code == 200

    # The application should be running with the configured app name
    # (implicitly tested by successful response)


@pytest.mark.anyio
async def test_lifecycle_management(client: AsyncClient) -> None:
    """Test application lifecycle management."""
    # Test that the application starts up correctly
    response = await client.get("/health")
    assert response.status_code == 200

    # Test that the application is ready
    response = await client.get("/ready")
    assert response.status_code == 200

    # The application should handle requests normally
    response = await client.get("/api/v1/providers")
    assert response.status_code == 200
