from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.config import settings
from gateway.logging_config import get_logger

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = (
            "strict-origin-when-cross-origin"
        )
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response


def add_security_middleware(app: object) -> None:
    """Add security middleware to the FastAPI app."""
    # Add trusted host middleware (only if not in test mode)
    if not settings.debug:
        app.add_middleware(  # type: ignore[attr-defined]
            TrustedHostMiddleware,
            allowed_hosts=settings.allowed_hosts,
        )

    # Add security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)  # type: ignore[attr-defined]

    logger.info("Security middleware added", allowed_hosts=settings.allowed_hosts)
