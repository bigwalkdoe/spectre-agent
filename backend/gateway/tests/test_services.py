from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.config import settings
from gateway.main import create_app
from gateway.schemas import Provider


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    # Enable debug mode for testing to skip security middleware
    original_debug = settings.debug
    settings.debug = True

    try:
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
    finally:
        settings.debug = original_debug


@pytest.mark.anyio
async def test_providers_list(client: AsyncClient) -> None:
    """Test listing available providers."""
    response = await client.get("/api/v1/providers")
    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    assert Provider.openai.value in data["providers"]
    assert Provider.ollama.value in data["providers"]
    assert Provider.azure.value in data["providers"]


@pytest.mark.anyio
async def test_chat_completions_invalid_model(client: AsyncClient) -> None:
    """Test chat completion with invalid model."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "",  # Empty model
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.anyio
async def test_chat_completions_invalid_messages(client: AsyncClient) -> None:
    """Test chat completion with invalid messages."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [],  # Empty messages
        },
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.anyio
async def test_chat_completions_no_user_message(client: AsyncClient) -> None:
    """Test chat completion without user message."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "system", "content": "You are helpful"}],
        },
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.anyio
async def test_chat_completions_with_temperature(client: AsyncClient) -> None:
    """Test chat completion with temperature parameter."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "test"}],
            "temperature": 0.7,
        },
    )
    # Will fail with 502 since no real backend, but should accept the parameter
    assert response.status_code in [502, 400]


@pytest.mark.anyio
async def test_chat_completions_with_max_tokens(client: AsyncClient) -> None:
    """Test chat completion with max_tokens parameter."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 100,
        },
    )
    # Will fail with 502 since no real backend, but should accept the parameter
    assert response.status_code in [502, 400]


@pytest.mark.anyio
async def test_chat_completions_ollama_model(client: AsyncClient) -> None:
    """Test chat completion with Ollama model."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "llama2",
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    # Will fail with 502 since no real backend, but should route to Ollama
    assert response.status_code in [502, 400]


@pytest.mark.anyio
async def test_chat_completions_gpt_model(client: AsyncClient) -> None:
    """Test chat completion with GPT model."""
    response = await client.post(
        "/api/v1/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "test"}],
        },
    )
    # Will fail with 502 since no real backend, but should route to OpenAI
    assert response.status_code in [502, 400]
