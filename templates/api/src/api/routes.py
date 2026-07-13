from __future__ import annotations

from fastapi import APIRouter

from .schemas import HealthResponse, MessageResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/ping", response_model=MessageResponse)
async def ping() -> MessageResponse:
    return MessageResponse(message="pong")
