from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .routes import router
from .schemas import ErrorDetail, ErrorResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
    )

    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        detail = ErrorDetail(message=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(detail=detail).model_dump(),
        )

    return app


app = create_app()
