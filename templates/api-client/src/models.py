from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class BaseResponse(BaseModel, Generic[DataT]):
    data: DataT | None = None
    message: str | None = None
    status: str = "ok"


class PaginatedResponse(BaseResponse, Generic[DataT]):
    data: list[DataT] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_more: bool = False


class ErrorDetail(BaseModel):
    code: str | None = None
    message: str
    details: dict[str, Any] | None = None
    timestamp: datetime | None = None


class ErrorResponse(BaseModel):
    status: str = "error"
    error: ErrorDetail
