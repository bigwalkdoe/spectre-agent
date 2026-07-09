# Architecture Guidelines

## Modelink Ecosystem

Modelink is an AI engineering platform. Core architectural principles:

- **Modular microservices**: Each service is independently deployable.
- **API-first**: All communication between services is via well-defined REST or gRPC APIs.
- **Event-driven**: Async communication via Redis Pub/Sub or message queues where appropriate.
- **Stateless services**: State lives in PostgreSQL (primary), Redis (cache/queue), or object storage.
- **AI as infrastructure**: LLM calls are abstracted behind a gateway/service layer.

## Repository Structure (Convention)

```
project/
├── src/          # Application source
├── tests/        # Test suite
├── migrations/   # Database migrations (Alembic)
├── docs/         # Documentation
├── docker/       # Dockerfiles and compose files
├── .github/      # GitHub Actions workflows
└── README.md
```

## Design Decisions

1. **FastAPI** for Python services — async, auto-docs, Pydantic integration.
2. **SQLAlchemy 2.0** with async drivers for PostgreSQL.
3. **Alembic** for schema migrations.
4. **Next.js** for frontend applications.
5. **Podman** for container builds and local development.
6. **Ollama** for local LLM inference, Azure OpenAI for production.
