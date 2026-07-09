from __future__ import annotations

from typing import Any

import httpx

from gateway.config import settings
from gateway.schemas import Provider


class ProviderClient:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        c = await self._get_client()
        body: dict[str, Any] = {"model": model, "messages": messages, **kwargs}

        if self.provider == Provider.openai:
            resp = await c.post(
                "https://api.openai.com/v1/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        elif self.provider == Provider.ollama:
            resp = await c.post(
                f"{settings.ollama_base_url}/api/chat",
                json=body,
            )
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()


class Router:
    def __init__(self) -> None:
        self._providers: dict[Provider, ProviderClient] = {}

    async def _get_client(self, provider: Provider) -> ProviderClient:
        if provider not in self._providers:
            self._providers[provider] = ProviderClient(provider)
        return self._providers[provider]

    def _select_provider(self, model: str) -> Provider:
        if model.startswith("gpt") or model.startswith("o"):
            return Provider.openai
        return Provider.ollama

    async def route(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        provider = self._select_provider(model)
        client = await self._get_client(provider)
        return await client.chat(model, messages, **kwargs)

    async def aclose(self) -> None:
        for p in self._providers.values():
            await p.aclose()
        self._providers.clear()
