# Service

Modelink microservice.

## Quickstart

```bash
cp -r ~/.spectre/templates/microservice ./my-service
cd my-service
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn service.main:app --reload
```

## Structure

```
src/service/
├── __init__.py
├── config.py          # Pydantic settings from env
├── database.py        # Async SQLAlchemy engine and session
├── main.py            # FastAPI app factory
├── models.py          # SQLAlchemy ORM models
├── routes.py          # API route handlers
└── schemas.py         # Pydantic request/response models
tests/
└── test_api.py
pyproject.toml
```
