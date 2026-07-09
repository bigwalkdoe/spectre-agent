from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Modelink Gateway"
    debug: bool = False

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000

    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    # Upstream LLM providers
    openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # API Authentication (comma-separated in env)
    api_keys: str = ""

    # Security
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]


settings = Settings()
