# PostgreSQL Patterns

- asyncpg driver with SQLAlchemy async
- UUID primary keys (`uuid-ossp` extension)
- Timestamps with timezone (`TIMESTAMPTZ`)
- JSONB for flexible attributes
- Indexes on foreign keys and frequently queried columns
- Alembic for migrations — autogenerate with `alembic revision --autogenerate`
