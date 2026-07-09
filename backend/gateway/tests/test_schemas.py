from __future__ import annotations

import pytest

from gateway.schemas import ChatRequest, Message, Role


def test_message_validation() -> None:
    """Test message validation."""
    # Valid message
    msg = Message(role=Role.user, content="Hello")
    assert msg.role == Role.user
    assert msg.content == "Hello"

    # Empty content should fail
    # Pydantic raises ValidationError which inherits from ValueError
    with pytest.raises(ValueError):
        Message(role=Role.user, content="")

    # Whitespace only should fail
    with pytest.raises(ValueError):
        Message(role=Role.user, content="   ")


def test_chat_request_validation() -> None:
    """Test chat request validation."""
    # Valid request
    request = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[
            Message(role=Role.system, content="You are helpful"),
            Message(role=Role.user, content="Hello"),
        ],
    )
    assert request.model == "gpt-3.5-turbo"
    assert len(request.messages) == 2

    # Request without user message should fail
    with pytest.raises(ValueError, match="must contain at least one user message"):
        ChatRequest(
            model="gpt-3.5-turbo",
            messages=[
                Message(role=Role.system, content="You are helpful"),
            ],
        )

    # Empty messages list should fail
    with pytest.raises(ValueError):
        ChatRequest(model="gpt-3.5-turbo", messages=[])

    # Temperature validation
    with pytest.raises(ValueError):
        ChatRequest(
            model="gpt-3.5-turbo",
            messages=[Message(role=Role.user, content="test")],
            temperature=3.0,  # Too high
        )

    with pytest.raises(ValueError):
        ChatRequest(
            model="gpt-3.5-turbo",
            messages=[Message(role=Role.user, content="test")],
            temperature=-1.0,  # Too low
        )

    # Max tokens validation
    with pytest.raises(ValueError):
        ChatRequest(
            model="gpt-3.5-turbo",
            messages=[Message(role=Role.user, content="test")],
            max_tokens=0,  # Too low
        )

    with pytest.raises(ValueError):
        ChatRequest(
            model="gpt-3.5-turbo",
            messages=[Message(role=Role.user, content="test")],
            max_tokens=20000,  # Too high
        )


def test_message_length_validation() -> None:
    """Test message length constraints."""
    # Model name length
    with pytest.raises(ValueError):
        ChatRequest(
            model="a" * 101,  # Too long
            messages=[Message(role=Role.user, content="test")],
        )

    # Messages count
    with pytest.raises(ValueError):
        ChatRequest(
            model="gpt-3.5-turbo",
            messages=[Message(role=Role.user, content="test")] * 101,  # Too many
        )

    # Content length
    with pytest.raises(ValueError):
        Message(role=Role.user, content="a" * 100001)  # Too long


def test_role_enum() -> None:
    """Test role enum values."""
    assert Role.system == "system"
    assert Role.user == "user"
    assert Role.assistant == "assistant"
