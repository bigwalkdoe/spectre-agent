#!/usr/bin/env python3
"""
Free LLM provider abstraction for the ML fix engine.

Uses locally hosted, free/open-weight models via Ollama by default. An
OpenAI-compatible provider is included so any free endpoint (local
llama.cpp server, or a free cloud tier) can be used without code changes.
"""

import os
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


class LLMProvider:
    """Base class for free model providers."""

    def __init__(self, model=None):
        self.model = model

    def generate(self, prompt, expect_json=False):
        raise NotImplementedError

    def is_available(self):
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    """Local Ollama server (fully free, runs on-host)."""

    def __init__(self, model=None, base_url=None):
        self.model = model or os.environ.get("ML_FIX_MODEL", "llama3.2")
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

    def is_available(self):
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(f"Ollama unavailable: {e}")
            return False

    def _ensure_model(self):
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            models = {m.get("name") for m in data.get("models", [])}
            if self.model not in models:
                logger.warning(
                    f"Model '{self.model}' not pulled. Run: ollama pull {self.model}"
                )
        except Exception:
            pass

    def generate(self, prompt, expect_json=False):
        self._ensure_model()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if expect_json:
            payload["format"] = "json"
            payload["system"] = (
                "You are a senior Linux SRE. Always respond with valid JSON only."
            )

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode())
        return result.get("response", "")


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible HTTP endpoint (local llama.cpp, free tiers)."""

    def __init__(self, model=None, base_url=None, api_key=None):
        self.model = model or os.environ.get("ML_FIX_MODEL", "local-model")
        self.base_url = (base_url or os.environ.get("ML_FIX_API_BASE", "http://localhost:8080/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("ML_FIX_API_KEY", "not-needed")

    def is_available(self):
        try:
            req = urllib.request.Request(f"{self.base_url}/models")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(f"OpenAI-compatible endpoint unavailable: {e}")
            return False

    def generate(self, prompt, expect_json=False):
        messages = [
            {"role": "system", "content": "You are a senior Linux SRE. Respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"} if expect_json else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]


def get_provider():
    """Return the best available free provider (Ollama preferred)."""
    provider_name = os.environ.get("ML_FIX_PROVIDER", "ollama").lower()

    if provider_name == "openai-compatible":
        provider = OpenAICompatibleProvider()
    else:
        provider = OllamaProvider()

    if provider.is_available():
        return provider

    fallback = OllamaProvider()
    if fallback.is_available():
        logger.warning("Configured provider unavailable, falling back to Ollama")
        return fallback

    logger.error("No free LLM provider available")
    return None
