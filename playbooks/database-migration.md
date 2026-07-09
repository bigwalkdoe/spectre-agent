# Database Migration Playbook

## Steps

1. **Generate migration** — `alembic revision --autogenerate -m "description"`
2. **Review generated file** — check upgrade and downgrade paths, verify column types
3. **Test locally** — `alembic upgrade head` on a copy of production data
4. **Handle data migrations** — separate data migration from schema migration (two revisions)
5. **Deploy** — run `alembic upgrade head` as a pre-deploy step, not at app startup
6. **Rollback plan** — verify `alembic downgrade -1` works before merging
