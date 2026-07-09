from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response, status
from redis import asyncio as aioredis
from redis.asyncio import Redis

from gateway.config import settings
from gateway.logging_config import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Rate limiter using Redis backend with sliding window algorithm."""

    def __init__(self) -> None:
        self._redis: Redis | None = None

    async def initialize(self) -> None:
        """Initialize the rate limiter with Redis backend."""
        try:
            self._redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info(
                "Rate limiter initialized",
                requests=settings.rate_limit_requests,
                window_seconds=settings.rate_limit_window_seconds,
            )
        except Exception as e:
            logger.error("Failed to initialize rate limiter", error=str(e))
            raise

    async def check_rate_limit(self, key: str) -> bool:
        """Check if the request should be rate limited using sliding window."""
        if self._redis is None:
            logger.warning("Rate limiter not initialized, skipping check")
            return True

        try:
            current_time = await self._redis.time()
            timestamp = current_time[0]

            # Remove old entries outside the time window
            window_start = timestamp - settings.rate_limit_window_seconds
            await self._redis.zremrangebyscore(key, 0, window_start)

            # Count current requests
            current_count = await self._redis.zcard(key)

            if current_count >= settings.rate_limit_requests:
                logger.warning("Rate limit exceeded", key=key, count=current_count)
                return False

            # Add current request
            await self._redis.zadd(key, {str(timestamp): timestamp})
            await self._redis.expire(key, settings.rate_limit_window_seconds)

            return True

        except Exception as e:
            logger.error("Rate limit check error", error=str(e))
            # On error, allow the request to proceed (fail open)
            return True

    async def close(self) -> None:
        """Close the rate limiter connection."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None


# Global rate limiter instance
_rate_limiter: RateLimiter | None = None


async def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
        await _rate_limiter.initialize()
    return _rate_limiter


async def close_rate_limiter() -> None:
    """Close the global rate limiter."""
    global _rate_limiter
    if _rate_limiter:
        await _rate_limiter.close()
        _rate_limiter = None


def rate_limit_key_func(request: Request) -> str:
    """Generate a rate limit key from the request."""
    # Use API key if available, otherwise use IP address
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"ratelimit:api_key:{api_key}"

    # Fallback to client IP
    client_host = request.client.host if request.client else "unknown"
    return f"ratelimit:ip:{client_host}"


async def rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Rate limiting middleware."""
    # Skip rate limiting for health checks
    if request.url.path in ["/health", "/ready", "/docs", "/openapi.json"]:
        return await call_next(request)

    # Skip rate limiting in debug mode
    if settings.debug:
        return await call_next(request)

    try:
        limiter = await get_rate_limiter()
        key = rate_limit_key_func(request)

        if not await limiter.check_rate_limit(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )

        return await call_next(request)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Rate limiting error", error=str(e))
        # On error, allow the request to proceed (fail open)
        return await call_next(request)
