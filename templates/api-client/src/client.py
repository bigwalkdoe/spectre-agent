from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Generic, TypeVar

import httpx
from httpx import URL, Auth, BasicAuth, Headers, QueryParams
from pydantic import BaseModel

from .models import BaseResponse, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

RequestT = TypeVar("RequestT", bound=BaseModel | None)
ResponseT = TypeVar("ResponseT", bound=BaseModel)


class APIError(Exception):
    def __init__(self, status_code: int, detail: ErrorDetail | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail.message if detail else f"HTTP {status_code}")


class APIClient(Generic[RequestT, ResponseT]):
    def __init__(
        self,
        base_url: str | URL,
        api_key: str | None = None,
        api_key_header: str = "X-API-Key",
        timeout: float = 30.0,
        auth: Auth | None = None,
        default_headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = URL(str(base_url))
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.timeout = timeout
        self.auth = auth
        self.default_headers = default_headers or {}

        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            auth=self.auth,
            timeout=httpx.Timeout(timeout),
        )

    async def __aenter__(self) -> APIClient[RequestT, ResponseT]:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {**self.default_headers}
        if self.api_key:
            headers[self.api_key_header] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    async def _handle_response(
        self,
        response: httpx.Response,
        response_model: type[ResponseT],
    ) -> ResponseT:
        if response.is_success:
            data = response.json()
            if issubclass(response_model, BaseModel):
                return response_model.model_validate(data)
            return data  # type: ignore[return-value]

        try:
            body = response.json()
            if "error" in body:
                detail = ErrorDetail.model_validate(body["error"])
            else:
                detail = ErrorDetail(message=body.get("message", str(response.text)))
        except Exception:
            detail = ErrorDetail(message=response.text or f"HTTP {response.status_code}")

        raise APIError(status_code=response.status_code, detail=detail)

    async def _request(
        self,
        method: str,
        path: str,
        response_model: type[ResponseT],
        params: QueryParams | dict[str, Any] | None = None,
        json_body: BaseModel | dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ResponseT:
        url = str(URL(path=path))
        request_headers = self._build_headers(headers)
        content: dict[str, Any] | None = (
            json_body.model_dump(mode="json")
            if isinstance(json_body, BaseModel)
            else json_body
        )

        response = await self._client.request(
            method=method,
            url=url,
            params=params,
            json=content,
            headers=request_headers,
        )
        return await self._handle_response(response, response_model)

    async def get(
        self,
        path: str,
        response_model: type[ResponseT],
        params: QueryParams | dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ResponseT:
        return await self._request("GET", path, response_model, params=params, headers=headers)

    async def post(
        self,
        path: str,
        response_model: type[ResponseT],
        json_body: BaseModel | dict[str, Any] | None = None,
        params: QueryParams | dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ResponseT:
        return await self._request(
            "POST", path, response_model, params=params, json_body=json_body, headers=headers
        )

    async def patch(
        self,
        path: str,
        response_model: type[ResponseT],
        json_body: BaseModel | dict[str, Any] | None = None,
        params: QueryParams | dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ResponseT:
        return await self._request(
            "PATCH", path, response_model, params=params, json_body=json_body, headers=headers
        )

    async def delete(
        self,
        path: str,
        response_model: type[ResponseT],
        params: QueryParams | dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ResponseT:
        return await self._request("DELETE", path, response_model, params=params, headers=headers)
