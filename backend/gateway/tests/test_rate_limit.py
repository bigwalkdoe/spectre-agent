from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.config import settings
from gateway.main import create_app
from gateway.rate_limit import close_rate_limiter, get_rate_limiter, rate_limit_key_func


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


def test_rate_limit_key_func_with_api_key() -> None:
    """Test rate limit key generation with API key."""
    from unittest.mock import Mock

    request = Mock()
    request.headers.get.return_value = "test-api-key"
    request.client.host = "192.168.1.1"

    key = rate_limit_key_func(request)
    assert key == "ratelimit:api_key:test-api-key"


def test_rate_limit_key_func_without_api_key() -> None:
    """Test rate limit key generation without API key."""
    from unittest.mock import Mock

    request = Mock()
    request.headers.get.return_value = None
    request.client.host = "192.168.1.1"

    key = rate_limit_key_func(request)
    assert key == "ratelimit:ip:192.168.1.1"


def test_rate_limit_key_func_no_client() -> None:
    """Test rate limit key generation when client is None."""
    from unittest.mock import Mock

    request = Mock()
    request.headers.get.return_value = None
    request.client = None

    key = rate_limit_key_func(request)
    assert key == "ratelimit:ip:unknown"


@pytest.mark.anyio
async def test_close_rate_limiter() -> None:
    """Test closing the rate limiter."""
    # Initialize rate limiter
    limiter = await get_rate_limiter()
    assert limiter is not None

    # Close rate limiter
    await close_rate_limiter()

    # Should create new instance on next call
    new_limiter = await get_rate_limiter()
    assert new_limiter is not None

    # Clean up
    await close_rate_limiter()
