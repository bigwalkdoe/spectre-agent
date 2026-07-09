# Create a FastAPI Microservice

## Steps

1. Create project directory with `src/`, `tests/`, `migrations/`, `docker/`, `docs/`
2. Create `pyproject.toml` with dependencies (fastapi, uvicorn, sqlalchemy, alembic, pydantic-settings, redis, httpx, pytest, pytest-asyncio, ruff, mypy)
3. Create `src/main.py` — FastAPI app factory
4. Create `src/config.py` — Pydantic settings from env
5. Create `src/database.py` — async SQLAlchemy engine and session
6. Create `src/models/` — SQLAlchemy ORM models
7. Create `src/schemas/` — Pydantic request/response models
8. Create `src/routes/` — API route modules
9. Create `src/services/` — Business logic layer
10. Create `Dockerfile` — multi-stage build
11. Create `docker-compose.yml` — service + postgres + redis
12. Create `tests/` — conftest.py + test files
13. Create `alembic.ini` and `migrations/`
14. Run `ruff format && ruff check && mypy src/`
