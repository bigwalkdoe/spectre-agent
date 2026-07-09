from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Role(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"


class Message(BaseModel):
    role: Role
    content: str = Field(..., min_length=1, max_length=100000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content is not empty or just whitespace."""
        if not v.strip():
            raise ValueError("Content cannot be empty or whitespace")
        return v


class ChatRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=100)
    messages: list[Message] = Field(..., min_length=1, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=16384)
    stream: bool = False

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[Message]) -> list[Message]:
        """Validate messages contain at least one user message."""
        if not any(msg.role == Role.user for msg in v):
            raise ValueError("Messages must contain at least one user message")
        return v


class ChatResponse(BaseModel):
    model: str
    choice: str
    usage: dict[str, int] | None = None


class Provider(StrEnum):
    openai = "openai"
    azure = "azure"
    ollama = "ollama"


class ModelCapability(BaseModel):
    provider: Provider
    model_id: str
    context_window: int
    supports_streaming: bool = True
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


class ErrorResponse(BaseModel):
    detail: str
