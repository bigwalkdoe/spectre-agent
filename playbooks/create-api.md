# Create an API Endpoint

## Steps

1. Define Pydantic schemas (request, response) in `src/schemas/`
2. Define SQLAlchemy model (if new table) in `src/models/`
3. Create Alembic migration (if new table or column)
4. Implement service function in `src/services/`
5. Implement route handler in `src/routes/`
6. Register router in `src/main.py`
7. Write tests — happy path, validation errors, not-found, auth failures
8. Run tests and lint
