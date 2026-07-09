# API Versioning Playbook

## Strategy

Use URL path versioning: `/api/v1/items`, `/api/v2/items`.

## Steps

1. **Create versioned router** — `APIRouter(prefix="/api/v1/items")`
2. **Mount in app factory** — `app.include_router(v1_router)` and `app.include_router(v2_router)`
3. **Deprecate old version** — add `Sunset` and `Deprecation` response headers on v1 endpoints
4. **Communicate timeline** — document deprecation date, migration guide
5. **Remove old version** — only after deprecation window expires and all clients migrate
