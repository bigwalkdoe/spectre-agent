from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "API"
    debug: bool = False
    api_key: str | None = None

    model_config = {"env_prefix": "API_"}


settings = Settings()
