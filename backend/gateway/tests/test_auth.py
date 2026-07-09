from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.auth import parse_api_keys
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


def test_parse_api_keys_empty() -> None:
    """Test parsing empty API keys string."""
    assert parse_api_keys("") == []
    assert parse_api_keys(None) == []  # type: ignore[arg-type]


def test_parse_api_keys_single() -> None:
    """Test parsing single API key."""
    result = parse_api_keys("test-key")
    assert result == ["test-key"]


def test_parse_api_keys_multiple() -> None:
    """Test parsing multiple API keys."""
    result = parse_api_keys("key1,key2,key3")
    assert result == ["key1", "key2", "key3"]


def test_parse_api_keys_with_spaces() -> None:
    """Test parsing API keys with spaces."""
    result = parse_api_keys("key1, key2 , key3")
    assert result == ["key1", "key2", "key3"]


@pytest.mark.anyio
async def test_api_key_missing(client: AsyncClient) -> None:
    """Test request without API key when auth is enabled."""
    # Temporarily set API keys
    original_api_keys = settings.api_keys
    settings.api_keys = "test-key"

    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException):  # HTTPException from middleware
            await client.post(
                "/api/v1/completions",
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "test"}],
                },
            )
    finally:
        settings.api_keys = original_api_keys


@pytest.mark.anyio
async def test_api_key_invalid(client: AsyncClient) -> None:
    """Test request with invalid API key."""
    # Temporarily set API keys
    original_api_keys = settings.api_keys
    settings.api_keys = "valid-key"

    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException):  # HTTPException from middleware
            await client.post(
                "/api/v1/completions",
                headers={"X-API-Key": "invalid-key"},
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "test"}],
                },
            )
    finally:
        settings.api_keys = original_api_keys


@pytest.mark.anyio
async def test_api_key_valid(client: AsyncClient) -> None:
    """Test request with valid API key."""
    # Temporarily set API keys
    original_api_keys = settings.api_keys
    settings.api_keys = "valid-key"

    try:
        response = await client.post(
            "/api/v1/completions",
            headers={"X-API-Key": "valid-key"},
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "test"}],
            },
        )
        # Will fail with 502 since no real backend, but should pass auth
        assert response.status_code in [502, 400]
    finally:
        settings.api_keys = original_api_keys


@pytest.mark.anyio
async def test_no_auth_when_disabled(client: AsyncClient) -> None:
    """Test that auth is skipped when no API keys are configured."""
    # Ensure no API keys are set
    original_api_keys = settings.api_keys
    settings.api_keys = ""

    try:
        response = await client.post(
            "/api/v1/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "test"}],
            },
        )
        # Should pass auth and fail with 502 or 400
        assert response.status_code in [502, 400]
    finally:
        settings.api_keys = original_api_keys


@pytest.mark.anyio
async def test_health_skip_auth(client: AsyncClient) -> None:
    """Test that health endpoints skip auth."""
    original_api_keys = settings.api_keys
    settings.api_keys = "test-key"

    try:
        response = await client.get("/health")
        assert response.status_code == 200

        response = await client.get("/ready")
        assert response.status_code == 200
    finally:
        settings.api_keys = original_api_keys



