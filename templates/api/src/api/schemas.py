from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MessageResponse(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    code: str | None = None
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail
