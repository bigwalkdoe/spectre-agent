from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.auth import verify_api_key
from gateway.config import settings
from gateway.logging_config import configure_logging, get_logger
from gateway.rate_limit import close_rate_limiter, rate_limit_middleware
from gateway.security import add_security_middleware

configure_logging(settings.log_level)
logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add security middleware
    add_security_middleware(app)

    # Add API key authentication middleware
    app.middleware("http")(verify_api_key)

    # Add rate limiting middleware
    app.middleware("http")(rate_limit_middleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        logger.debug("Health check requested")
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, bool]:
        logger.debug("Readiness check requested")
        return {"ready": True}

    from gateway.routes import router
    app.include_router(router)

    logger.info("Application created", app_name=settings.app_name)
    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Application startup")
    yield
    logger.info("Application shutdown")
    await close_rate_limiter()
