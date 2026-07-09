from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from gateway.logging_config import get_logger
from gateway.schemas import ChatRequest, ChatResponse, Provider
from gateway.services import Router

router = APIRouter()
logger = get_logger(__name__)
_router = Router()


@router.post("/api/v1/completions", response_model=ChatResponse)
async def chat_completions(request: Request, payload: ChatRequest) -> ChatResponse:
    logger.info(
        "Chat completion request",
        model=payload.model,
        message_count=len(payload.messages),
        client=request.client.host if request.client else "unknown",
    )

    messages = [m.model_dump() for m in payload.messages]
    kwargs = {}
    if payload.temperature is not None:
        kwargs["temperature"] = payload.temperature
    if payload.max_tokens is not None:
        kwargs["max_tokens"] = payload.max_tokens

    try:
        result = await _router.route(payload.model, messages, **kwargs)
        logger.info("Chat completion successful", model=payload.model)
    except ValueError as e:
        logger.error("Invalid request", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        logger.error("Upstream provider error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Upstream provider error"
        ) from e

    usage = None
    if result.get("usage"):
        usage = {
            "prompt_tokens": result["usage"].get("prompt_tokens", 0),
            "completion_tokens": result["usage"].get("completion_tokens", 0),
            "total_tokens": result["usage"].get("total_tokens", 0),
        }

    if result.get("choices"):
        choice = result["choices"][0]["message"]["content"]
    else:
        choice = result.get("message", {}).get("content", "")

    return ChatResponse(
        model=result.get("model", payload.model),
        choice=choice,
        usage=usage,
    )


@router.get("/api/v1/providers")
async def list_providers() -> dict[str, list[str]]:
    logger.info("Providers list requested")
    return {"providers": [p.value for p in Provider]}
