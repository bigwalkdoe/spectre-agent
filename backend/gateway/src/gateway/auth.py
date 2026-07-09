from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from gateway.config import settings
from gateway.logging_config import get_logger

logger = get_logger(__name__)


def parse_api_keys(api_keys_str: str) -> list[str]:
    """Parse API keys from comma-separated string."""
    if not api_keys_str:
        return []
    return [key.strip() for key in api_keys_str.split(",") if key.strip()]


async def verify_api_key(
    request: Request,
    call_next: Callable[[Request], Awaitable[Request]],
) -> Request:
    """Middleware to verify API key authentication."""
    # Skip auth for health checks and public endpoints
    if request.url.path in ["/health", "/ready", "/docs", "/openapi.json"]:
        return await call_next(request)

    # Parse API keys from comma-separated string
    api_keys_list = parse_api_keys(settings.api_keys)

    # If no API keys are configured, skip authentication (development mode)
    if not api_keys_list:
        logger.warning("No API keys configured, skipping authentication")
        return await call_next(request)

    api_key = request.headers.get("X-API-Key")
    if api_key is None:
        logger.warning("Missing API key", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )

    # Check if api_key is in the allowed list
    if api_key not in api_keys_list:
        logger.warning("Invalid API key", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    logger.debug("API key authenticated", path=request.url.path)
    return await call_next(request)
