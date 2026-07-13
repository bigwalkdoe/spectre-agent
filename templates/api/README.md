# Template: REST API

Simple FastAPI REST API scaffold with Pydantic schemas, config, and health check endpoints. Lightweight alternative to the full microservice template — no database or message queue dependencies.

## Quickstart

```bash
cp -r ~/.spectre/templates/api ./my-api
cd my-api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn src.api.main:app --reload
```

## Structure

```
src/api/
├── __init__.py
├── config.py    # Pydantic-settings from env (prefix API_)
├── main.py      # FastAPI app factory with global error handler
├── routes.py    # Route definitions (/health, /ping)
└── schemas.py   # Pydantic request/response models
tests/
└── test_api.py
pyproject.toml
```

## Test

```bash
pytest
```
